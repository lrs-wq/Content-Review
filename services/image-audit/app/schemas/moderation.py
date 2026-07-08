"""Pydantic schemas for image moderation requests and responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, model_validator


RiskLevel = Literal["none", "low", "medium", "high"]
Action = Literal["allow", "review", "block", "mask"]

ACTION_LABELS = {
    "allow": "放行",
    "review": "人工复核",
    "block": "拦截",
    "mask": "打码",
}

RISK_LEVEL_LABELS = {
    "none": "无风险",
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
}

LABEL_NAMES = {
    "skin_exposure_heuristic": "疑似皮肤暴露",
    "ocr_sensitive": "OCR敏感文本",
    "political": "涉政风险",
    "nsfw": "疑似色情",
    "nudity": "疑似裸露",
    "qr_code": "二维码/引流风险",
    "image_quality": "图片质量异常",
    "vision_safety": "多模态安全风险",
    "vision_sexual": "多模态色情裸露风险",
    "vision_violence_gore": "多模态暴力血腥风险",
    "vision_dangerous": "多模态危险行为风险",
    "vision_safety_unavailable": "多模态二审不可用",
    "ocr_text_unchecked": "OCR文本未完成审核",
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
    "heuristic": "启发式",
    "falconsai": "NSFW模型",
    "nudenet": "裸露检测模型",
    "shieldgemma2": "多模态二审",
    "shieldgemma2_local": "多模态二审",
    "llama_guard4_openai": "多模态二审",
    "vision_safety": "多模态二审",
}

STATUS_LABELS = {
    "ok": "正常",
    "provided": "上游已提供",
    "skipped": "已跳过",
    "error": "异常",
    "disabled": "未启用",
    "unavailable": "不可用",
}

ERROR_MESSAGES = {
    "skipped_by_request": "请求指定跳过OCR",
    "ocr_engine_not_loaded": "OCR引擎未加载",
    "unsupported_ocr_provider": "不支持的OCR提供方",
}


def action_label(value: str) -> str:
    return ACTION_LABELS.get(str(value), str(value))


def risk_level_label(value: str) -> str:
    return RISK_LEVEL_LABELS.get(str(value), str(value))


def label_name(value: str) -> str:
    return LABEL_NAMES.get(str(value), str(value))


def source_name(value: str) -> str:
    return SOURCE_NAMES.get(str(value), str(value))


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
    for prefix, message in ERROR_MESSAGES.items():
        if text.startswith(prefix):
            return message
    return text


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
            raise ValueError("必须提供 image_base64、image_url 或上传图片文件")
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


class OcrPayload(BaseModel):
    """OCR result returned whether text was provided, recognized, skipped, or errored."""

    status: str
    text: str
    lines: list[str]
    provider: str
    elapsed_ms: float
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
    """Text-audit-service result for OCR or provided image text."""

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
    """Readiness response used by probes and the web test page."""

    status: str
    service: str
    policy_version: str
    visual_status: str
    vision_safety_status: str
    ocr_status: str
    text_audit_status: str

    @computed_field
    @property
    def status_label(self) -> str:
        return "正常" if self.status == "ok" else self.status
