from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    config_dir: Path
    policy_version: str
    thresholds_path: Path
    text_audit_url: str
    text_audit_timeout_seconds: float
    max_image_bytes: int
    max_image_pixels: int
    enable_ocr: bool
    ocr_provider: str
    enable_nsfw_model: bool
    nsfw_model_name: str
    nsfw_model_device: int
    nsfw_download_on_request: bool
    enable_nudenet: bool
    enable_vision_safety: bool
    vision_safety_provider: str
    vision_safety_model_name: str
    vision_safety_endpoint_url: str
    vision_safety_api_key_env: str
    vision_safety_timeout_seconds: float
    vision_safety_device: str
    vision_safety_download_on_request: bool
    vision_safety_allow_cpu: bool
    vision_safety_trigger_mode: str
    vision_safety_gray_min_score: float
    vision_safety_gray_max_score: float
    vision_safety_review_score: float
    vision_safety_block_score: float
    vision_safety_max_new_tokens: int
    vision_safety_review_on_unavailable: bool


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    return data if isinstance(data, dict) else {}


def _resolve_model_name(root: Path, raw_model_name: str) -> str:
    model_path = Path(raw_model_name)
    if model_path.is_absolute():
        return str(model_path)
    local_model_path = (root / model_path).resolve()
    if local_model_path.exists():
        return str(local_model_path)
    return raw_model_name


