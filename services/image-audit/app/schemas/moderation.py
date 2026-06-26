from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


RiskLevel = Literal["none", "low", "medium", "high"]
Action = Literal["allow", "review", "block", "mask"]


class ImageModerationRequest(BaseModel):
    content_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    scene: str = Field(default="general")
    image_base64: str | None = None
    image_url: str | None = None
    image_bytes: bytes | None = Field(default=None, exclude=True)
    image_mime: str | None = None
    image_filename: str | None = None
    related_text: str | None = None
    provided_ocr_text: str | None = None
    skip_ocr: bool = False
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_image_source(self) -> "ImageModerationRequest":
        if not self.image_base64 and not self.image_url and not self.image_bytes:
            raise ValueError("one of image_base64, image_url, or image_bytes is required")
        return self


class ImageMetadata(BaseModel):
    width: int
    height: int
    format: str
    mode: str
    mime_type: str
    bytes: int
    sha256: str


class DetectionPayload(BaseModel):
    label: str
    score: float
    box: list[float] | None = None
    source: str
    action: Action = "review"
    risk_level: RiskLevel = "medium"
    evidence: str | None = None


class OcrPayload(BaseModel):
    status: str
    text: str
    lines: list[str]
    provider: str
    elapsed_ms: float
    error: str | None = None


class TextReviewPayload(BaseModel):
    used: bool
    status: str
    action: str = "allow"
    risk_level: str = "none"
    labels: list[str] = Field(default_factory=list)
    score: float = 0.0
    trace_id: str | None = None
    error: str | None = None


class ImageModerationResponse(BaseModel):
    trace_id: str
    content_id: str
    risk_level: RiskLevel
    action: Action
    labels: list[str]
    scores: dict[str, float]
    image: ImageMetadata
    ocr: OcrPayload
    text_review: TextReviewPayload
    detections: list[DetectionPayload]
    policy_version: str
    model_status: dict[str, str]
    elapsed_ms: float


class HealthResponse(BaseModel):
    status: str
    service: str
    policy_version: str
    visual_status: str
    vision_safety_status: str
    ocr_status: str
    text_audit_status: str
