from __future__ import annotations

import time
from dataclasses import dataclass
import os
from pathlib import Path

from PIL import Image

from app.core.config import Settings


@dataclass(frozen=True)
class OcrResult:
    status: str
    text: str
    lines: list[str]
    provider: str
    elapsed_ms: float
    error: str | None = None


class OcrEngine:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.enable_ocr
        self.provider = settings.ocr_provider
        self._engine = None
        self._load_error: str | None = None
        if self.enabled:
            self._load()

    @property
    def status(self) -> str:
        if self._engine is not None:
            return f"enabled:{self.provider}"
        if self.enabled:
            return f"disabled:{self._load_error or 'engine_not_loaded'}"
        return "disabled:config"

    def recognize(self, image: Image.Image, provided_text: str | None = None) -> OcrResult:
        started = time.perf_counter()
        provided = (provided_text or "").strip()
        if provided:
            lines = [line.strip() for line in provided.splitlines() if line.strip()]
            if not lines:
                lines = [provided]
            return OcrResult(
                status="provided",
                text="\n".join(lines),
                lines=lines,
                provider="provided",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            )

        if self._engine is None:
            return OcrResult(
                status="skipped",
                text="",
                lines=[],
                provider=self.provider,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                error=self._load_error or "ocr_engine_not_loaded",
            )

        try:
            if self.provider.lower() == "paddleocr":
                return self._recognize_with_paddleocr(image, started)
            return OcrResult(
                status="skipped",
                text="",
                lines=[],
                provider=self.provider,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                error=f"unsupported_ocr_provider:{self.provider}",
            )
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            return OcrResult(
                status="error",
                text="",
                lines=[],
                provider=self.provider,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                error=str(exc),
            )

    def _load(self) -> None:
        if self.provider.lower() != "paddleocr":
            self._load_error = f"unsupported_ocr_provider:{self.provider}"
            return
        try:
            os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PaddleOCR  # type: ignore

            try:
                self._engine = PaddleOCR(
                    lang="ch",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
            except TypeError:
                self._engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            self._engine = None
            self._load_error = str(exc)

    def _recognize_with_paddleocr(self, image: Image.Image, started: float) -> OcrResult:
        import numpy as np

        if hasattr(self._engine, "predict"):
            raw_result = self._engine.predict(np.array(image))
        else:
            raw_result = self._engine.ocr(np.array(image), cls=True)
        lines = self._extract_lines(raw_result)
        return OcrResult(
            status="ok",
            text="\n".join(lines),
            lines=lines,
            provider=self.provider,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _extract_lines(self, raw_result: object) -> list[str]:
        lines: list[str] = []
        self._collect_text(raw_result, lines)
        return list(dict.fromkeys(line for line in lines if line))

    def _collect_text(self, value: object, lines: list[str]) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                lines.append(text)
            return
        if isinstance(value, dict):
            for key in ("rec_text", "rec_texts", "text", "texts"):
                if key in value:
                    self._collect_text(value[key], lines)
            return
        if isinstance(value, (list, tuple)):
            if self._looks_like_legacy_text_item(value):
                self._collect_text(value[1][0], lines)
                return
            for item in value:
                self._collect_text(item, lines)
            return

        for attr in ("rec_text", "rec_texts", "text", "texts", "json"):
            if hasattr(value, attr):
                candidate = getattr(value, attr)
                if callable(candidate):
                    try:
                        candidate = candidate()
                    except TypeError:
                        continue
                self._collect_text(candidate, lines)

        if hasattr(value, "save_to_json"):
            temp_path = Path.cwd() / ".ocr_probe.json"
            try:
                value.save_to_json(str(temp_path))
                import json

                self._collect_text(json.loads(temp_path.read_text(encoding="utf-8")), lines)
            except Exception:
                pass
            finally:
                if temp_path.exists():
                    temp_path.unlink()

    @staticmethod
    def _looks_like_legacy_text_item(value: object) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[1], (list, tuple))
            and bool(value[1])
            and isinstance(value[1][0], str)
        )
