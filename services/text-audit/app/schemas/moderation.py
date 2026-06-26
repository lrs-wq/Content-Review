from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["none", "low", "medium", "high"]
Action = Literal["allow", "review", "block"]


class TextModerationRequest(BaseModel):
    content_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    scene: str = Field(default="general")
    text: str = Field(..., min_length=1)
    related_text: str | None = Field(default=None)
    image_ocr_text: list[str] = Field(default_factory=list)
    video_transcript: str | None = Field(default=None)
    context: dict[str, Any] = Field(default_factory=dict)


class RuleHitPayload(BaseModel):
    type: str
    category: str
    term: str
    risk_level: str
    action: str
    score: float
    span: list[int] | None = None


class AgentReviewPayload(BaseModel):
    used: bool
    trigger_reason: list[str]
    risk_level: RiskLevel
    action: Action
    labels: list[str]
    score: float
    reason: str
    evidence: list[str]


class ClassifierReviewPayload(BaseModel):
    enabled: bool
    label: str
    score: float
    action: Action
    risk_level: RiskLevel
    model_version: str
    error: str | None = None


class TextModerationResponse(BaseModel):
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


class HealthResponse(BaseModel):
    status: str
    service: str
    policy_version: str
    model_status: str
    classifier_status: str
    agent_status: str
