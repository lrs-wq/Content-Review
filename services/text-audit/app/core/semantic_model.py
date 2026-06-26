from __future__ import annotations

from dataclasses import dataclass


HEURISTIC_OFFENSIVE_TERMS = {
    "去死": 0.78,
    "废物": 0.72,
    "垃圾": 0.66,
    "滚": 0.62,
}


@dataclass(frozen=True)
class SemanticResult:
    label: str
    score: float
    provider: str
    enabled: bool
    error: str | None = None


class SemanticModel:
    def __init__(self, model_name: str, enabled: bool) -> None:
        self.model_name = model_name
        self.enabled = enabled
        self._pipeline = None
        self._load_error: str | None = None

        if self.enabled:
            self._load()

    @property
    def status(self) -> str:
        if self._pipeline is not None:
            return f"enabled:{self.model_name}"
        if self.enabled and self._load_error:
            return f"fallback:{self._load_error}"
        return "fallback:heuristic"

    def infer(self, text: str) -> SemanticResult:
        if self._pipeline is not None:
            try:
                output = self._pipeline(text[:512], truncation=True)
                item = output[0] if isinstance(output, list) else output
                label = str(item.get("label", "unknown"))
                raw_score = float(item.get("score", 0.0))
                score = self._map_score(label, raw_score)
                return SemanticResult(label=label, score=score, provider=self.model_name, enabled=True)
            except Exception as exc:  # pragma: no cover - defensive runtime fallback
                return self._heuristic(text, error=str(exc))

        return self._heuristic(text, error=self._load_error)

    def _load(self) -> None:
        try:
            from transformers import pipeline

            self._pipeline = pipeline(
                "text-classification",
                model=self.model_name,
                tokenizer=self.model_name,
            )
        except Exception as exc:  # pragma: no cover - depends on optional model deps
            self._load_error = str(exc)
            self._pipeline = None

    @staticmethod
    def _map_score(label: str, raw_score: float) -> float:
        label_lower = label.lower()
        offensive_labels = {"label_1", "offensive", "toxic", "unsafe"}
        safe_labels = {"label_0", "safe", "normal"}
        if label_lower in offensive_labels:
            return raw_score
        if label_lower in safe_labels:
            return 1.0 - raw_score
        return raw_score

    @staticmethod
    def _heuristic(text: str, error: str | None = None) -> SemanticResult:
        score = 0.0
        label = "safe"
        for term, term_score in HEURISTIC_OFFENSIVE_TERMS.items():
            if term in text:
                score = max(score, term_score)
                label = "offensive_heuristic"

        return SemanticResult(
            label=label,
            score=score,
            provider="heuristic",
            enabled=False,
            error=error,
        )

