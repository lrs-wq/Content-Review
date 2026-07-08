"""Compact response helpers for video moderation."""

from __future__ import annotations

from app.schemas.moderation import BriefModerationResponse, VideoModerationResponse


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


def to_brief_response(response: VideoModerationResponse) -> BriefModerationResponse:
    """Convert the full explainable response into the default business-facing shape."""

    return BriefModerationResponse(
        content_id=response.content_id,
        result=response.action,
        action=response.action,
        risk_level=response.risk_level,
        reason=_reason(response),
    )


def _reason(response: VideoModerationResponse) -> str:
    """Build a short reason from frame-level and aggregated text evidence."""

    parts: list[str] = []
    has_text_evidence = any(getattr(item, "type", "") == "text" for item in response.evidence)
    if response.evidence:
        parts.append(f"原因 {_evidence_reason(response.evidence)}")
    if response.text_review.used and response.text_review.action != "allow" and not has_text_evidence:
        labels = _label_list(response.text_review.labels[:5]) or response.text_review.risk_level
        parts.append(f"原因 聚合文本命中 {labels}({response.text_review.score:.2f})")
        text_snippet = _first_text_snippet(response.text_review.evidence, response.ocr_text, response.asr.text)
        if text_snippet:
            parts.append(text_snippet)
    risky_frames = [frame for frame in response.frame_results if frame.action != "allow"]
    if risky_frames and not response.evidence:
        parts.append(f"原因 风险帧 {_frame_reason(risky_frames)}")
    if response.asr.status.startswith("error"):
        error = f"：{response.asr.error}" if response.asr.error else ""
        parts.append(f"原因 ASR异常{error}")
    if response.labels:
        parts.append(f"标签 {_label_list(response.labels[:5])}")
    if parts:
        return "；".join(parts)
    return "视频帧、OCR和ASR聚合文本未发现明显风险"


def _evidence_reason(evidence) -> str:
    """Format the strongest video evidence with timestamps and text snippets."""

    items: list[str] = []
    for item in evidence[:3]:
        prefix = "聚合文本" if item.timestamp_seconds is None else f"{item.timestamp_seconds:.1f}s帧"
        text = f"{prefix}命中 {_label_list(str(item.label).split(','))}({item.score:.2f})"
        snippet = _snippet(item.text)
        if snippet:
            text = f"{text}：{snippet}"
        items.append(text)
    return "、".join(items)


def _frame_reason(frames) -> str:
    """Format risky frame fallback evidence when explicit evidence is unavailable."""

    items: list[str] = []
    for frame in frames[:3]:
        labels = _label_list(frame.labels[:3]) or frame.action
        score = float(frame.scores.get("overall", 0.0))
        text = f"{frame.timestamp_seconds:.1f}s帧 {labels}({score:.2f})"
        snippet = _evidence_list(frame.text_evidence) or _snippet(frame.ocr_text) or _frame_error_text(frame.error)
        if snippet:
            text = f"{text}：{snippet}"
        items.append(text)
    return "、".join(items)


def _label_list(labels) -> str:
    """Translate risk labels for business-facing brief reasons."""

    return ",".join(_label_name(label) for label in labels if label)


def _label_name(label: str) -> str:
    """Return a Chinese display name for a technical label."""

    return LABEL_NAMES.get(str(label), str(label))


def _first_text_snippet(evidence: list[str], ocr_text: str, asr_text: str) -> str:
    """Prefer OCR evidence, then ASR evidence, for the compact reason."""

    evidence_snippet = _evidence_list(evidence)
    if evidence_snippet:
        return f"命中内容 {evidence_snippet}"
    ocr_snippet = _snippet(ocr_text)
    if ocr_snippet:
        return f"OCR摘要 {ocr_snippet}"
    asr_snippet = _snippet(asr_text)
    if asr_snippet:
        return f"ASR摘要 {asr_snippet}"
    return ""


def _evidence_list(values: list[str]) -> str:
    """Format matched text evidence without exposing full OCR/ASR text."""

    cleaned = []
    for value in values:
        text = _snippet(value, limit=30)
        if text:
            cleaned.append(text)
    return "、".join(list(dict.fromkeys(cleaned))[:5])


def _snippet(value: str | None, limit: int = 60) -> str:
    """Return a compact one-line evidence snippet for business-facing reasons."""

    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _frame_error_text(error: str | None) -> str:
    """Translate frame audit transport failures into concise Chinese text."""

    text = str(error or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered or "readtimeout" in lowered:
        return "图片帧审核服务超时，未完成OCR/视觉审核"
    if "connection" in lowered or "connect" in lowered:
        return "图片帧审核服务连接失败，未完成OCR/视觉审核"
    return _snippet(text, limit=60)
