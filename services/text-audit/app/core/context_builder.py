from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.normalizer import normalize_text
from app.schemas.moderation import TextModerationRequest


@dataclass(frozen=True)
class ContextPackage:
    scene: str
    primary_text: str
    aggregate_text: str
    fields: dict[str, str | list[str]]
    has_complex_context: bool


class ContextBuilder:
    def __init__(self, max_chars: int = 3000) -> None:
        self.max_chars = max_chars

    def build(self, payload: TextModerationRequest) -> ContextPackage:
        fields: dict[str, str | list[str]] = {
            "text": payload.text,
        }

        if payload.related_text:
            fields["related_text"] = payload.related_text
        if payload.image_ocr_text:
            fields["image_ocr_text"] = payload.image_ocr_text
        if payload.video_transcript:
            fields["video_transcript"] = payload.video_transcript

        self._copy_context_fields(payload.context, fields)

        aggregate_parts = self._flatten_fields(fields)
        aggregate_text = "\n".join(aggregate_parts)
        if len(aggregate_text) > self.max_chars:
            aggregate_text = aggregate_text[: self.max_chars]

        has_complex_context = any(key != "text" for key in fields)
        return ContextPackage(
            scene=payload.scene,
            primary_text=payload.text,
            aggregate_text=aggregate_text,
            fields=fields,
            has_complex_context=has_complex_context,
        )

    def _copy_context_fields(self, context: dict[str, Any], fields: dict[str, str | list[str]]) -> None:
        for key, value in context.items():
            if value is None:
                continue
            if isinstance(value, str) and value.strip():
                fields[key] = value.strip()
            elif isinstance(value, list):
                text_items = [str(item).strip() for item in value if str(item).strip()]
                if text_items:
                    fields[key] = text_items

    @staticmethod
    def _flatten_fields(fields: dict[str, str | list[str]]) -> list[str]:
        parts: list[str] = []
        for key, value in fields.items():
            if isinstance(value, list):
                joined = "\n".join(value)
                if joined.strip():
                    parts.append(f"[{key}]\n{joined}")
            elif value.strip():
                parts.append(f"[{key}]\n{value.strip()}")
        return parts


def normalized_context_text(package: ContextPackage) -> str:
    return normalize_text(package.aggregate_text)

