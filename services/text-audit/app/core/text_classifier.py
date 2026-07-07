"""Small local text classifier used between rules and the gray-zone agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import joblib

from app.core.config import load_yaml


@dataclass(frozen=True)
class ClassifierResult:
    """Normalized result from the local text classifier artifact."""

    enabled: bool
    label: str
    score: float
    action: str
    risk_level: str
    model_version: str
    error: str | None = None


class TextClassifier:
    """Loads a joblib scikit-learn artifact and maps labels to moderation actions."""

    def __init__(self, thresholds_path: Path, repo_root: Path) -> None:
        thresholds = load_yaml(thresholds_path)
        text_thresholds = thresholds.get("text", {}) if isinstance(thresholds.get("text", {}), dict) else {}
        config = text_thresholds.get("classifier", {}) if isinstance(text_thresholds.get("classifier", {}), dict) else {}

        self.enabled = bool(config.get("enabled", True))
        self.review_score = float(config.get("review_score", 0.55))
        self.block_score = float(config.get("block_score", 0.93))
        self.label_review_scores = dict(config.get("label_review_scores", {}))
        self.block_labels = set(config.get("block_labels", ["adult", "weapon"]))
        self.label_actions = dict(config.get("label_actions", {}))
        self.model_path = self._resolve_model_path(str(config.get("model_path", "")), repo_root)
        self._model = None
        self._metadata: dict = {}
        self._load_error: str | None = None

        if self.enabled:
            self._load()

    @property
    def status(self) -> str:
        if self._model is not None:
            version = self._metadata.get("version", "unknown")
            return f"enabled:{version}"
        if self.enabled:
            return f"disabled:{self._load_error or 'model_not_loaded'}"
        return "disabled:config"

    def classify(self, text: str) -> ClassifierResult:
        """Classify normalized text and convert the best label into an action."""

        if self._model is None:
            return ClassifierResult(
                enabled=False,
                label="safe",
                score=0.0,
                action="allow",
                risk_level="none",
                model_version="none",
                error=self._load_error,
            )

        try:
            prepared_text = self._prepare_text(text)
            probabilities = self._model.predict_proba([prepared_text])[0]
            classes = list(self._model.classes_)
            best_index = max(range(len(probabilities)), key=lambda index: probabilities[index])
            label = str(classes[best_index])
            score = float(probabilities[best_index])
            action, risk_level = self._decision(label, score)
            return ClassifierResult(
                enabled=True,
                label=label,
                score=round(score, 4),
                action=action,
                risk_level=risk_level,
                model_version=str(self._metadata.get("version", "unknown")),
            )
        except Exception as exc:  # pragma: no cover - defensive runtime fallback
            return ClassifierResult(
                enabled=False,
                label="safe",
                score=0.0,
                action="allow",
                risk_level="none",
                model_version=str(self._metadata.get("version", "unknown")),
                error=str(exc),
            )

    def _decision(self, label: str, score: float) -> tuple[str, str]:
        """Apply per-label thresholds after the classifier chooses its top class."""

        if label == "safe":
            return "allow", "none"
        review_score = float(self.label_review_scores.get(label, self.review_score))
        if label in self.block_labels and score >= self.block_score:
            return "block", "high"
        if score >= review_score:
            return self.label_actions.get(label, "review"), "medium"
        return "allow", "low"

    @staticmethod
    def _prepare_text(text: str) -> str:
        """Remove context labels like [text] so the char model sees mostly user content."""

        return re.sub(r"\[[a-zA-Z_]+\]\s*", " ", text).strip()

    def _load(self) -> None:
        """Load the classifier artifact, recording status instead of failing startup."""

        if not self.model_path.exists():
            self._load_error = f"model_missing:{self.model_path}"
            return
        try:
            artifact = joblib.load(self.model_path)
            self._model = artifact["model"]
            self._metadata = artifact.get("metadata", {})
        except Exception as exc:  # pragma: no cover - depends on artifact state
            self._model = None
            self._metadata = {}
            self._load_error = str(exc)

    @staticmethod
    def _resolve_model_path(raw_path: str, repo_root: Path) -> Path:
        """Resolve model paths relative to the repository root when needed."""

        if not raw_path:
            return repo_root / "storage" / "models" / "text-classifier" / "text_classifier.joblib"
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return (repo_root / path).resolve()
