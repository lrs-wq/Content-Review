"""Compact response helpers for text moderation."""

from __future__ import annotations

from app.schemas.moderation import BriefModerationResponse, TextModerationResponse


def to_brief_response(response: TextModerationResponse) -> BriefModerationResponse:
    """Convert the full explainable response into the default business-facing shape."""

    return BriefModerationResponse(
        content_id=response.content_id,
        result=response.action,
        reason=_reason(response),
    )


def _reason(response: TextModerationResponse) -> str:
    """Build a short human-readable reason from the strongest available evidence."""

    parts: list[str] = []
    if response.hits:
        hit_text = "、".join(f"{hit.category}:{hit.term}" for hit in response.hits[:3])
        parts.append(f"命中规则 {hit_text}")
    if response.classifier_review and response.classifier_review.action != "allow":
        classifier = response.classifier_review
        parts.append(f"小模型判断 {classifier.label}({classifier.score:.2f})")
    if response.agent_review and response.agent_review.used and response.agent_review.action != "allow":
        parts.append(f"上下文审查 {response.agent_review.reason}")
    if response.labels:
        parts.append(f"风险标签 {','.join(response.labels[:5])}")
    if parts:
        return "；".join(parts)
    if response.allow_hits:
        return f"命中白名单 {','.join(response.allow_hits[:3])}"
    return "未命中风险规则，模型综合风险较低"
