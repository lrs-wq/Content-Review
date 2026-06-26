from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.image_loader import ImageLoadError


settings = get_settings()

app = FastAPI(
    title="Content Review Image Audit Service",
    version=settings.policy_version,
    description="Image moderation service with validation, visual risk checks, OCR, and text-audit callback.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(ImageLoadError)
def image_load_error_handler(_, exc: ImageLoadError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "detail": str(exc),
            "error": "invalid_image",
        },
    )
