"""Pydantic schemas for video moderation and dependency health responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["none", "low", "medium", "high"]
Action = Literal["allow", "review", "block"]


class VideoMetadata(BaseModel):
    """Stable metadata extracted by ffprobe and returned with every video result."""

    filename: str
    mime_type: str
    bytes: int
    sha256: str
    duration_seconds: float
    width: int
    height: int
    format_name: str
    video_codec: str
    audio_codec: str | None = None


class FrameDetectionPayload(BaseModel):
    """Single visual detection returned by image-audit-service for a sampled frame."""

    label: str
    score: float
    source: str
    action: str
    risk_level: str
    evidence: str | None = None


class FrameAuditPayload(BaseModel):
    """Normalized moderation result for one sampled video frame."""

    index: int
    timestamp_seconds: float
    source: str = "fixed"
    action: str
    risk_level: str
    labels: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    trace_id: str | None = None
    ocr_text: str = ""
    ocr_lines: list[str] = Field(default_factory=list)
    text_evidence: list[str] = Field(default_factory=list)
    ocr_attempted: bool = False
    ocr_reason: str | None = None
    detections: list[FrameDetectionPayload] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    error: str | None = None


class AsrSegmentPayload(BaseModel):
    """Timestamped ASR segment for local transcription providers."""

    start: float
    end: float
    text: str


class AsrPayload(BaseModel):
    """Speech-to-text result, whether provided by upstream or generated locally."""

    used: bool
    status: str
    provider: str
    text: str = ""
    segments: list[AsrSegmentPayload] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    error: str | None = None


class TextReviewPayload(BaseModel):
    """Aggregated text moderation result for OCR, ASR, and related text."""

    used: bool
    status: str
    action: str = "allow"
    risk_level: str = "none"
    labels: list[str] = Field(default_factory=list)
    score: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    trace_id: str | None = None
    error: str | None = None


class EvidencePayload(BaseModel):
    """Compact evidence item suitable for UI display and manual review queues."""

    type: str
    label: str
    action: str
    risk_level: str
    score: float
    source: str
    timestamp_seconds: float | None = None
    text: str | None = None


class VideoModerationResponse(BaseModel):
    """Top-level video moderation response returned by /v1/moderation/video/upload."""

    trace_id: str
    content_id: str
    risk_level: RiskLevel
    action: Action
    labels: list[str]
    scores: dict[str, float]
    video: VideoMetadata
    sampled_frames: int
    audited_frames: int
    frame_results: list[FrameAuditPayload]
    ocr_text: str
    asr: AsrPayload
    text_review: TextReviewPayload
    evidence: list[EvidencePayload]
    policy_version: str
    model_status: dict[str, str]
    elapsed_ms: float


class BriefModerationResponse(BaseModel):
    """Default compact response for business callers that only need the final decision."""

    content_id: str
    result: Action
    reason: str


class HealthResponse(BaseModel):
    """Readiness payload for service and dependency status checks."""

    status: str
    service: str
    policy_version: str
    max_duration_seconds: float
    frame_sample_fps: float
    max_sampled_frames: int
    ffmpeg_status: str
    image_audit_status: str
    text_audit_status: str
    asr_status: str
    selective_ocr_status: str
