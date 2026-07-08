"""Pydantic schemas shared by the text moderation HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["none", "low", "medium", "high"]
Action = Literal["allow", "review", "block"]


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


class ClassifierReviewPayload(BaseModel):
    """Small classifier output normalized for API consumers."""

    enabled: bool
    label: str
    score: float
    action: Action
    risk_level: RiskLevel
    model_version: str
    error: str | None = None


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
