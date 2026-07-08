"""FastAPI entrypoint for the unified content moderation gateway."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import GatewayError
from app.core.response_format import error_message


settings = get_settings()

app = FastAPI(
    title="Content Review Unified Gateway",
    version=settings.policy_version,
    description="Unified API gateway for text, image, and video moderation services.",
)

app.add_middleware(
    CORSMiddleware,
    # Local testers may open pages from localhost, LAN IPs, or file://. Production deployments
    # should restrict origins at this gateway or the upstream reverse proxy.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(GatewayError)
def gateway_error_handler(_, exc: GatewayError) -> JSONResponse:
    """Expose gateway validation/forwarding errors as stable JSON responses."""

    message = error_message(exc.error, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error,
            "message": message,
            "detail": message,
        },
    )
