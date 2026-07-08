"""FastAPI entrypoint for the standalone image moderation service."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.image_loader import ImageLoadError


# Resolve configuration once so health responses and route dependencies agree on policy version.
settings = get_settings()

app = FastAPI(
    title="Content Review Image Audit Service",
    version=settings.policy_version,
    description="Image moderation service with validation, visual risk checks, OCR, and text-audit callback.",
)

app.add_middleware(
    CORSMiddleware,
    # Local test pages may be opened through localhost or LAN IPs. Gateways should narrow this in
    # production deployments.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(ImageLoadError)
def image_load_error_handler(_, exc: ImageLoadError) -> JSONResponse:
    """Return image validation failures as structured API errors."""

    image_error = str(exc)
    message = _image_load_message(image_error)
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_image",
            "image_error": image_error.split(":", 1)[0],
            "message": message,
            "detail": message,
        },
    )


def _image_load_message(error: str) -> str:
    """Translate image loading errors into Chinese API messages."""

    code = str(error).split(":", 1)[0]
    messages = {
        "image_too_large": "图片文件过大",
        "image_empty": "图片文件为空",
        "unsupported_image_format": "不支持的图片格式",
        "invalid_image_dimensions": "图片尺寸无效",
        "image_pixels_too_large": "图片像素过大",
        "image_decode_failed": "图片解码失败",
        "missing_image_source": "缺少图片来源",
        "invalid_image_base64": "图片Base64内容无效",
    }
    return messages.get(code, "图片无法解析或不符合审核要求")
