"""Smoke checks for compact image/video moderation reasons."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _clear_service_modules() -> None:
    """Unload service-local ``app`` modules so image and video imports do not collide."""

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def _with_service(service_name: str) -> None:
    """Put one service package at the front of sys.path."""

    service_root = str(ROOT / "services" / service_name)
    sys.path = [item for item in sys.path if not item.endswith("services\\" + service_name)]
    sys.path.insert(0, service_root)


def check_image_reason() -> None:
    """Verify image brief reasons include the failing visual/OCR evidence."""

    _clear_service_modules()
    _with_service("image-audit")

    from app.core.brief import to_brief_response
    from app.schemas.moderation import (
        DetectionPayload,
        ImageMetadata,
        ImageModerationResponse,
        OcrPayload,
        TextReviewPayload,
    )

    response = ImageModerationResponse(
        trace_id="img_test",
        content_id="img_reason_case",
        risk_level="high",
        action="block",
        labels=["ocr_sensitive", "political"],
        scores={"overall": 0.95, "ocr_text": 0.95},
        image=ImageMetadata(
            width=600,
            height=400,
            format="PNG",
            mode="RGB",
            mime_type="image/png",
            bytes=1000,
            sha256="x" * 64,
        ),
        ocr=OcrPayload(
            status="ok",
            text="毛泽东习近平",
            lines=["毛泽东习近平"],
            provider="paddleocr",
            elapsed_ms=120.0,
        ),
        text_review=TextReviewPayload(
            used=True,
            status="ok",
            action="block",
            risk_level="high",
            labels=["political"],
            score=0.95,
            evidence=["毛泽东", "习近平"],
        ),
        detections=[
            DetectionPayload(
                label="vision_safety",
                score=0.86,
                source="shieldgemma2",
                action="review",
                risk_level="medium",
                evidence="sensitive political text in screenshot",
            )
        ],
        policy_version="test",
        model_status={},
        elapsed_ms=200.0,
    )

    reason = to_brief_response(response).reason
    print(reason)
    for expected in ("原因 视觉命中", "原因 OCR/关联文本命中 涉政风险(0.95)", "命中内容 毛泽东、习近平"):
        if expected not in reason:
            raise SystemExit(f"image reason missing {expected}: {reason}")

    skin_response = response.model_copy(
        update={
            "content_id": "img_skin_reason_case",
            "risk_level": "medium",
            "action": "review",
            "labels": ["skin_exposure_heuristic"],
            "scores": {"overall": 0.83, "skin_exposure": 0.83},
            "ocr": OcrPayload(status="skipped", text="", lines=[], provider="skip_ocr", elapsed_ms=0.0),
            "text_review": TextReviewPayload(used=False, status="skipped:empty_ocr_text"),
            "detections": [
                DetectionPayload(
                    label="skin_exposure_heuristic",
                    score=0.83,
                    source="heuristic",
                    action="review",
                    risk_level="medium",
                    evidence="skin_like_pixel_ratio=0.510",
                )
            ],
        }
    )
    skin_reason = to_brief_response(skin_response).reason
    print(skin_reason)
    for expected in ("原因 视觉命中 疑似皮肤暴露(0.83)/启发式", "疑似皮肤色区域占比 0.510", "标签 疑似皮肤暴露"):
        if expected not in skin_reason:
            raise SystemExit(f"image skin reason missing {expected}: {skin_reason}")


def check_video_reason() -> None:
    """Verify video brief reasons include frame time and text evidence."""

    _clear_service_modules()
    _with_service("video-audit")

    from app.core.brief import to_brief_response
    from app.schemas.moderation import (
        AsrPayload,
        EvidencePayload,
        FrameAuditPayload,
        TextReviewPayload,
        VideoMetadata,
        VideoModerationResponse,
    )

    response = VideoModerationResponse(
        trace_id="vid_test",
        content_id="video_reason_case",
        risk_level="high",
        action="block",
        labels=["video_text_sensitive", "political"],
        scores={"overall": 0.95, "video_text": 0.95},
        video=VideoMetadata(
            filename="sample.mp4",
            mime_type="video/mp4",
            bytes=1000,
            sha256="x" * 64,
            duration_seconds=10.0,
            width=640,
            height=360,
            format_name="mov,mp4",
            video_codec="h264",
            audio_codec="aac",
        ),
        sampled_frames=2,
        audited_frames=2,
        frame_results=[],
        ocr_text="毛泽东习近平",
        asr=AsrPayload(used=True, status="ok", provider="faster_whisper", text="测试音频文本"),
        text_review=TextReviewPayload(
            used=True,
            status="ok",
            action="block",
            risk_level="high",
            labels=["political"],
            score=0.95,
            evidence=["毛泽东", "习近平"],
        ),
        evidence=[
            EvidencePayload(
                type="frame",
                label="ocr_sensitive,political",
                action="block",
                risk_level="high",
                score=0.95,
                source="image-audit-service",
                timestamp_seconds=3.5,
                text="毛泽东习近平",
            )
        ],
        policy_version="test",
        model_status={},
        elapsed_ms=300.0,
    )

    reason = to_brief_response(response).reason
    print(reason)
    for expected in ("3.5s帧命中", "原因 聚合文本命中 涉政风险(0.95)", "毛泽东习近平"):
        if expected not in reason:
            raise SystemExit(f"video reason missing {expected}: {reason}")

    skin_video_response = response.model_copy(
        update={
            "content_id": "video_skin_reason_case",
            "risk_level": "medium",
            "action": "review",
            "labels": ["skin_exposure_heuristic", "video_frame_risk"],
            "scores": {"overall": 0.83, "frame": 0.83},
            "ocr_text": "",
            "asr": AsrPayload(used=False, status="skipped:no_audio", provider="none", text=""),
            "text_review": TextReviewPayload(used=False, status="skipped:empty_text"),
            "evidence": [
                EvidencePayload(
                    type="frame",
                    label="skin_exposure_heuristic",
                    action="review",
                    risk_level="medium",
                    score=0.83,
                    source="image-audit-service",
                    timestamp_seconds=1.0,
                )
            ],
        }
    )
    skin_video_reason = to_brief_response(skin_video_response).reason
    print(skin_video_reason)
    for expected in ("1.0s帧命中 疑似皮肤暴露(0.83)", "标签 疑似皮肤暴露,视频画面风险"):
        if expected not in skin_video_reason:
            raise SystemExit(f"video skin reason missing {expected}: {skin_video_reason}")

    error_video_response = response.model_copy(
        update={
            "content_id": "video_frame_error_reason_case",
            "risk_level": "medium",
            "action": "review",
            "labels": ["frame_audit_error", "video_frame_risk"],
            "scores": {"overall": 0.65, "frame": 0.65},
            "ocr_text": "",
            "asr": AsrPayload(used=False, status="skipped:no_audio", provider="none", text=""),
            "text_review": TextReviewPayload(used=False, status="skipped:empty_text"),
            "frame_results": [
                FrameAuditPayload(
                    index=1,
                    timestamp_seconds=0.0,
                    action="review",
                    risk_level="medium",
                    labels=["frame_audit_error"],
                    scores={"overall": 0.65},
                    error="The read operation timed out",
                )
            ],
            "evidence": [],
        }
    )
    error_reason = to_brief_response(error_video_response).reason
    print(error_reason)
    for expected in ("0.0s帧 帧审核调用异常(0.65)", "图片帧审核服务超时"):
        if expected not in error_reason:
            raise SystemExit(f"video frame error reason missing {expected}: {error_reason}")


def main() -> None:
    """Run compact-reason checks for image and video services."""

    check_image_reason()
    check_video_reason()


if __name__ == "__main__":
    main()
