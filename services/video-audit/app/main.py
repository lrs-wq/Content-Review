from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import VideoAuditError


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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(VideoAuditError)
def video_audit_error_handler(_, exc: VideoAuditError) -> JSONResponse:
    """Expose domain errors as structured JSON instead of generic 500 responses."""

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error": exc.error,
        },
    )