def get_settings() -> Settings:
    root = Path(os.getenv("PROJECT_ROOT", _repo_root())).resolve()
    config_dir = Path(os.getenv("CONFIG_DIR", root / "configs")).resolve()
    thresholds_path = Path(os.getenv("THRESHOLDS_PATH", config_dir / "thresholds.yaml")).resolve()
    thresholds = load_yaml(thresholds_path)
    image_config = thresholds.get("image", {}) if isinstance(thresholds.get("image", {}), dict) else {}
    ocr_config = image_config.get("ocr", {}) if isinstance(image_config.get("ocr", {}), dict) else {}
    model_config = image_config.get("nsfw_model", {}) if isinstance(image_config.get("nsfw_model", {}), dict) else {}
    nudenet_config = image_config.get("nudenet", {}) if isinstance(image_config.get("nudenet", {}), dict) else {}
    vision_safety_config = (
        image_config.get("vision_safety", {}) if isinstance(image_config.get("vision_safety", {}), dict) else {}
    )

    return Settings(
        repo_root=root,
        config_dir=config_dir,
        policy_version=os.getenv("POLICY_VERSION", str(thresholds.get("policy_version", "dev"))),
        thresholds_path=thresholds_path,
        text_audit_url=os.getenv(
            "TEXT_AUDIT_URL",
            str(image_config.get("text_audit_url", "http://127.0.0.1:8010/v1/moderation/text")),
        ),
        text_audit_timeout_seconds=float(image_config.get("text_audit_timeout_seconds", 5.0)),
        max_image_bytes=int(image_config.get("max_image_bytes", 10 * 1024 * 1024)),
        max_image_pixels=int(image_config.get("max_image_pixels", 25_000_000)),
        enable_ocr=_env_bool("IMAGE_AUDIT_ENABLE_OCR", bool(ocr_config.get("enabled", True))),
        ocr_provider=os.getenv("IMAGE_AUDIT_OCR_PROVIDER", str(ocr_config.get("provider", "paddleocr"))),
        enable_nsfw_model=_env_bool(
            "IMAGE_AUDIT_ENABLE_NSFW_MODEL",
            bool(model_config.get("enabled", False)),
        ),
        nsfw_model_name=_resolve_model_name(
            root,
            os.getenv(
                "IMAGE_AUDIT_NSFW_MODEL_NAME",
                str(model_config.get("model_name", "Falconsai/nsfw_image_detection")),
            ),
        ),
        nsfw_model_device=int(os.getenv("IMAGE_AUDIT_NSFW_DEVICE", str(model_config.get("device", -1)))),
        nsfw_download_on_request=_env_bool(
            "IMAGE_AUDIT_NSFW_DOWNLOAD_ON_REQUEST",
            bool(model_config.get("download_on_request", False)),
        ),
        enable_nudenet=_env_bool(
            "IMAGE_AUDIT_ENABLE_NUDENET",
            bool(nudenet_config.get("enabled", False)),
        ),
        enable_vision_safety=_env_bool(
            "IMAGE_AUDIT_ENABLE_VISION_SAFETY",
            bool(vision_safety_config.get("enabled", False)),
        ),
        vision_safety_provider=os.getenv(
            "IMAGE_AUDIT_VISION_SAFETY_PROVIDER",
            str(vision_safety_config.get("provider", "shieldgemma2_local")),
        ),
        vision_safety_model_name=_resolve_model_name(
            root,
            os.getenv(
                "IMAGE_AUDIT_VISION_SAFETY_MODEL_NAME",
                str(vision_safety_config.get("model_name", "storage/models/shieldgemma-2-4b-it")),
            ),
        ),
        vision_safety_endpoint_url=os.getenv(
            "IMAGE_AUDIT_VISION_SAFETY_ENDPOINT_URL",
            str(vision_safety_config.get("endpoint_url", "")),
        ),
        vision_safety_api_key_env=os.getenv(
            "IMAGE_AUDIT_VISION_SAFETY_API_KEY_ENV",
            str(vision_safety_config.get("api_key_env", "VISION_SAFETY_API_KEY")),
        ),
        vision_safety_timeout_seconds=float(
            os.getenv(
                "IMAGE_AUDIT_VISION_SAFETY_TIMEOUT_SECONDS",
                str(vision_safety_config.get("timeout_seconds", 30.0)),
            )
        ),
        vision_safety_device=os.getenv(
            "IMAGE_AUDIT_VISION_SAFETY_DEVICE",
            str(vision_safety_config.get("device", "cpu")),
        ),
        vision_safety_download_on_request=_env_bool(
            "IMAGE_AUDIT_VISION_SAFETY_DOWNLOAD_ON_REQUEST",
            bool(vision_safety_config.get("download_on_request", False)),
        ),
        vision_safety_allow_cpu=_env_bool(
            "IMAGE_AUDIT_VISION_SAFETY_ALLOW_CPU",
            bool(vision_safety_config.get("allow_cpu", False)),
        ),
        vision_safety_trigger_mode=os.getenv(
            "IMAGE_AUDIT_VISION_SAFETY_TRIGGER_MODE",
            str(vision_safety_config.get("trigger_mode", "gray")),
        ),
        vision_safety_gray_min_score=float(
            os.getenv(
                "IMAGE_AUDIT_VISION_SAFETY_GRAY_MIN_SCORE",
                str(vision_safety_config.get("gray_min_score", 0.30)),
            )
        ),
        vision_safety_gray_max_score=float(
            os.getenv(
                "IMAGE_AUDIT_VISION_SAFETY_GRAY_MAX_SCORE",
                str(vision_safety_config.get("gray_max_score", 0.90)),
            )
        ),
        vision_safety_review_score=float(
            os.getenv(
                "IMAGE_AUDIT_VISION_SAFETY_REVIEW_SCORE",
                str(vision_safety_config.get("review_score", 0.55)),
            )
        ),
        vision_safety_block_score=float(
            os.getenv(
                "IMAGE_AUDIT_VISION_SAFETY_BLOCK_SCORE",
                str(vision_safety_config.get("block_score", 0.85)),
            )
        ),
        vision_safety_max_new_tokens=int(
            os.getenv(
                "IMAGE_AUDIT_VISION_SAFETY_MAX_NEW_TOKENS",
                str(vision_safety_config.get("max_new_tokens", 256)),
            )
        ),
        vision_safety_review_on_unavailable=_env_bool(
            "IMAGE_AUDIT_VISION_SAFETY_REVIEW_ON_UNAVAILABLE",
            bool(vision_safety_config.get("review_on_unavailable", True)),
        ),
    )
