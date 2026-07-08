"""Compact response helpers for image moderation."""

from __future__ import annotations

from app.schemas.moderation import BriefModerationResponse, ImageModerationResponse


LABEL_NAMES = {
    "skin_exposure_heuristic": "疑似皮肤暴露",
    "ocr_sensitive": "OCR敏感文本",
    "political": "涉政风险",
    "nsfw": "疑似色情",
    "nudity": "疑似裸露",
    "qr_code": "二维码/引流风险",
    "image_quality": "图片质量异常",
    "vision_safety": "多模态安全风险",
}

SOURCE_NAMES = {
    "heuristic": "启发式",
    "falconsai": "NSFW模型",
    "nudenet": "裸露检测模型",
    "shieldgemma2": "多模态二审",
    "vision_safety": "多模态二审",
}


def to_brief_response(response: ImageModerationResponse) -> BriefModerationResponse:
    """Convert the full explainable response into the default business-facing shape."""

    return BriefModerationResponse(
        content_id=response.content_id,
        result=response.action,
        action=response.action,
        risk_level=response.risk_level,
        reason=_reason(response),
    )


def _reason(response: ImageModerationResponse) -> str:
    """Build a short reason from visual, OCR, text, and multimodal safety evidence."""

    parts: list[str] = []
    if response.detections:
        parts.append(f"原因 视觉命中 {_visual_reason(response.detections)}")
    if response.text_review.used and response.text_review.action != "allow":
        labels = _label_list(response.text_review.labels[:5]) or response.text_review.risk_level
        parts.append(f"原因 OCR/关联文本命中 {labels}({response.text_review.score:.2f})")
        evidence = _evidence_list(response.text_review.evidence)
        if evidence:
            parts.append(f"命中内容 {evidence}")
        else:
            ocr_summary = _ocr_summary(response.ocr.lines, response.ocr.text)
            if ocr_summary:
                parts.append(f"OCR摘要 {ocr_summary}")
    if response.ocr.status == "error":
        error = f"：{response.ocr.error}" if response.ocr.error else ""
        parts.append(f"原因 OCR异常{error}")
    if response.labels:
        parts.append(f"标签 {_label_list(response.labels[:5])}")
    if parts:
        return "；".join(parts)
    return "视觉、OCR和文本审核未发现明显风险"


def _visual_reason(detections) -> str:
    """Format visual detections with label, score, source, and optional evidence."""

    items: list[str] = []
    for detection in detections[:3]:
        label = f"{_label_name(detection.label)}({detection.score:.2f})"
        if detection.source:
            label = f"{label}/{_source_name(detection.source)}"
        evidence = _evidence_text(detection.evidence)
        if evidence:
            label = f"{label}：{evidence}"
        items.append(label)
    return "、".join(items)


def _label_list(labels) -> str:
    """Translate risk labels for business-facing brief reasons."""

    return ",".join(_label_name(label) for label in labels if label)


def _label_name(label: str) -> str:
    """Return a Chinese display name for a technical label."""

    return LABEL_NAMES.get(str(label), str(label))


def _source_name(source: str) -> str:
    """Return a Chinese display name for a detection source."""

    return SOURCE_NAMES.get(str(source), str(source))


def _evidence_text(value: str | None) -> str:
    """Translate compact technical evidence into a clearer Chinese reason."""

    text = _snippet(value)
    prefix = "skin_like_pixel_ratio="
    if text.startswith(prefix):
        return f"疑似皮肤色区域占比 {text[len(prefix):]}"
    return text


def _evidence_list(values: list[str]) -> str:
    """Format text-review evidence without exposing noisy full OCR text."""

    cleaned = []
    for value in values:
        text = _snippet(value, limit=30)
        if text:
            cleaned.append(text)
    return "、".join(list(dict.fromkeys(cleaned))[:5])


def _ocr_summary(lines: list[str], text: str | None) -> str:
    """Return a fallback OCR summary after dropping common editor chrome noise."""

    raw_lines = lines or str(text or "").splitlines()
    cleaned = []
    for line in raw_lines:
        normalized = " ".join(str(line or "").split())
        if not normalized or _looks_like_ui_noise(normalized):
            continue
        cleaned.append(normalized)
    return _snippet(" ".join(cleaned), limit=40)


def _looks_like_ui_noise(text: str) -> bool:
    """Detect OCR fragments that are likely toolbar/ruler text from screenshots."""

    noise_tokens = ("未命名", "已编辑", "常规体", "苹方", "字号", "字体", "B|I|U", "1.0")
    digit_count = sum(char.isdigit() for char in text)
    return any(token in text for token in noise_tokens) and digit_count >= 3


def _snippet(value: str | None, limit: int = 60) -> str:
    """Return a compact one-line evidence snippet for business-facing reasons."""

    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
