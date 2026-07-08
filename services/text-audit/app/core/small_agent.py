"""Heuristic small-agent layer for gray-zone or context-heavy text decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import load_yaml
from app.core.context_builder import ContextPackage, normalized_context_text
from app.core.decision import Decision


VIOLENCE_RE = re.compile(
    # Broad verb-object violence hint. It deliberately avoids hardcoding every possible target
    # noun so variants like "杀猫/杀狗/杀兔" still trigger semantic review.
    r"(杀|宰|弄死|打死|毒死|捅|砍|烧死|灭了|干掉)(?:了|掉)?[\w\u4e00-\u9fff]{0,8}"
)
DIRECT_THREAT_RE = re.compile(
    # Direct threats are scored higher than general violent wording because they imply intent.
    r"("
    r"(我要|我想|准备|去|一起|叫人)?[\w\u4e00-\u9fff]{0,6}"
    r"(杀|宰|弄死|打死|毒死|捅|砍|烧死|灭了|干掉)"
    r"[\w\u4e00-\u9fff]{0,8}(你|他|她|人|猫|狗|宠物|孩子|家人|同学|老师|老板|兔子|动物)"
    r")|("
    r"(把|让|给我)?(你|他|她|人|猫|狗|宠物|孩子|家人|同学|老师|老板|兔子|动物)"
    r"[\w\u4e00-\u9fff]{0,6}(杀|宰|弄死|打死|毒死|捅|砍|烧死|灭了|干掉)"
    r")"
)
AD_RE = re.compile(r"(加微信|微信号|私加|进群|扫码|二维码|联系我).{0,20}(免费|领取|日赚|稳赚|返利|兼职|赚钱)")
FRAUD_RE = re.compile(r"(日赚|稳赚|稳赚不赔|高回报|返利|先交|保证金|刷流水)")
CONTEXT_RELIEF_RE = re.compile(r"(小说|电影|游戏|剧情|新闻|引用|反诈|普法|法律讨论|医学科普|历史资料)")


@dataclass(frozen=True)
class AgentResult:
    """Normalized result from the gray-zone agent layer."""

    used: bool
    trigger_reason: list[str]
    risk_level: str
    action: str
    labels: list[str]
    score: float
    reason: str
    evidence: list[str]


class SmallAgent:
    """A lightweight context judge used only after cheap filters find a gray case."""

    def __init__(self, thresholds_path: Path) -> None:
        thresholds = load_yaml(thresholds_path)
        text_thresholds = thresholds.get("text", {}) if isinstance(thresholds.get("text", {}), dict) else {}
        agent_config = text_thresholds.get("agent", {}) if isinstance(text_thresholds.get("agent", {}), dict) else {}

        self.enabled = bool(agent_config.get("enabled", True))
        self.provider = str(agent_config.get("provider", "heuristic"))
        self.gray_min_score = float(agent_config.get("gray_min_score", 0.45))
        self.gray_max_score = float(agent_config.get("gray_max_score", 0.92))
        self.max_context_chars = int(agent_config.get("max_context_chars", 3000))

    @property
    def status(self) -> str:
        return f"{self.provider}:{'enabled' if self.enabled else 'disabled'}"

    def review(self, package: ContextPackage, preliminary: Decision) -> AgentResult:
        """Review a context package when score/context triggers warrant deeper inspection."""

        trigger_reason = self._trigger_reason(package, preliminary)
        if not self.enabled or not trigger_reason:
            return AgentResult(
                used=False,
                trigger_reason=trigger_reason,
                risk_level="none",
                action="allow",
                labels=[],
                score=0.0,
                reason="上下文审查未触发",
                evidence=[],
            )

        text = normalized_context_text(package)
        relief = bool(CONTEXT_RELIEF_RE.search(text))
        labels: list[str] = []
        evidence: list[str] = []
        score = 0.0
        action = "allow"
        risk_level = "none"
        reason = "上下文未发现额外风险"

        # Run the more specific threat pattern before the broad violence pattern so explicit
        # intent receives stronger action and evidence.
        violence = self._find(VIOLENCE_RE, text)
        direct_threat = self._find(DIRECT_THREAT_RE, text)
        ad = self._find(AD_RE, text)
        fraud = self._find(FRAUD_RE, text)

        if direct_threat:
            labels.append("violence")
            evidence.append(direct_threat)
            score = 0.94 if not relief else 0.72
            risk_level = "high" if not relief else "medium"
            action = "block" if not relief else "review"
            reason = "发现明确暴力意图"
        elif violence:
            labels.append("violence")
            evidence.append(violence)
            score = 0.82 if not relief else 0.58
            risk_level = "medium"
            action = "review"
            reason = "发现疑似暴力表述，需人工复核"

        if ad:
            labels.append("ad")
            evidence.append(ad)
            score = max(score, 0.78)
            risk_level = self._max_risk(risk_level, "medium")
            action = self._max_action(action, "review")
            reason = "发现疑似广告引流模式"
        elif fraud:
            labels.append("fraud")
            evidence.append(fraud)
            score = max(score, 0.7)
            risk_level = self._max_risk(risk_level, "medium")
            action = self._max_action(action, "review")
            reason = "发现疑似诈骗收益承诺"

        labels = list(dict.fromkeys(labels))
        return AgentResult(
            used=True,
            trigger_reason=trigger_reason,
            risk_level=risk_level,
            action=action,
            labels=labels,
            score=round(score, 4),
            reason=reason,
            evidence=list(dict.fromkeys(evidence))[:5],
        )

    def _trigger_reason(self, package: ContextPackage, preliminary: Decision) -> list[str]:
        """Decide whether the agent should run for this request."""

        if preliminary.action == "block":
            return []

        reasons: list[str] = []
        overall = preliminary.scores.get("overall", 0.0)
        text = normalized_context_text(package)
        has_suspicious_hint = self._has_suspicious_hint(text)

        if (
            preliminary.scores.get("rule", 0.0) > 0
            and not package.has_complex_context
            and not has_suspicious_hint
        ):
            return []

        if self.gray_min_score <= overall < self.gray_max_score:
            reasons.append("gray_score")
        if package.has_complex_context:
            reasons.append("complex_context")
        if has_suspicious_hint:
            reasons.append("suspicious_context_hint")
        return reasons

    @staticmethod
    def _has_suspicious_hint(text: str) -> bool:
        """Detect hints that deserve agent review even when rules did not fire."""

        return any(pattern.search(text) for pattern in (VIOLENCE_RE, AD_RE, FRAUD_RE))

    @staticmethod
    def _find(pattern: re.Pattern[str], text: str) -> str | None:
        """Return the first matched evidence span for compact API output."""

        match = pattern.search(text)
        return match.group(0) if match else None

    @staticmethod
    def _max_risk(current: str, incoming: str) -> str:
        """Return the higher risk level."""

        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        return incoming if rank[incoming] > rank[current] else current

    @staticmethod
    def _max_action(current: str, incoming: str) -> str:
        """Return the stricter action."""

        rank = {"allow": 0, "review": 1, "block": 2}
        return incoming if rank[incoming] > rank[current] else current
