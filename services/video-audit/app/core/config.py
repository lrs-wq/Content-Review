"""Configuration loader for video-audit-service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    """Resolve the repository root from this service module location."""

    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings for video-audit-service.

    Values come from configs/thresholds.yaml and can be overridden with environment variables.
    This mirrors the text/image services and keeps Docker/local startup scripts simple.
    """

    repo_root: Path
    config_dir: Path
    policy_version: str
    thresholds_path: Path
    max_video_bytes: int
    max_duration_seconds: float
    allowed_extensions: tuple[str, ...]
    frame_sample_fps: float
    max_sampled_frames: int
    scene_detect_enabled: bool
    scene_detect_threshold: float
    scene_detect_min_scene_len: int
    scene_detect_max_scene_frames: int
    scene_detect_dedupe_seconds: float
    frame_skip_ocr: bool
    stop_on_block: bool
    selective_ocr_enabled: bool
    selective_ocr_max_frames: int
    selective_ocr_include_first_frame: bool
    selective_ocr_include_last_frame: bool
    selective_ocr_min_interval_seconds: float
    selective_ocr_text_region_enabled: bool
    selective_ocr_text_region_score: float
    selective_ocr_retry_on_qr_or_risk: bool
    image_audit_url: str
    image_audit_timeout_seconds: float
    text_audit_url: str
    text_audit_timeout_seconds: float
    ffmpeg_path: str
    ffprobe_path: str
    asr_enabled: bool
    asr_provider: str
    asr_model_name: str
    asr_device: str
    asr_compute_type: str


def _env_bool(name: str, default: bool) -> bool:
    """Read common boolean environment variable spellings."""

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML object, returning an empty dict for missing or invalid top-level data."""

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    return data if isinstance(data, dict) else {}


def _string_tuple(raw: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize extension lists from YAML or comma-separated environment variables."""

    if isinstance(raw, list):
        values = [str(item).strip().lower().lstrip(".") for item in raw]
        return tuple(item for item in values if item)
    if isinstance(raw, str):
        values = [item.strip().lower().lstrip(".") for item in raw.split(",")]
        return tuple(item for item in values if item)
    return default


