from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.schemas.moderation import AsrPayload, AsrSegmentPayload


@dataclass(frozen=True)
class AsrResult:
    """Wrapper used to keep ASR return shape consistent with other engines."""

    payload: AsrPayload


class AsrEngine:
    """Optional ASR adapter for video speech text.

    The first deployment keeps local ASR disabled by default. Upstream systems can pass
    provided_asr_text immediately; faster-whisper can be enabled later without changing the API.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._load_error: str | None = None

    @property
    def status(self) -> str:
        if not self.settings.asr_enabled:
            return "disabled"
        if self._model is not None:
            return f"loaded:{self.settings.asr_provider}:{self.settings.asr_model_name}"
        if self._load_error:
            return f"error:{self._load_error}"
        return f"configured:{self.settings.asr_provider}:{self.settings.asr_model_name}"

    def transcribe(self, video_path: Path, provided_asr_text: str | None) -> AsrResult:
        """Return provided transcript, skip ASR, or run the configured local ASR model."""

        started = time.perf_counter()
        text = (provided_asr_text or "").strip()
        if text:
            # Provided ASR is treated as already trusted upstream processing. It is still moderated
            # later by text-audit-service.
            return AsrResult(
                payload=AsrPayload(
                    used=True,
                    status="provided",
                    provider="provided",
                    text=text,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            )
        if not self.settings.asr_enabled:
            # Disabled ASR is not an error. Many clients will call this service with silent videos
            # or with transcripts generated elsewhere.
            return AsrResult(
                payload=AsrPayload(
                    used=False,
                    status="skipped:disabled",
                    provider=self.settings.asr_provider,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            )
        if self.settings.asr_provider != "faster_whisper":
            return AsrResult(
                payload=AsrPayload(
                    used=False,
                    status=f"skipped:unsupported_provider:{self.settings.asr_provider}",
                    provider=self.settings.asr_provider,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            )
        try:
            model = self._load_model()
            segments, _ = model.transcribe(str(video_path), vad_filter=True)
            segment_payloads: list[AsrSegmentPayload] = []
            texts: list[str] = []
            for segment in segments:
                segment_text = str(segment.text).strip()
                if not segment_text:
                    continue
                texts.append(segment_text)
                segment_payloads.append(
                    AsrSegmentPayload(
                        start=round(float(segment.start), 3),
                        end=round(float(segment.end), 3),
                        text=segment_text,
                    )
                )
            return AsrResult(
                payload=AsrPayload(
                    used=True,
                    status="ok",
                    provider=self.settings.asr_provider,
                    text="\n".join(texts),
                    segments=segment_payloads,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            )
        except Exception as exc:  # pragma: no cover - optional dependency/model runtime
            self._load_error = f"{type(exc).__name__}"
            return AsrResult(
                payload=AsrPayload(
                    used=True,
                    status="error",
                    provider=self.settings.asr_provider,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                    error=str(exc),
                )
            )

    def _load_model(self):
        """Lazily load faster-whisper so service startup stays lightweight."""

        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel  # type: ignore

        self._model = WhisperModel(
            self.settings.asr_model_name,
            device=self.settings.asr_device,
            compute_type=self.settings.asr_compute_type,
        )
        self._load_error = None
        return self._model
