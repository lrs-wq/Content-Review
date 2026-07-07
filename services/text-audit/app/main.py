"""FastAPI entrypoint for the standalone text moderation service."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings


# Resolve settings once at startup so service metadata and routes share one policy version.
settings = get_settings()

app = FastAPI(
    title="Content Review Text Audit Service",
    version=settings.policy_version,
    description="Rule based and optional model based text moderation service.",
)

app.add_middleware(
    CORSMiddleware,
    # The local test page can be opened from localhost or a LAN address, so development CORS is
    # intentionally permissive. Production gateways should restrict origins.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
