"""Compact response helpers for image moderation."""

from __future__ import annotations

from app.schemas.moderation import BriefModerationResponse, ImageModerationResponse


def to_brief_response(response: ImageModerationResponse) -> BriefModerationResponse:
    """Convert the full explainable response into the default business-facing shape."""

    return BriefModerationResponse(
        content_id=response.content_id,
        result=response.action,
        reason=_reason(response),
    )


def _reason(response: ImageModerationResponse) -> str:
    """Build a short reason from visual, OCR, text, and multimodal safety evidence."""

    parts: list[str] = []
    if response.detections:
        detections = []
        for detection in response.detections[:3]:
            label = f"{detection.label}({detection.score:.2f})"
            if detection.source:
                label = f"{label}/{detection.source}"
            detections.append(label)
        parts.append(f"视觉命中 {','.join(detections)}")
    if response.text_review.used and response.text_review.action != "allow":
        labels = ",".join(response.text_review.labels[:5]) or response.text_review.risk_level
        parts.append(f"OCR/关联文本审核 {labels}")
    if response.ocr.status == "error":
        parts.append("OCR异常需复核")
    if response.labels:
        parts.append(f"风险标签 {','.join(response.labels[:5])}")
    if parts:
        return "；".join(parts)
    return "视觉、OCR和文本审核未发现明显风险"
