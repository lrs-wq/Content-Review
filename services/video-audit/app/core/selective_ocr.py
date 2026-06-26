from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.frame_sampler import SampledFrame
from app.schemas.moderation import FrameAuditPayload


@dataclass(frozen=True)
class OcrFramePlan:
    """Selected OCR frames keyed by sampled frame index."""

    reasons_by_index: dict[int, str]

    def should_ocr(self, frame: SampledFrame) -> bool:
        return frame.index in self.reasons_by_index

    def reason(self, frame: SampledFrame) -> str | None:
        return self.reasons_by_index.get(frame.index)


class SelectiveOcrPlanner:
    """Chooses a small OCR budget for video frames.

    PaddleOCR can dominate total video latency when every 1080p frame is processed. The planner
    keeps the fast visual pass for all frames, then spends OCR only on frames that are likely to
    contain useful text evidence: keyframes, text-like regions, QR/risk frames, or configured
    retry labels.
    """

    # Labels that suggest frame text may be important enough to justify a second image-audit pass
    # with OCR enabled.
    retry_labels = {"qr_code", "ad", "fraud", "url", "ocr_text_unchecked"}

    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.selective_ocr_enabled
        self.max_frames = max(0, settings.selective_ocr_max_frames)
        self.include_first = settings.selective_ocr_include_first_frame
        self.include_last = settings.selective_ocr_include_last_frame
        self.min_interval_seconds = max(0.0, settings.selective_ocr_min_interval_seconds)
        self.text_region_enabled = settings.selective_ocr_text_region_enabled
        self.text_region_score = settings.selective_ocr_text_region_score
        self.retry_on_qr_or_risk = settings.selective_ocr_retry_on_qr_or_risk

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        return (
            "enabled:"
            f"max_frames={self.max_frames},"
            f"text_region={self.text_region_enabled},"
            f"retry_on_qr_or_risk={self.retry_on_qr_or_risk}"
        )

    def plan(self, frames: list[SampledFrame]) -> OcrFramePlan:
        """Build the initial OCR plan before any image-audit results are available."""

        if not self.enabled or self.max_frames <= 0 or not frames:
            return OcrFramePlan(reasons_by_index={})

        candidates: dict[int, tuple[float, str]] = {}

        # First and last frames are cheap anchors for short videos. The default includes the first
        # frame only, because many phone videos repeat overlays and OCR is expensive.
        if self.include_first:
            self._add_candidate(candidates, frames[0].index, 1.0, "keyframe:first")
        if self.include_last and frames[-1].index != frames[0].index:
            self._add_candidate(candidates, frames[-1].index, 0.95, "keyframe:last")

        # A lightweight OpenCV detector looks for dense horizontal edge groups that resemble text.
        # It is intentionally approximate: it is used only to decide whether to pay the OCR cost.
        if self.text_region_enabled:
            for frame in frames:
                score = self._text_region_score(frame)
                if score >= self.text_region_score:
                    self._add_candidate(candidates, frame.index, 0.7 + min(score, 1.0), f"text_region:{score:.2f}")

        frames_by_index = {frame.index: frame for frame in frames}
        selected: dict[int, str] = {}
        selected_timestamps: list[float] = []

        # Highest-priority candidates win, but keep temporal spacing so repeated overlays do not
        # consume the whole OCR budget.
        for index, (_, reason) in sorted(candidates.items(), key=lambda item: item[1][0], reverse=True):
            frame = frames_by_index[index]
            if not self._can_add(frame.timestamp_seconds, selected_timestamps):
                continue
            selected[index] = reason
            selected_timestamps.append(frame.timestamp_seconds)
            if len(selected) >= self.max_frames:
                break
        return OcrFramePlan(reasons_by_index=selected)

    def should_retry_with_ocr(
        self,
        frame: SampledFrame,
        result: FrameAuditPayload,
        ocr_timestamps: list[float],
    ) -> tuple[bool, str | None]:
        """Decide whether a fast no-OCR frame result should be retried with OCR enabled."""

        if not self.enabled or not self.retry_on_qr_or_risk or self.max_frames <= 0:
            return False, None
        if result.ocr_attempted or len(ocr_timestamps) >= self.max_frames:
            return False, None
        if not self._can_add(frame.timestamp_seconds, ocr_timestamps):
            return False, None
        labels = set(result.labels)
        if labels & self.retry_labels:
            return True, f"risk_label:{','.join(sorted(labels & self.retry_labels))}"
        if result.action in {"review", "block"}:
            return True, f"risk_action:{result.action}"
        if float(result.scores.get("qr_code", 0.0)) >= 0.65:
            return True, "qr_score"
        return False, None

    def _text_region_score(self, frame: SampledFrame) -> float:
        """Estimate whether a sampled frame contains text-like regions using cheap image features."""

        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            gray = cv2.imread(str(frame.path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                return 0.0
            height, width = gray.shape[:2]

            # Downscale large frames before analysis. The goal is routing, not precise OCR.
            if width > 640:
                scale = 640.0 / float(width)
                gray = cv2.resize(gray, (640, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)

            # Text usually forms compact horizontal edge clusters. Canny + morphology gives a
            # low-cost signal without loading the OCR engine.
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            edges = cv2.Canny(gray, 80, 180)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 3))
            closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            text_like = 0
            edge_pixels = 0
            for contour in contours:
                x, y, box_width, box_height = cv2.boundingRect(contour)

                # Filter out tiny noise, large objects, and shapes that do not resemble text lines.
                if box_width < 24 or box_height < 6:
                    continue
                if box_height > gray.shape[0] * 0.22:
                    continue
                aspect = box_width / max(1, box_height)
                if aspect < 1.2 or aspect > 28:
                    continue
                area = box_width * box_height
                if area < 100 or area > gray.size * 0.18:
                    continue
                roi = edges[y : y + box_height, x : x + box_width]
                density = float(np.count_nonzero(roi)) / float(max(1, roi.size))
                if density < 0.035:
                    continue
                text_like += 1
                edge_pixels += int(np.count_nonzero(roi))

            # Combine number of text-like boxes and edge coverage into one bounded routing score.
            contour_score = min(1.0, text_like / 10.0)
            edge_score = min(1.0, edge_pixels / float(max(1, gray.size)) * 18.0)
            return max(contour_score, edge_score)
        except Exception:
            return 0.0

    def _add_candidate(
        self,
        candidates: dict[int, tuple[float, str]],
        index: int,
        priority: float,
        reason: str,
    ) -> None:
        """Insert or merge a candidate while retaining its strongest priority."""

        current = candidates.get(index)
        if current is None:
            candidates[index] = (priority, reason)
            return
        current_priority, current_reason = current
        if priority > current_priority:
            candidates[index] = (priority, f"{current_reason};{reason}")
        else:
            candidates[index] = (current_priority, f"{current_reason};{reason}")

    def _can_add(self, timestamp: float, selected_timestamps: list[float]) -> bool:
        """Check OCR budget and minimum spacing between selected frames."""

        if len(selected_timestamps) >= self.max_frames:
            return False
        if self.min_interval_seconds <= 0:
            return True
        return all(abs(timestamp - selected) >= self.min_interval_seconds for selected in selected_timestamps)
