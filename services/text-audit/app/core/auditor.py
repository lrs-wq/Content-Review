"""Pipeline coordinator for text moderation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import Settings
from app.core.context_builder import ContextBuilder
from app.core.decision import DecisionMaker
from app.core.rule_engine import RuleEngine
from app.core.semantic_model import SemanticModel
from app.core.small_agent import SmallAgent
from app.core.text_classifier import TextClassifier
from app.schemas.moderation import (
    AgentReviewPayload,
    ClassifierReviewPayload,
    RuleHitPayload,
    TextModerationRequest,
    TextModerationResponse,
)


class TextAuditor:
    """Runs rule matching, small-model classification, context agent review, and fusion."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.policy_version = settings.policy_version
        # Rule engine stays first because deterministic high-confidence hits are cheap and
        # explainable. Later semantic layers handle wording that is hard to enumerate.
        self.rules = RuleEngine(settings.term_paths, settings.allow_terms_path)
        self.semantic_model = SemanticModel(settings.model_name, settings.enable_model)
        self.text_classifier = TextClassifier(settings.thresholds_path, settings.repo_root)
        self.decider = DecisionMaker(settings.thresholds_path)
        self.small_agent = SmallAgent(settings.thresholds_path)
        self.context_builder = ContextBuilder(max_chars=self.small_agent.max_context_chars)

    @property
    def model_status(self) -> str:
        return self.semantic_model.status

    @property
    def agent_status(self) -> str:
        return self.small_agent.status

    @property
    def classifier_status(self) -> str:
        return self.text_classifier.status

    def audit(self, payload: TextModerationRequest) -> TextModerationResponse:
        """Moderate one text package and return a stable API response."""

        # The context package is the key difference from plain keyword matching: title, parent
        # comments, OCR, ASR, and custom business fields are folded into one bounded text window.
        context_package = self.context_builder.build(payload)
        scan = self.rules.scan(context_package.aggregate_text)
        semantic = self.semantic_model.infer(scan.normalized_text)
        classifier = self.text_classifier.classify(scan.normalized_text)
        preliminary = self.decider.decide(scan.hits, semantic, classifier)
        # The lightweight agent only runs after the cheap layers and only when the case is gray or
        # context-heavy. It is intentionally used as a precision layer, not as the main hot path.
        agent_result = self.small_agent.review(context_package, preliminary)
        decision = self.decider.apply_agent(preliminary, agent_result)

        return TextModerationResponse(
            trace_id=self._trace_id(),
            content_id=payload.content_id,
            risk_level=decision.risk_level,
            action=decision.action,
            labels=decision.labels,
            scores=decision.scores,
            hits=[
                RuleHitPayload(
                    type=hit.type,
                    category=hit.category,
                    term=hit.term,
                    risk_level=hit.risk_level,
                    action=hit.action,
                    score=hit.score,
                    span=list(hit.span) if hit.span is not None else None,
                )
                for hit in scan.hits
            ],
            allow_hits=scan.allow_hits,
            normalized_text=scan.normalized_text,
            classifier_review=ClassifierReviewPayload(
                enabled=classifier.enabled,
                label=classifier.label,
                score=classifier.score,
                action=classifier.action,
                risk_level=classifier.risk_level,
                model_version=classifier.model_version,
                error=classifier.error,
            ),
            agent_review=AgentReviewPayload(
                used=agent_result.used,
                trigger_reason=agent_result.trigger_reason,
                risk_level=agent_result.risk_level,
                action=agent_result.action,
                labels=agent_result.labels,
                score=agent_result.score,
                reason=agent_result.reason,
                evidence=agent_result.evidence,
            ),
            policy_version=self.policy_version,
            model_status=self.model_status,
        )

    @staticmethod
    def _trace_id() -> str:
        """Create a short trace id suitable for logs, UI output, and user reports."""

        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"tr_{now}_{uuid4().hex[:8]}"
