from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.config import load_yaml
from app.core.rule_engine import RuleHit
from app.core.semantic_model import SemanticResult


class AgentDecision(Protocol):
    used: bool
    risk_level: str
    action: str
    labels: list[str]
    score: float


class ClassifierDecision(Protocol):
    enabled: bool
    label: str
    score: float
    action: str
    risk_level: str


@dataclass(frozen=True)
class Decision:
    risk_level: str
    action: str
    labels: list[str]
    scores: dict[str, float]


class DecisionMaker:
    def __init__(self, thresholds_path: Path) -> None:
        thresholds = load_yaml(thresholds_path)
        text_thresholds = thresholds.get("text", {}) if isinstance(thresholds.get("text", {}), dict) else {}
        self.block_score = float(text_thresholds.get("block_score", 0.92))
        self.review_score = float(text_thresholds.get("review_score", 0.65))

    def decide(
        self,
        hits: list[RuleHit],
        semantic: SemanticResult,
        classifier: ClassifierDecision | None = None,
    ) -> Decision:
        max_rule_score = max((hit.score for hit in hits), default=0.0)
        classifier_score = self._classifier_risk_score(classifier)
        max_score = max(max_rule_score, semantic.score, classifier_score)

        labels = self._labels(hits, semantic, classifier)
        scores = {
            "rule": round(max_rule_score, 4),
            "offensive": round(semantic.score, 4),
            "classifier": round(classifier_score, 4),
            "overall": round(max_score, 4),
        }

        if self._should_block(hits, semantic, classifier, max_score):
            return Decision(risk_level="high", action="block", labels=labels, scores=scores)

        if self._should_review(hits, semantic, classifier, max_score):
            if any(hit.risk_level == "high" for hit in hits):
                return Decision(risk_level="high", action="review", labels=labels, scores=scores)
            if classifier is not None and classifier.action == "review":
                return Decision(risk_level=classifier.risk_level, action="review", labels=labels, scores=scores)
            return Decision(risk_level="medium", action="review", labels=labels, scores=scores)

        if max_score > 0:
            return Decision(risk_level="low", action="allow", labels=labels, scores=scores)

        return Decision(risk_level="none", action="allow", labels=labels, scores=scores)

    def apply_agent(self, preliminary: Decision, agent: AgentDecision) -> Decision:
        if not agent.used or agent.action == "allow":
            scores = dict(preliminary.scores)
            scores["agent"] = round(agent.score, 4)
            return Decision(
                risk_level=preliminary.risk_level,
                action=preliminary.action,
                labels=preliminary.labels,
                scores=scores,
            )

        labels = list(dict.fromkeys([*preliminary.labels, *agent.labels]))
        scores = dict(preliminary.scores)
        scores["agent"] = round(agent.score, 4)
        scores["overall"] = round(max(scores.get("overall", 0.0), agent.score), 4)

        if preliminary.action == "block" or agent.action == "block":
            return Decision(risk_level="high", action="block", labels=labels, scores=scores)

        risk_level = self._max_risk(preliminary.risk_level, agent.risk_level)
        return Decision(risk_level=risk_level, action="review", labels=labels, scores=scores)

    def _should_block(
        self,
        hits: list[RuleHit],
        semantic: SemanticResult,
        classifier: ClassifierDecision | None,
        max_score: float,
    ) -> bool:
        if any(hit.action == "block" and hit.risk_level == "high" for hit in hits):
            return True
        if semantic.score >= self.block_score:
            return True
        if classifier is not None and classifier.action == "block":
            return True
        return False

    def _should_review(
        self,
        hits: list[RuleHit],
        semantic: SemanticResult,
        classifier: ClassifierDecision | None,
        max_score: float,
    ) -> bool:
        if any(hit.action in {"review", "block"} for hit in hits):
            return True
        if semantic.score >= self.review_score:
            return True
        if classifier is not None and classifier.action == "review":
            return True
        return max_score >= self.review_score

    def _labels(
        self,
        hits: list[RuleHit],
        semantic: SemanticResult,
        classifier: ClassifierDecision | None,
    ) -> list[str]:
        labels: list[str] = []
        for hit in hits:
            if hit.category not in labels:
                labels.append(hit.category)
        if semantic.score >= self.review_score and semantic.label not in labels:
            labels.append(semantic.label)
        has_high_rule = any(hit.risk_level == "high" for hit in hits)
        classifier_confident = classifier is not None and classifier.score >= self.review_score
        if (
            classifier is not None
            and classifier.label != "safe"
            and classifier.action in {"review", "block"}
            and (not has_high_rule or classifier_confident)
            and classifier.label not in labels
        ):
            labels.append(classifier.label)
        return labels

    @staticmethod
    def _classifier_risk_score(classifier: ClassifierDecision | None) -> float:
        if classifier is None or not classifier.enabled or classifier.label == "safe":
            return 0.0
        return classifier.score

    @staticmethod
    def _max_risk(current: str, incoming: str) -> str:
        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        return incoming if rank.get(incoming, 0) > rank.get(current, 0) else current
