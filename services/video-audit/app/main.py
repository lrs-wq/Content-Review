"""FastAPI entrypoint for the standalone video moderation service."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import VideoAuditError


# Resolve settings once at startup; model/provider objects are cached deeper in the auditor.
settings = get_settings()

# FastAPI is intentionally kept small here; the heavy pipeline lives under app.core so it is easy
# to test without running an HTTP server.
app = FastAPI(
    title="Content Review Video Audit Service",
    version=settings.policy_version,
    description="Video moderation service with 60s validation, frame sampling, image audit, and text aggregation.",
)

app.add_middleware(
    CORSMiddleware,
    # The manual web tester may run from localhost or a LAN IP, so development CORS is open.
    # Production deployments should restrict this at the gateway/reverse-proxy layer.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(VideoAuditError)
def video_audit_error_handler(_, exc: VideoAuditError) -> JSONResponse:
    """Expose domain errors as structured JSON instead of generic 500 responses."""

    message = _video_error_message(exc.error)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error,
            "message": message,
            "detail": message,
        },
    )


def _video_error_message(error: str) -> str:
    """Translate video audit domain errors into Chinese API messages."""

    messages = {
        "unsupported_video_type": "不支持的视频格式",
        "empty_video": "视频文件为空",
        "video_file_too_large": "视频文件过大",
        "missing_video_source": "缺少视频文件或视频链接",
        "invalid_video_url": "视频链接格式无效",
        "video_download_failed": "视频链接下载失败",
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
    return messages.get(str(error), "视频审核失败")
