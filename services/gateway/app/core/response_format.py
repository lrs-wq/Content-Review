"""Chinese display helpers for gateway responses."""

from __future__ import annotations


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

STATUS_LABELS = {
    "queued": "已排队",
    "processing": "处理中",
    "completed": "已完成",
    "failed": "处理失败",
    "not_found": "未找到",
    "ok": "正常",
}

CONTENT_TYPE_LABELS = {
    "text": "文本",
    "image": "图片",
    "video": "视频",
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
    "ocr_sensitive": "OCR敏感文本",
    "video_text_sensitive": "视频文本敏感",
    "video_asr_sensitive": "视频语音敏感",
    "video_frame_risk": "视频画面风险",
    "skin_exposure_heuristic": "疑似皮肤暴露",
    "vision_safety": "多模态安全风险",
    "vision_sexual": "多模态色情裸露风险",
    "vision_violence_gore": "多模态暴力血腥风险",
    "vision_dangerous": "多模态危险行为风险",
    "vision_safety_unavailable": "多模态二审不可用",
    "frame_audit_error": "帧审核调用异常",
    "ocr_text_unchecked": "OCR文本未完成审核",
    "video_text_unchecked": "视频聚合文本未完成审核",
    "nsfw": "疑似色情",
    "nudity": "疑似裸露",
    "qr_code": "二维码/引流风险",
    "safe": "低风险",
    "normal": "低风险",
    "unknown": "未知风险",
}

ERROR_MESSAGES = {
    "unsupported_content_type": "不支持的内容类型",
    "unknown_file_type": "无法识别上传文件类型，请上传图片或视频",
    "missing_content_type": "缺少内容类型，且无法从请求内容自动识别",
    "missing_required_field": "缺少必填字段",
    "invalid_context": "上下文必须是 JSON 对象",
    "invalid_json_body": "JSON 请求体必须是对象",
    "unsupported_media_type": "请求格式不支持，请使用 JSON 或 multipart/form-data",
    "missing_video_file": "视频审核需要上传视频文件",
    "async_job_failed": "异步审核任务执行失败",
    "downstream_unavailable": "下游审核服务不可用",
    "downstream_invalid_json": "下游审核服务返回了非 JSON 内容",
    "invalid_image": "图片无法解析或不符合审核要求",
    "unsupported_video_type": "不支持的视频格式",
    "empty_video": "视频文件为空",
    "video_file_too_large": "视频文件过大",
    "missing_video_stream": "未检测到视频画面流",
    "invalid_video_duration": "视频时长无效",
    "video_too_long": "视频超过60秒限制",
    "ffprobe_not_found": "未找到 ffprobe",
    "ffprobe_failed": "视频元数据解析失败",
    "ffprobe_invalid_json": "视频元数据解析结果异常",
    "ffmpeg_not_found": "未找到 ffmpeg",
    "frame_sampling_failed": "视频抽帧失败",
    "no_sampled_frames": "未抽取到可审核视频帧",
}


def action_label(value: str) -> str:
    """Return Chinese display text for an action/result enum."""

    return ACTION_LABELS.get(str(value), str(value))


def risk_level_label(value: str) -> str:
    """Return Chinese display text for a risk-level enum."""

    return RISK_LEVEL_LABELS.get(str(value), str(value))


def status_label(value: str) -> str:
    """Return Chinese display text for an async job status."""

    return STATUS_LABELS.get(str(value), str(value))


def content_type_label(value: str) -> str:
    """Return Chinese display text for a moderation content type."""

    return CONTENT_TYPE_LABELS.get(str(value), str(value))


def label_name(value: str) -> str:
    """Return Chinese display text for a technical risk label."""

    return LABEL_NAMES.get(str(value), str(value))


def labels_zh(labels: list[str]) -> list[str]:
    """Translate a list of technical labels while preserving order."""

    return [label_name(label) for label in labels]


def standard_decision_fields(action: str, risk_level: str) -> dict[str, str]:
    """Return common Chinese display fields for a moderation decision."""

    return {
        "result_label": action_label(action),
        "action_label": action_label(action),
        "risk_level_label": risk_level_label(risk_level),
    }


def error_message(error: str, detail: str = "") -> str:
    """Return a Chinese user-facing error message while keeping detail separately available."""

    base = ERROR_MESSAGES.get(str(error), "请求处理失败")
    if error == "missing_required_field" and detail:
        field = str(detail).split()[0]
        return f"{base}：{field}"
    return base
