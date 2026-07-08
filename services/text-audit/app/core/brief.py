"""Compact response helpers for text moderation."""

from __future__ import annotations

from app.schemas.moderation import BriefModerationResponse, TextModerationResponse


LABEL_NAMES = {
    "adult": "成人低俗风险",
    "ad": "广告引流风险",
    "fraud": "诈骗风险",
    "gambling": "赌博风险",
    "political": "涉政风险",
    "violence": "暴力风险",
    "weapon": "武器风险",
    "offensive": "攻击辱骂风险",
    "safe": "低风险",
}

AGENT_REASON_NAMES = {
    "context agent found direct violent intent": "发现明确暴力意图",
    "context agent found violent wording that needs review": "发现疑似暴力表述，需人工复核",
    "context agent found traffic diversion or advertising pattern": "发现疑似广告引流模式",
    "context agent found fraud-like earning promise": "发现疑似诈骗收益承诺",
    "no additional context risk found": "上下文未发现额外风险",
    "agent not triggered": "上下文审查未触发",
}


def to_brief_response(response: TextModerationResponse) -> BriefModerationResponse:
    """Convert the full explainable response into the default business-facing shape."""

    return BriefModerationResponse(
        content_id=response.content_id,
        result=response.action,
        action=response.action,
        risk_level=response.risk_level,
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
        parts.append(f"小模型判断 {_label_name(classifier.label)}({classifier.score:.2f})")
    if response.agent_review and response.agent_review.used and response.agent_review.action != "allow":
        parts.append(f"上下文审查 {_agent_reason(response.agent_review.reason)}")
    if response.labels:
        parts.append(f"风险标签 {_label_list(response.labels[:5])}")
    if parts:
        return "；".join(parts)
    if response.allow_hits:
        return f"命中白名单 {','.join(response.allow_hits[:3])}"
    return "未命中风险规则，模型综合风险较低"


def _label_list(labels: list[str]) -> str:
    """Translate technical labels for business-facing brief reasons."""

    return ",".join(_label_name(label) for label in labels if label)


def _label_name(label: str) -> str:
    """Return a Chinese display name for a technical label."""

    return LABEL_NAMES.get(str(label), str(label))


def _agent_reason(reason: str) -> str:
    """Return a Chinese display reason for internal agent verdicts."""

    return AGENT_REASON_NAMES.get(str(reason), str(reason))
