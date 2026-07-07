"""Configuration for the unified moderation gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables."""

    policy_version: str
    text_audit_url: str
    image_audit_json_url: str
    image_audit_upload_url: str
    video_audit_upload_url: str
    request_timeout_seconds: float
    health_timeout_seconds: float


def _env(name: str, default: str) -> str:
    """Return a stripped environment value or the provided default."""

    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load gateway settings once so health and route handlers agree."""

    return Settings(
        policy_version=_env("POLICY_VERSION", "2026.06.24"),
        text_audit_url=_env("GATEWAY_TEXT_AUDIT_URL", "http://127.0.0.1:8010/v1/moderation/text"),
        image_audit_json_url=_env("GATEWAY_IMAGE_AUDIT_JSON_URL", "http://127.0.0.1:8020/v1/moderation/image"),
        image_audit_upload_url=_env(
            "GATEWAY_IMAGE_AUDIT_UPLOAD_URL",
            "http://127.0.0.1:8020/v1/moderation/image/upload",
        ),
        video_audit_upload_url=_env(
            "GATEWAY_VIDEO_AUDIT_UPLOAD_URL",
            "http://127.0.0.1:8030/v1/moderation/video/upload",
        ),
        request_timeout_seconds=float(_env("GATEWAY_REQUEST_TIMEOUT_SECONDS", "300")),
        health_timeout_seconds=float(_env("GATEWAY_HEALTH_TIMEOUT_SECONDS", "2")),
    )
