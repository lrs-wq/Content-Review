"""HTTP clients used by video-audit-service to reuse image and text services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.core.frame_sampler import SampledFrame
from app.schemas.moderation import FrameAuditPayload, FrameDetectionPayload, TextReviewPayload


class ImageAuditClient:
    """HTTP client for reusing image-audit-service on sampled video frames."""

    def __init__(self, settings: Settings) -> None:
        self.url = settings.image_audit_url
        self.timeout = settings.image_audit_timeout_seconds
        self.default_skip_ocr = settings.frame_skip_ocr

    @property
    def status(self) -> str:
        return f"configured:{self.url}"

    def review_frame(
        self,
        frame: SampledFrame,
        content_id: str,
        user_id: str,
        scene: str,
        related_text: str | None,
        context: dict[str, Any],
        skip_ocr: bool,
        ocr_reason: str | None = None,
    ) -> FrameAuditPayload:
        """Submit one sampled frame to image-audit-service and normalize the response."""

        # Pass frame timing through context so downstream logs/evidence can point back to the
        # original video timestamp.
        frame_context = {
            **context,
            "source": "video-audit-service",
            "source_content_id": content_id,
            "frame_index": frame.index,
            "frame_source": frame.source,
            "timestamp_seconds": frame.timestamp_seconds,
        }
        data = {
            "content_id": f"{content_id}#frame_{frame.index:05d}",
            "user_id": user_id,
            "scene": f"{scene}:video_frame",
            "related_text": related_text or "",
            "provided_ocr_text": "",
            "skip_ocr": "true" if skip_ocr else "false",
            "context": self._json_context(frame_context),
        }
        try:
            # Use multipart upload to avoid base64 inflation and to match the manual web tester.
            with frame.path.open("rb") as stream:
                files = {"file": (frame.path.name, stream, "image/jpeg")}
                with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                    response = client.post(self.url, params={"brief": "false"}, data=data, files=files)
                    response.raise_for_status()
                    body = response.json()
            return self._to_frame_payload(frame, body, skip_ocr=skip_ocr, ocr_reason=ocr_reason)
        except Exception as exc:
            # A failed frame call is treated as review rather than allow. This preserves safety
            # when downstream image-audit-service is temporarily unavailable.
            return FrameAuditPayload(
                index=frame.index,
                timestamp_seconds=frame.timestamp_seconds,
                source=frame.source,
                action="review",
                risk_level="medium",
                labels=["frame_audit_error"],
                scores={"overall": 0.65},
                ocr_attempted=not skip_ocr,
                ocr_reason=ocr_reason,
                error=str(exc),
            )

    @staticmethod
    def _json_context(context: dict[str, Any]) -> str:
        """Serialize context as the form field expected by image-audit-service."""

        import json

        return json.dumps(context, ensure_ascii=False)

    @staticmethod
    def _to_frame_payload(
        frame: SampledFrame,
        body: dict[str, Any],
        skip_ocr: bool = False,
        ocr_reason: str | None = None,
    ) -> FrameAuditPayload:
        """Convert the image moderation JSON response into the video frame schema."""

        ocr = body.get("ocr", {}) if isinstance(body.get("ocr"), dict) else {}
        detections = []
        for item in body.get("detections", []) if isinstance(body.get("detections"), list) else []:
            if not isinstance(item, dict):
                continue
            detections.append(
                FrameDetectionPayload(
                    label=str(item.get("label", "")),
                    score=float(item.get("score", 0.0)),
                    source=str(item.get("source", "")),
                    action=str(item.get("action", "")),
                    risk_level=str(item.get("risk_level", "")),
                    evidence=item.get("evidence"),
                )
            )
        return FrameAuditPayload(
            index=frame.index,
            timestamp_seconds=frame.timestamp_seconds,
            source=frame.source,
            action=str(body.get("action", "allow")),
            risk_level=str(body.get("risk_level", "none")),
            labels=list(body.get("labels", [])),
            scores=dict(body.get("scores", {})),
            trace_id=body.get("trace_id"),
            ocr_text=str(ocr.get("text", "")),
            ocr_lines=list(ocr.get("lines", [])) if isinstance(ocr.get("lines"), list) else [],
            text_evidence=_frame_text_evidence(body),
            ocr_attempted=not skip_ocr,
            ocr_reason=ocr_reason,
            detections=detections,
            elapsed_ms=float(body.get("elapsed_ms", 0.0)),
        )


class TextAuditClient:
    """HTTP client for the aggregated video text review step."""

    def __init__(self, settings: Settings) -> None:
        self.url = settings.text_audit_url
        self.timeout = settings.text_audit_timeout_seconds

    @property
    def status(self) -> str:
        return f"configured:{self.url}"

    def review_video_text(
        self,
        content_id: str,
        user_id: str,
        scene: str,
        related_text: str | None,
        ocr_lines: list[str],
        asr_text: str,
        context: dict[str, Any],
    ) -> TextReviewPayload:
        """Review related text, selected frame OCR, and ASR transcript as one text package."""

        primary_text_parts = [item for item in [related_text, asr_text, "\n".join(ocr_lines)] if item and item.strip()]
        if not primary_text_parts:
            return TextReviewPayload(used=False, status="skipped:empty_video_text")

        # Keep the primary text bounded because text-audit-service also builds its own aggregate
        # context. Longer full transcripts can be chunked in a future async implementation.
        request_body = {
            "content_id": f"{content_id}#video_text",
            "user_id": user_id,
            "scene": f"{scene}:video_text",
            "text": "\n".join(primary_text_parts)[:3000],
            "related_text": related_text,
            "image_ocr_text": ocr_lines,
            "video_transcript": asr_text or None,
            "context": {
                **context,
                "source": "video-audit-service",
                "source_content_id": content_id,
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
            # If aggregated video text cannot be checked, manual review is safer than allowing a
            # possibly risky transcript/OCR package through silently.
            return TextReviewPayload(
                used=True,
                status="error",
                action="review",
                risk_level="medium",
                labels=["video_text_unchecked"],
                score=0.65,
                error=str(exc),
            )


def _frame_text_evidence(body: dict[str, Any]) -> list[str]:
    """Extract concise OCR text evidence returned by image-audit-service."""

    text_review = body.get("text_review")
    if not isinstance(text_review, dict):
        return []
    evidence = text_review.get("evidence", [])
    if not isinstance(evidence, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in evidence if str(item).strip()))[:10]


def _extract_text_evidence(body: dict[str, Any]) -> list[str]:
    """Keep only matched terms from text-audit-service for compact video reasons."""

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
