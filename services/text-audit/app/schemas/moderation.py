"""Pydantic schemas shared by the text moderation HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field


RiskLevel = Literal["none", "low", "medium", "high"]
Action = Literal["allow", "review", "block"]

ACTION_LABELS = {
    "allow": "放行",
    "review": "人工复核",
    "block": "拦截",
}

RISK_LEVEL_LABELS = {
    "none": "无风险",
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
}

LABEL_NAMES = {
    "adult": "成人低俗风险",
    "ad": "广告引流风险",
    "fraud": "诈骗风险",
    "gambling": "赌博风险",
    "political": "涉政风险",
    "violence": "暴力风险",
    "weapon": "武器风险",
    "insult": "攻击辱骂风险",
    "offensive": "攻击辱骂风险",
    "inappropriate_oral": "低俗口头语风险",
    "safe": "低风险",
    "normal": "低风险",
    "unknown": "未知风险",
}

TRIGGER_REASON_NAMES = {
    "gray_score": "综合分处于灰区",
    "complex_context": "存在复杂上下文",
    "suspicious_context_hint": "发现疑似风险语义线索",
}


def action_label(value: str) -> str:
    return ACTION_LABELS.get(str(value), str(value))


def risk_level_label(value: str) -> str:
    return RISK_LEVEL_LABELS.get(str(value), str(value))


def label_name(value: str) -> str:
    return LABEL_NAMES.get(str(value), str(value))


def trigger_reason_name(value: str) -> str:
    return TRIGGER_REASON_NAMES.get(str(value), str(value))


class TextModerationRequest(BaseModel):
    """Text request with optional multimodal context gathered by upstream services."""

    content_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    scene: str = Field(default="general")
    text: str = Field(..., min_length=1)
    related_text: str | None = Field(default=None)
    image_ocr_text: list[str] = Field(default_factory=list)
    video_transcript: str | None = Field(default=None)
    context: dict[str, Any] = Field(default_factory=dict)
    brief: bool = Field(default=True, exclude=True)


class RuleHitPayload(BaseModel):
    """A deterministic rule hit returned for explainability and audit logs."""

    type: str
    category: str
    term: str
    risk_level: str
    action: str
    score: float
    span: list[int] | None = None

    @computed_field
    @property
    def category_label(self) -> str:
        return label_name(self.category)

    @computed_field
    @property
    def action_label(self) -> str:
        return action_label(self.action)

    @computed_field
    @property
    def risk_level_label(self) -> str:
        return risk_level_label(self.risk_level)


class AgentReviewPayload(BaseModel):
    """Gray-zone context review result from the lightweight agent layer."""

    used: bool
    trigger_reason: list[str]
    risk_level: RiskLevel
    action: Action
    labels: list[str]
    score: float
    reason: str
    evidence: list[str]

    @computed_field
    @property
    def action_label(self) -> str:
        return action_label(self.action)

    @computed_field
    @property
    def risk_level_label(self) -> str:
        return risk_level_label(self.risk_level)

    @computed_field
    @property
    def labels_zh(self) -> list[str]:
        return [label_name(label) for label in self.labels]

    @computed_field
    @property
    def trigger_reason_zh(self) -> list[str]:
        return [trigger_reason_name(reason) for reason in self.trigger_reason]


class ClassifierReviewPayload(BaseModel):
    """Small classifier output normalized for API consumers."""

    enabled: bool
    label: str
    score: float
    action: Action
    risk_level: RiskLevel
    model_version: str
    error: str | None = None

    @computed_field
    @property
    def label_zh(self) -> str:
        return label_name(self.label)

    @computed_field
    @property
    def action_label(self) -> str:
        return action_label(self.action)

    @computed_field
    @property
    def risk_level_label(self) -> str:
        return risk_level_label(self.risk_level)


class TextModerationResponse(BaseModel):
    """Final text moderation decision plus evidence from all enabled layers."""

    trace_id: str
    content_id: str
    risk_level: RiskLevel
    action: Action
    labels: list[str]
    scores: dict[str, float]
    hits: list[RuleHitPayload]
    allow_hits: list[str]
    normalized_text: str
    classifier_review: ClassifierReviewPayload | None = None
    agent_review: AgentReviewPayload | None = None
    policy_version: str
    model_status: str

    @computed_field
    @property
    def action_label(self) -> str:
        return action_label(self.action)

    @computed_field
    @property
    def risk_level_label(self) -> str:
        return risk_level_label(self.risk_level)

    @computed_field
    @property
    def labels_zh(self) -> list[str]:
        return [label_name(label) for label in self.labels]


class BriefModerationResponse(BaseModel):
    """Default compact response for business callers that only need the final decision."""

    content_id: str
    result: Action
    action: Action
    risk_level: RiskLevel
    reason: str


class HealthResponse(BaseModel):
    """Readiness payload for service dependency checks."""

    status: str
    service: str
    policy_version: str
    model_status: str
    classifier_status: str
    agent_status: str

    @computed_field
    @property
    def status_label(self) -> str:
        return "正常" if self.status == "ok" else self.status
