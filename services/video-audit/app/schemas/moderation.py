"""Pydantic schemas for video moderation and dependency health responses."""

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
    "skin_exposure_heuristic": "疑似皮肤暴露",
    "video_frame_risk": "视频画面风险",
    "video_text_sensitive": "视频文本敏感",
    "video_asr_sensitive": "视频语音敏感",
    "ocr_sensitive": "OCR敏感文本",
    "political": "涉政风险",
    "nsfw": "疑似色情",
    "nudity": "疑似裸露",
    "qr_code": "二维码/引流风险",
    "vision_safety": "多模态安全风险",
    "vision_sexual": "多模态色情裸露风险",
    "vision_violence_gore": "多模态暴力血腥风险",
    "vision_dangerous": "多模态危险行为风险",
    "vision_safety_unavailable": "多模态二审不可用",
    "frame_audit_error": "帧审核调用异常",
    "ocr_text_unchecked": "OCR文本未完成审核",
    "video_text_unchecked": "视频聚合文本未完成审核",
    "adult": "成人低俗风险",
    "ad": "广告引流风险",
    "fraud": "诈骗风险",
    "gambling": "赌博风险",
    "violence": "暴力风险",
    "offensive": "攻击辱骂风险",
    "inappropriate_oral": "低俗口头语风险",
    "safe": "低风险",
    "normal": "低风险",
    "unknown": "未知风险",
}

SOURCE_NAMES = {
    "fixed": "固定间隔抽帧",
    "scene_detect": "场景变化抽帧",
    "image-audit-service": "图片审核服务",
    "heuristic": "启发式",
    "falconsai": "NSFW模型",
    "nudenet": "裸露检测模型",
    "shieldgemma2": "多模态二审",
    "shieldgemma2_local": "多模态二审",
    "llama_guard4_openai": "多模态二审",
    "vision_safety": "多模态二审",
}

OCR_REASON_NAMES = {
    "keyframe:first": "首帧抽检",
    "keyframe:last": "尾帧抽检",
    "qr_score": "二维码风险分触发OCR",
}

STATUS_LABELS = {
    "ok": "正常",
    "provided": "上游已提供",
    "disabled": "未启用",
    "none": "无",
}

ERROR_MESSAGES = {
    "The read operation timed out": "图片帧审核服务超时，未完成OCR/视觉审核",
}


def action_label(value: str) -> str:
    return ACTION_LABELS.get(str(value), str(value))


def risk_level_label(value: str) -> str:
    return RISK_LEVEL_LABELS.get(str(value), str(value))


def label_name(value: str) -> str:
    return LABEL_NAMES.get(str(value), str(value))


def source_name(value: str) -> str:
    return SOURCE_NAMES.get(str(value), str(value))


def ocr_reason_name(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.startswith("text_region:"):
        return f"检测到疑似文字区域({text.split(':', 1)[1]})"
    if text.startswith("risk_label:"):
        labels = text.split(":", 1)[1].split(",")
        return f"风险标签触发OCR：{','.join(label_name(label) for label in labels if label)}"
    if text.startswith("risk_action:"):
        action = text.split(":", 1)[1]
        return f"风险动作触发OCR：{action_label(action)}"
    return OCR_REASON_NAMES.get(text, text)


def status_label(value: str) -> str:
    text = str(value)
    if text.startswith("skipped"):
        return "已跳过"
    if text.startswith("error"):
        return "异常"
    return STATUS_LABELS.get(text, text)


def error_message(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered or "readtimeout" in lowered:
        return "图片帧审核服务超时，未完成OCR/视觉审核"
    if "connection" in lowered or "connect" in lowered:
        return "图片帧审核服务连接失败，未完成OCR/视觉审核"
    return ERROR_MESSAGES.get(text, text)


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

    @computed_field
    @property
    def label_zh(self) -> str:
        return label_name(self.label)

    @computed_field
    @property
    def source_label(self) -> str:
        return source_name(self.source)

    @computed_field
    @property
    def action_label(self) -> str:
        return action_label(self.action)

    @computed_field
    @property
    def risk_level_label(self) -> str:
        return risk_level_label(self.risk_level)


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

    @computed_field
    @property
    def source_label(self) -> str:
        return source_name(self.source)

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
    def ocr_reason_label(self) -> str | None:
        return ocr_reason_name(self.ocr_reason)

    @computed_field
    @property
    def error_message(self) -> str | None:
        return error_message(self.error)


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

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(self.status)

    @computed_field
    @property
    def error_message(self) -> str | None:
        return error_message(self.error)


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

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(self.status)

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
    def error_message(self) -> str | None:
        return error_message(self.error)


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

    @computed_field
    @property
    def type_label(self) -> str:
        return {"frame": "视频帧", "text": "聚合文本", "asr": "语音文本", "ocr": "OCR文本"}.get(
            str(self.type),
            str(self.type),
        )

    @computed_field
    @property
    def label_zh(self) -> str:
        return ",".join(label_name(label) for label in str(self.label).split(",") if label)

    @computed_field
    @property
    def source_label(self) -> str:
        return source_name(self.source)

    @computed_field
    @property
    def action_label(self) -> str:
        return action_label(self.action)

    @computed_field
    @property
    def risk_level_label(self) -> str:
        return risk_level_label(self.risk_level)


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

    @computed_field
    @property
    def status_label(self) -> str:
        return "正常" if self.status == "ok" else self.status
