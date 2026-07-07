"""HTTP client for sending OCR text to text-audit-service."""

from __future__ import annotations

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

        text = ocr_text.strip()
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
            with httpx.Client(timeout=self.timeout) as client:
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
