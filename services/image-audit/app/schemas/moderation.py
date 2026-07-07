"""Pydantic schemas for image moderation requests and responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


RiskLevel = Literal["none", "low", "medium", "high"]
Action = Literal["allow", "review", "block", "mask"]


class ImageModerationRequest(BaseModel):
    """Image request supporting JSON base64/URL input and multipart-upload bytes."""

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
    brief: bool = Field(default=True, exclude=True)

    @model_validator(mode="after")
    def require_image_source(self) -> "ImageModerationRequest":
        """Ensure the auditor always has exactly some image source to load."""

        if not self.image_base64 and not self.image_url and not self.image_bytes:
            raise ValueError("one of image_base64, image_url, or image_bytes is required")
        return self


class ImageMetadata(BaseModel):
    """Stable image facts returned with every moderation response."""

    width: int
    height: int
    format: str
    mode: str
    mime_type: str
    bytes: int
    sha256: str


class DetectionPayload(BaseModel):
    """One visual or multimodal risk signal found in the image."""

    label: str
    score: float
    box: list[float] | None = None
    source: str
    action: Action = "review"
    risk_level: RiskLevel = "medium"
    evidence: str | None = None


class OcrPayload(BaseModel):
    """OCR result returned whether text was provided, recognized, skipped, or errored."""

    status: str
    text: str
    lines: list[str]
    provider: str
    elapsed_ms: float
    error: str | None = None


class TextReviewPayload(BaseModel):
    """Text-audit-service result for OCR or provided image text."""

    used: bool
    status: str
    action: str = "allow"
    risk_level: str = "none"
    labels: list[str] = Field(default_factory=list)
    score: float = 0.0
    trace_id: str | None = None
    error: str | None = None


class ImageModerationResponse(BaseModel):
    """Final image moderation response combining visual, OCR, and text risk."""

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


class BriefModerationResponse(BaseModel):
    """Default compact response for business callers that only need the final decision."""

    content_id: str
    result: Action
    reason: str


class HealthResponse(BaseModel):
    """Readiness response used by probes and the web test page."""

    status: str
    service: str
    policy_version: str
    visual_status: str
    vision_safety_status: str
    ocr_status: str
    text_audit_status: str
