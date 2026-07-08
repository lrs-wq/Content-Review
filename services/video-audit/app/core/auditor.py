"""Pipeline coordinator for video moderation."""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.asr import AsrEngine
from app.core.clients import ImageAuditClient, TextAuditClient
from app.core.config import Settings
from app.core.decision import VideoDecisionMaker
from app.core.frame_sampler import FrameSampler
from app.core.selective_ocr import SelectiveOcrPlanner
from app.core.video_probe import VideoProbe
from app.schemas.moderation import VideoModerationResponse


@dataclass(frozen=True)
class VideoAuditInput:
    """Normalized request payload used internally after FastAPI has stored the upload on disk."""

    content_id: str
    user_id: str
    scene: str
    related_text: str | None
    provided_asr_text: str | None
    skip_ocr: bool
    context: dict
    video_path: Path
    filename: str
    mime_type: str
    bytes: int


class VideoAuditor:
    """Coordinates the full video moderation pipeline.

    The video service deliberately stays thin: it validates and samples video, then reuses the
    already established image-audit and text-audit services. This keeps video moderation
    explainable and avoids introducing a separate video model in the first implementation.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.policy_version = settings.policy_version
        self.probe = VideoProbe(settings)
        self.sampler = FrameSampler(settings)
        self.image_client = ImageAuditClient(settings)
        self.text_client = TextAuditClient(settings)
        self.asr = AsrEngine(settings)
        self.ocr_planner = SelectiveOcrPlanner(settings)
        self.decider = VideoDecisionMaker()

    @property
    def ffmpeg_status(self) -> str:
        return self.probe.status

    @property
    def image_audit_status(self) -> str:
        return self.image_client.status

    @property
    def text_audit_status(self) -> str:
        return self.text_client.status

    @property
    def asr_status(self) -> str:
        return self.asr.status

    @property
    def selective_ocr_status(self) -> str:
        return self.ocr_planner.status

    def audit(self, payload: VideoAuditInput) -> VideoModerationResponse:
        started = time.perf_counter()

        # Validate the file and collect immutable metadata before doing expensive work. This is
        # where videos longer than the configured 60-second limit are rejected.
        probe_result = self.probe.probe(payload.video_path, payload.filename, payload.mime_type, payload.bytes)

        # ASR is optional. If upstream already provides a transcript, we use it directly and avoid
        # local transcription cost. If the video has no audio stream, ASR is skipped cleanly.
        has_audio_stream = bool(probe_result.metadata.audio_codec)
        asr_result = self.asr.transcribe(
            payload.video_path,
            payload.provided_asr_text,
            has_audio=has_audio_stream,
        ).payload

        # Frames are temporary evidence for this synchronous request only. Persisting frame images
        # should be added later in an evidence store if manual review needs snapshots.
        with tempfile.TemporaryDirectory(prefix="video_audit_frames_") as temp_dir:
            frames = self.sampler.sample(payload.video_path, Path(temp_dir), probe_result.metadata.duration_seconds)
            frame_results = []

            # Plan which frames deserve OCR before calling the image service. Full-frame OCR is
            # expensive on 1080p frames, so the default path audits every frame visually but only
            # OCRs a small number of high-value frames.
            ocr_plan = self.ocr_planner.plan(frames)
            ocr_timestamps: list[float] = []
            for frame in frames:
                skip_ocr, ocr_reason = self._frame_ocr_choice(payload.skip_ocr, frame, ocr_plan)

                # First pass: always audit the sampled frame visually. Most frames run with
                # skip_ocr=True, which keeps video latency near the image-classification path.
                result = self.image_client.review_frame(
                    frame=frame,
                    content_id=payload.content_id,
                    user_id=payload.user_id,
                    scene=payload.scene,
                    related_text=payload.related_text,
                    context=payload.context,
                    skip_ocr=skip_ocr,
                    ocr_reason=ocr_reason,
                )
                if not skip_ocr:
                    ocr_timestamps.append(frame.timestamp_seconds)

                # Second pass: if a fast visual pass discovers a QR/risky frame, spend the OCR
                # budget on that frame. This catches poster-like frames without OCRing everything.
                if skip_ocr and self.settings.frame_skip_ocr and not payload.skip_ocr:
                    should_retry, retry_reason = self.ocr_planner.should_retry_with_ocr(
                        frame,
                        result,
                        ocr_timestamps,
                    )
                    if should_retry:
                        result = self.image_client.review_frame(
                            frame=frame,
                            content_id=payload.content_id,
                            user_id=payload.user_id,
                            scene=payload.scene,
                            related_text=payload.related_text,
                            context=payload.context,
                            skip_ocr=False,
                            ocr_reason=retry_reason,
                        )
                        ocr_timestamps.append(frame.timestamp_seconds)
                frame_results.append(result)

                # Optional fast-fail mode: stop after a decisive block to avoid doing unnecessary
                # work on the remaining frames. The default is disabled so 60-second test videos
                # still return evidence across the full sampled timeline.
                if self.settings.stop_on_block and result.action == "block":
                    break

        # Deduplicate OCR lines across frames. Video overlays often repeat the same timestamp,
        # watermark, or call-to-action text on every sampled frame.
        ocr_lines = self._unique_lines(line for frame in frame_results for line in frame.ocr_lines)
        ocr_text = "\n".join(ocr_lines)

        # Run text moderation once over the aggregated text package: related text, OCR lines, and
        # ASR transcript. This mirrors the project-wide "context aggregation" strategy.
        text_review = self.text_client.review_video_text(
            content_id=payload.content_id,
            user_id=payload.user_id,
            scene=payload.scene,
            related_text=payload.related_text,
            ocr_lines=ocr_lines,
            asr_text=asr_result.text,
            context=payload.context,
        )

        # Fuse frame-level visual risks and video-level text risks into one final action.
        decision = self.decider.decide(frame_results, text_review, bool(asr_result.text.strip()))

        return VideoModerationResponse(
            trace_id=self._trace_id(),
            content_id=payload.content_id,
            risk_level=decision.risk_level,  # type: ignore[arg-type]
            action=decision.action,  # type: ignore[arg-type]
            labels=decision.labels,
            scores=decision.scores,
            video=probe_result.metadata,
            sampled_frames=len(frames),
            audited_frames=len(frame_results),
            frame_results=frame_results,
            ocr_text=ocr_text,
            asr=asr_result,
            text_review=text_review,
            evidence=decision.evidence,
            policy_version=self.policy_version,
            model_status={
                "ffmpeg": self.ffmpeg_status,
                "image_audit": self.image_audit_status,
                "text_audit": self.text_audit_status,
                "asr": self.asr_status,
                "selective_ocr": self.selective_ocr_status,
            },
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _frame_ocr_choice(self, force_skip_ocr: bool, frame, ocr_plan) -> tuple[bool, str | None]:
        """Return whether OCR should be skipped for a frame and the reason if OCR is enabled."""

        if force_skip_ocr:
            return True, "forced_skip"
        if not self.settings.frame_skip_ocr:
            return False, "full_frame_ocr"
        reason = ocr_plan.reason(frame)
        if reason:
            return False, reason
        return True, None

    @staticmethod
    def _unique_lines(lines) -> list[str]:
        """Preserve first occurrence order while removing repeated OCR lines."""

        seen = set()
        result = []
        for raw_line in lines:
            line = str(raw_line).strip()
            if not line or line in seen:
                continue
            seen.add(line)
            result.append(line)
        return result

    @staticmethod
    def _trace_id() -> str:
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"vid_tr_{now}_{uuid4().hex[:8]}"
