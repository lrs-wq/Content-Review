from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.core.normalizer import compact_text, normalize_text


RISK_SCORE = {
    "high": 0.95,
    "medium": 0.75,
    "low": 0.45,
}


@dataclass(frozen=True)
class TermRule:
    term: str
    category: str
    risk_level: str
    match_type: str
    action: str
    enabled: bool
    notes: str = ""
    normalized_term: str = field(init=False, repr=False)
    compact_term: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_term", normalize_text(self.term))
        object.__setattr__(self, "compact_term", compact_text(self.term))


@dataclass(frozen=True)
class RuleHit:
    type: str
    category: str
    term: str
    risk_level: str
    action: str
    score: float
    span: tuple[int, int] | None = None


@dataclass(frozen=True)
class RuleScanResult:
    normalized_text: str
    compacted_text: str
    hits: list[RuleHit]
    allow_hits: list[str]


class RuleEngine:
    def __init__(self, sensitive_terms_path: Path | Iterable[Path], allow_terms_path: Path) -> None:
        paths = [sensitive_terms_path] if isinstance(sensitive_terms_path, Path) else list(sensitive_terms_path)
        self.rules = self._load_rule_files(paths)
        self.allow_terms = self._load_allow_terms(allow_terms_path)

    def scan(self, text: str) -> RuleScanResult:
        normalized = normalize_text(text)
        compacted = compact_text(text)
        allow_hits = self._find_allow_hits(normalized)
        hits: list[RuleHit] = []

        for rule in self.rules:
            if not rule.enabled:
                continue
            hit = self._match_rule(rule, normalized, compacted, allow_hits)
            if hit is not None:
                hits.append(hit)

        return RuleScanResult(
            normalized_text=normalized,
            compacted_text=compacted,
            hits=hits,
            allow_hits=allow_hits,
        )

    def _match_rule(
        self,
        rule: TermRule,
        normalized: str,
        compacted: str,
        allow_hits: Iterable[str],
    ) -> RuleHit | None:
        if self._is_allowed(rule, allow_hits):
            return None

        match_type = rule.match_type.lower()
        span: tuple[int, int] | None = None
        matched = False

        if match_type == "exact":
            matched = normalized == rule.normalized_term
            if matched:
                span = (0, len(normalized))
        elif match_type == "regex":
            result = re.search(rule.term, normalized)
            matched = result is not None
            if result is not None:
                span = (result.start(), result.end())
        elif match_type == "compact":
            matched = bool(rule.compact_term and rule.compact_term in compacted)
        else:
            index = normalized.find(rule.normalized_term)
            matched = index >= 0
            if matched:
                span = (index, index + len(rule.normalized_term))

        if not matched:
            return None

        return RuleHit(
            type="term",
            category=rule.category,
            term=rule.term,
            risk_level=rule.risk_level,
            action=rule.action,
            score=RISK_SCORE.get(rule.risk_level, 0.5),
            span=span,
        )

    def _is_allowed(self, rule: TermRule, allow_hits: Iterable[str]) -> bool:
        normalized_rule = rule.normalized_term
        compact_rule = rule.compact_term
        for allow_term in allow_hits:
            if normalized_rule and normalized_rule in allow_term:
                return True
            if compact_rule and compact_rule in compact_text(allow_term):
                return True
        return False

    def _find_allow_hits(self, normalized: str) -> list[str]:
        hits: list[str] = []
        for term in self.allow_terms:
            if term and term in normalized:
                hits.append(term)
        return hits

    @staticmethod
    def _load_rules(path: Path) -> list[TermRule]:
        if not path.exists():
            return []
        rules: list[TermRule] = []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                term = (row.get("term") or "").strip()
                if not term:
                    continue
                rules.append(
                    TermRule(
                        term=term,
                        category=(row.get("category") or "general").strip(),
                        risk_level=(row.get("risk_level") or "medium").strip().lower(),
                        match_type=(row.get("match_type") or "contains").strip().lower(),
                        action=(row.get("action") or "review").strip().lower(),
                        enabled=(row.get("enabled") or "true").strip().lower() != "false",
                        notes=(row.get("notes") or "").strip(),
                    )
                )
        return rules

    @classmethod
    def _load_rule_files(cls, paths: Iterable[Path]) -> list[TermRule]:
        rules: list[TermRule] = []
        for path in paths:
            rules.extend(cls._load_rules(path))
        return rules

    @staticmethod
    def _load_allow_terms(path: Path) -> list[str]:
        if not path.exists():
            return []
        terms: list[str] = []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                term = normalize_text((row.get("term") or "").strip())
                if term:
                    terms.append(term)
        return terms
