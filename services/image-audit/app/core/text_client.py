"""HTTP client for sending OCR text to text-audit-service."""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.config import Settings
from app.schemas.moderation import ImageModerationRequest, TextReviewPayload


class TextAuditClient:
    """Wraps the text service so image moderation can reuse text policy and context logic."""

    def __init__(self, settings: Settings) -> None:
        self.url = settings.text_audit_url
        self.timeout = settings.text_audit_timeout_seconds

    @property
    def status(self) -> str:
        return f"configured:{self.url}"

    def review_ocr_text(self, payload: ImageModerationRequest, ocr_text: str) -> TextReviewPayload:
        """Moderate OCR text as a labeled child item of the image request."""

        text = _clean_ocr_text_for_review(ocr_text).strip()
        if not text:
            return TextReviewPayload(used=False, status="skipped:empty_ocr_text")

        # The source fields preserve provenance so manual review can tell OCR-derived text from
        # user-entered captions or comments.
        request_body = {
            "content_id": f"{payload.content_id}#ocr",
            "user_id": payload.user_id,
            "scene": f"{payload.scene}:image_ocr",
            "text": text,
            "related_text": payload.related_text,
            "context": {
                **payload.context,
                "source": "image-audit-service",
                "source_content_id": payload.content_id,
            },
        }
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.post(self.url, params={"brief": "false"}, json=request_body)
                response.raise_for_status()
                body = response.json()
            return TextReviewPayload(
                used=True,
                status="ok",
                action=str(body.get("action", "allow")),
                risk_level=str(body.get("risk_level", "none")),
                labels=list(body.get("labels", [])),
                score=float(body.get("scores", {}).get("overall", 0.0)),
                evidence=_extract_text_evidence(body),
                trace_id=body.get("trace_id"),
            )
        except Exception as exc:
            return TextReviewPayload(
                used=True,
                status="error",
                action="review",
                risk_level="medium",
                labels=["ocr_text_unchecked"],
                score=0.65,
                error=str(exc),
            )


def _extract_text_evidence(body: dict[str, Any]) -> list[str]:
    """Keep only concise matched terms from the full text-audit response."""

    evidence: list[str] = []
    hits = body.get("hits", [])
    if isinstance(hits, list):
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            term = str(hit.get("term") or "").strip()
            if term:
                evidence.append(term)

    agent_review = body.get("agent_review")
    if isinstance(agent_review, dict):
        for item in agent_review.get("evidence", []):
            text = str(item or "").strip()
            if text:
                evidence.append(text)

    return list(dict.fromkeys(evidence))[:10]


EDITOR_UI_HINT_RE = re.compile(r"(未命名|已编辑|常规体|苹方|字号|字体|B\s*\|\s*I\s*\|\s*U)", re.IGNORECASE)
EDITOR_STYLE_RE = re.compile(r"B\s*\|\s*I\s*\|\s*U\s*\|\s*S", re.IGNORECASE)
LONG_RULER_RE = re.compile(r"(?:\b\d+(?:\.\d+)?\b\s*){3,}")


def _clean_ocr_text_for_review(text: str) -> str:
    """Drop common screenshot-editor chrome before sending OCR text to text-audit-service."""

    cleaned_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = _clean_ocr_line_for_review(raw_line)
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _clean_ocr_line_for_review(line: str) -> str:
    """Remove toolbar/ruler fragments while preserving actual document text on the same line."""

    value = " ".join(str(line or "").split())
    if not value:
        return ""
    if not EDITOR_UI_HINT_RE.search(value):
        return value

    value = re.sub(r"未命名\S*已编辑", " ", value)
    value = EDITOR_STYLE_RE.sub(" ", value)
    value = re.sub(r"(苹方-简|常规体|字号|字体)", " ", value)
    value = re.sub(r"[▶▷▸]+", " ", value)
    value = LONG_RULER_RE.sub(" ", value)
    value = re.sub(r"\b[BIUS]\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\b\d+(?:\.\d+)?\b", " ", value)
    value = re.sub(r"(^|\s)(字|重|三)(?=\s|$)", " ", value)
    value = re.sub(r"[|]+", " ", value)
    return " ".join(value.split())
