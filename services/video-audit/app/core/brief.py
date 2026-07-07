"""Compact response helpers for video moderation."""

from __future__ import annotations

from app.schemas.moderation import BriefModerationResponse, VideoModerationResponse


def to_brief_response(response: VideoModerationResponse) -> BriefModerationResponse:
    """Convert the full explainable response into the default business-facing shape."""

    return BriefModerationResponse(
        content_id=response.content_id,
        result=response.action,
        reason=_reason(response),
    )


def _reason(response: VideoModerationResponse) -> str:
    """Build a short reason from frame-level and aggregated text evidence."""

    parts: list[str] = []
    if response.evidence:
        evidence_items = []
        for item in response.evidence[:3]:
            if item.timestamp_seconds is None:
                evidence_items.append(f"{item.type}:{item.label}({item.score:.2f})")
            else:
                evidence_items.append(f"{item.type}:{item.label}@{item.timestamp_seconds:.1f}s({item.score:.2f})")
        parts.append(f"证据 {','.join(evidence_items)}")
    if response.text_review.used and response.text_review.action != "allow":
        labels = ",".join(response.text_review.labels[:5]) or response.text_review.risk_level
        parts.append(f"聚合文本审核 {labels}")
    risky_frames = [frame for frame in response.frame_results if frame.action != "allow"]
    if risky_frames and not response.evidence:
        frames = ",".join(f"{frame.index}@{frame.timestamp_seconds:.1f}s:{frame.action}" for frame in risky_frames[:3])
        parts.append(f"风险帧 {frames}")
    if response.asr.status.startswith("error"):
        parts.append("ASR异常需复核")
    if response.labels:
        parts.append(f"风险标签 {','.join(response.labels[:5])}")
    if parts:
        return "；".join(parts)
    return "视频帧、OCR和ASR聚合文本未发现明显风险"
