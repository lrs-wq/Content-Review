"""Configuration loader for text-audit-service."""

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
    """Runtime settings after merging YAML defaults and environment overrides."""

    repo_root: Path
    config_dir: Path
    policy_version: str
    sensitive_terms_path: Path
    political_terms_path: Path
    fwwdn_terms_path: Path
    term_paths: tuple[Path, ...]
    allow_terms_path: Path
    thresholds_path: Path
    enable_model: bool
    model_name: str


def _env_bool(name: str, default: bool) -> bool:
    """Parse common truthy environment variable spellings."""

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML object from disk, returning an empty dict when unavailable."""

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        return {}
    return data


def get_settings() -> Settings:
    """Build a Settings object without mutating global process state."""

    root = Path(os.getenv("PROJECT_ROOT", _repo_root())).resolve()
    config_dir = Path(os.getenv("CONFIG_DIR", root / "configs")).resolve()
    thresholds_path = Path(os.getenv("THRESHOLDS_PATH", config_dir / "thresholds.yaml")).resolve()
    thresholds = load_yaml(thresholds_path)
    text_config = thresholds.get("text", {}) if isinstance(thresholds.get("text", {}), dict) else {}
    semantic_config = text_config.get("semantic", {}) if isinstance(text_config.get("semantic", {}), dict) else {}

    sensitive_terms_path = Path(
        os.getenv("SENSITIVE_TERMS_PATH", config_dir / "sensitive_terms.csv")
    ).resolve()
    political_terms_path = Path(
        os.getenv("POLITICAL_TERMS_PATH", config_dir / "political_terms.csv")
    ).resolve()
    fwwdn_terms_path = Path(
        os.getenv("FWWDN_TERMS_PATH", config_dir / "fwwdn_terms.csv")
    ).resolve()
    # Extra term files allow emergency/business-specific dictionaries without editing the base
    # repository CSVs.
    extra_term_paths = tuple(
        Path(item.strip()).resolve()
        for item in os.getenv("EXTRA_TERMS_PATHS", "").split(";")
        if item.strip()
    )

    return Settings(
        repo_root=root,
        config_dir=config_dir,
        policy_version=os.getenv("POLICY_VERSION", str(thresholds.get("policy_version", "dev"))),
        sensitive_terms_path=sensitive_terms_path,
        political_terms_path=political_terms_path,
        fwwdn_terms_path=fwwdn_terms_path,
        term_paths=(sensitive_terms_path, political_terms_path, fwwdn_terms_path, *extra_term_paths),
        allow_terms_path=Path(os.getenv("ALLOW_TERMS_PATH", config_dir / "allow_terms.csv")).resolve(),
        thresholds_path=thresholds_path,
        enable_model=_env_bool(
            "TEXT_AUDIT_ENABLE_MODEL",
            bool(semantic_config.get("enabled", False)),
        ),
        model_name=os.getenv(
            "TEXT_AUDIT_MODEL_NAME",
            str(semantic_config.get("model_name", "thu-coai/roberta-base-cold")),
        ),
    )