def get_settings() -> Settings:
    """Resolve configuration with environment overrides taking precedence over YAML."""

    root = Path(os.getenv("PROJECT_ROOT", _repo_root())).resolve()
    config_dir = Path(os.getenv("CONFIG_DIR", root / "configs")).resolve()
    thresholds_path = Path(os.getenv("THRESHOLDS_PATH", config_dir / "thresholds.yaml")).resolve()
    thresholds = load_yaml(thresholds_path)
    video_config = thresholds.get("video", {}) if isinstance(thresholds.get("video", {}), dict) else {}
    selective_ocr_config = (
        video_config.get("selective_ocr", {}) if isinstance(video_config.get("selective_ocr", {}), dict) else {}
    )
    scene_detect_config = (
        video_config.get("scene_detect", {}) if isinstance(video_config.get("scene_detect", {}), dict) else {}
    )
    asr_config = video_config.get("asr", {}) if isinstance(video_config.get("asr", {}), dict) else {}

    return Settings(
        repo_root=root,
        config_dir=config_dir,
        policy_version=os.getenv("POLICY_VERSION", str(thresholds.get("policy_version", "dev"))),
        thresholds_path=thresholds_path,
        max_video_bytes=int(os.getenv("VIDEO_AUDIT_MAX_VIDEO_BYTES", str(video_config.get("max_video_bytes", 100 * 1024 * 1024)))),
        max_duration_seconds=float(
            os.getenv("VIDEO_AUDIT_MAX_DURATION_SECONDS", str(video_config.get("max_duration_seconds", 60.0)))
        ),
        allowed_extensions=_string_tuple(
            os.getenv("VIDEO_AUDIT_ALLOWED_EXTENSIONS", video_config.get("allowed_extensions")),
            ("mp4", "mov", "webm", "mkv", "avi"),
        ),
        frame_sample_fps=float(os.getenv("VIDEO_AUDIT_FRAME_SAMPLE_FPS", str(video_config.get("frame_sample_fps", 1.0)))),
        max_sampled_frames=int(os.getenv("VIDEO_AUDIT_MAX_SAMPLED_FRAMES", str(video_config.get("max_sampled_frames", 60)))),
        scene_detect_enabled=_env_bool(
            "VIDEO_AUDIT_SCENE_DETECT_ENABLED",
            bool(scene_detect_config.get("enabled", True)),
        ),
        scene_detect_threshold=float(
            os.getenv(
                "VIDEO_AUDIT_SCENE_DETECT_THRESHOLD",
                str(scene_detect_config.get("threshold", 27.0)),
            )
        ),
        scene_detect_min_scene_len=int(
            os.getenv(
                "VIDEO_AUDIT_SCENE_DETECT_MIN_SCENE_LEN",
                str(scene_detect_config.get("min_scene_len", 15)),
            )
        ),
        scene_detect_max_scene_frames=int(
            os.getenv(
                "VIDEO_AUDIT_SCENE_DETECT_MAX_FRAMES",
                str(scene_detect_config.get("max_scene_frames", 8)),
            )
        ),
        scene_detect_dedupe_seconds=float(
            os.getenv(
                "VIDEO_AUDIT_SCENE_DETECT_DEDUPE_SECONDS",
                str(scene_detect_config.get("dedupe_seconds", 0.35)),
            )
        ),
        frame_skip_ocr=_env_bool("VIDEO_AUDIT_FRAME_SKIP_OCR", bool(video_config.get("frame_skip_ocr", True))),
        stop_on_block=_env_bool("VIDEO_AUDIT_STOP_ON_BLOCK", bool(video_config.get("stop_on_block", False))),
        selective_ocr_enabled=_env_bool(
            "VIDEO_AUDIT_SELECTIVE_OCR_ENABLED",
            bool(selective_ocr_config.get("enabled", True)),
        ),
        selective_ocr_max_frames=int(
            os.getenv(
                "VIDEO_AUDIT_SELECTIVE_OCR_MAX_FRAMES",
                str(selective_ocr_config.get("max_ocr_frames", 2)),
            )
        ),
        selective_ocr_include_first_frame=_env_bool(
            "VIDEO_AUDIT_SELECTIVE_OCR_INCLUDE_FIRST_FRAME",
            bool(selective_ocr_config.get("include_first_frame", True)),
        ),
        selective_ocr_include_last_frame=_env_bool(
            "VIDEO_AUDIT_SELECTIVE_OCR_INCLUDE_LAST_FRAME",
            bool(selective_ocr_config.get("include_last_frame", False)),
        ),
        selective_ocr_min_interval_seconds=float(
            os.getenv(
                "VIDEO_AUDIT_SELECTIVE_OCR_MIN_INTERVAL_SECONDS",
                str(selective_ocr_config.get("min_interval_seconds", 2.0)),
            )
        ),
        selective_ocr_text_region_enabled=_env_bool(
            "VIDEO_AUDIT_SELECTIVE_OCR_TEXT_REGION_ENABLED",
            bool(selective_ocr_config.get("text_region_enabled", True)),
        ),
        selective_ocr_text_region_score=float(
            os.getenv(
                "VIDEO_AUDIT_SELECTIVE_OCR_TEXT_REGION_SCORE",
                str(selective_ocr_config.get("text_region_score", 0.35)),
            )
        ),
        selective_ocr_retry_on_qr_or_risk=_env_bool(
            "VIDEO_AUDIT_SELECTIVE_OCR_RETRY_ON_QR_OR_RISK",
            bool(selective_ocr_config.get("retry_on_qr_or_risk", True)),
        ),
        image_audit_url=os.getenv(
            "IMAGE_AUDIT_URL",
            str(video_config.get("image_audit_url", "http://127.0.0.1:8020/v1/moderation/image/upload")),
        ),
        image_audit_timeout_seconds=float(
            os.getenv(
                "VIDEO_AUDIT_IMAGE_AUDIT_TIMEOUT_SECONDS",
                str(video_config.get("image_audit_timeout_seconds", 90.0)),
            )
        ),
        text_audit_url=os.getenv(
            "TEXT_AUDIT_URL",
            str(video_config.get("text_audit_url", "http://127.0.0.1:8010/v1/moderation/text")),
        ),
        text_audit_timeout_seconds=float(
            os.getenv(
                "VIDEO_AUDIT_TEXT_AUDIT_TIMEOUT_SECONDS",
                str(video_config.get("text_audit_timeout_seconds", 10.0)),
            )
        ),
        ffmpeg_path=os.getenv("VIDEO_AUDIT_FFMPEG_PATH", str(video_config.get("ffmpeg_path", "ffmpeg"))),
        ffprobe_path=os.getenv("VIDEO_AUDIT_FFPROBE_PATH", str(video_config.get("ffprobe_path", "ffprobe"))),
        asr_enabled=_env_bool("VIDEO_AUDIT_ENABLE_ASR", bool(asr_config.get("enabled", False))),
        asr_provider=os.getenv("VIDEO_AUDIT_ASR_PROVIDER", str(asr_config.get("provider", "faster_whisper"))),
        asr_model_name=os.getenv("VIDEO_AUDIT_ASR_MODEL_NAME", str(asr_config.get("model_name", "tiny"))),
        asr_device=os.getenv("VIDEO_AUDIT_ASR_DEVICE", str(asr_config.get("device", "cpu"))),
        asr_compute_type=os.getenv("VIDEO_AUDIT_ASR_COMPUTE_TYPE", str(asr_config.get("compute_type", "int8"))),
    )
