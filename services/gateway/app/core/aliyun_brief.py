"""Aliyun content-safety response normalization for brief gateway output."""

from __future__ import annotations

import json
import re
from typing import Any


RISK_LEVEL_TO_RESULT = {
    "high": "block",
    "medium": "review",
    "low": "allow",
    "none": "allow",
    "pass": "allow",
}


def to_aliyun_brief(body: Any, content_id: str | None) -> dict[str, str] | None:
    """Convert an Aliyun sensitive-word response into the project's compact response.

    Aliyun SDK callers often return ``{"statusCode": 200, "body": "{...}"}``, while direct HTTP
    integrations may return the inner ``{"code": 200, "data": ...}`` object. This helper accepts
    both shapes and returns ``None`` for normal project responses so the gateway can keep passing
    them through unchanged.
    """

    payload = _extract_payload(body)
    if payload is None:
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    results = data.get("result")
    if not isinstance(results, list):
        return None

    risk_level = str(data.get("riskLevel") or "none").strip().lower()
    result = RISK_LEVEL_TO_RESULT.get(risk_level, "review" if results else "allow")
    return {
        "content_id": content_id or str(payload.get("requestId") or ""),
        "result": result,
        "reason": _build_reason(data, results, risk_level, result),
    }


def _extract_payload(body: Any) -> dict[str, Any] | None:
    """Return the inner Aliyun JSON object if the response looks like Aliyun output."""

    if not isinstance(body, dict):
        return None

    wrapped_body = body.get("body")
    if isinstance(wrapped_body, str):
        try:
            parsed = json.loads(wrapped_body)
        except json.JSONDecodeError:
            return None
        return parsed if _is_aliyun_payload(parsed) else None

    if isinstance(wrapped_body, dict) and _is_aliyun_payload(wrapped_body):
        return wrapped_body

    return body if _is_aliyun_payload(body) else None


def _is_aliyun_payload(value: Any) -> bool:
    """Detect Aliyun's content-safety payload without relying on endpoint names."""

    if not isinstance(value, dict):
        return False
    data = value.get("data")
    return isinstance(data, dict) and "riskLevel" in data and isinstance(data.get("result"), list)


def _build_reason(data: dict[str, Any], results: list[Any], risk_level: str, result: str) -> str:
    """Create a business-readable failure reason from Aliyun evidence fields."""

    result_items = [item for item in results if isinstance(item, dict)]
    descriptions = _unique(str(item.get("description") or "").strip() for item in result_items)
    labels = _unique(str(item.get("label") or "").strip() for item in result_items)
    words = _unique(_risk_words(result_items))
    confidence = _max_confidence(result_items)

    parts: list[str] = []
    if descriptions:
        parts.append(f"原因 {'、'.join(descriptions[:3])}")
    if words:
        parts.append(f"命中词 {'、'.join(words[:5])}")
    if labels:
        parts.append(f"标签 {','.join(labels[:3])}")
    if confidence is not None:
        parts.append(f"置信度 {confidence:g}")
    if parts:
        return "；".join(parts)
    return "未命中阿里云敏感词风险" if result == "allow" else "命中阿里云敏感词风险"


def _risk_words(result_items: list[dict[str, Any]]) -> list[str]:
    """Collect risk words from detailed positions first, then summary strings."""

    words: list[str] = []
    seen_plain_words: set[str] = set()
    for item in result_items:
        positions = item.get("riskPositions")
        if isinstance(positions, list):
            for position in positions:
                if not isinstance(position, dict):
                    continue
                word = str(position.get("riskWord") or "").strip()
                if not word:
                    continue
                seen_plain_words.add(word)
                start = position.get("startPos")
                end = position.get("endPos")
                if isinstance(start, int) and isinstance(end, int):
                    words.append(f"{word}({start}-{end})")
                else:
                    words.append(word)

        raw_words = str(item.get("riskWords") or "").strip()
        if raw_words:
            words.extend(
                word.strip()
                for word in re.split(r"[,，;；\s]+", raw_words)
                if word.strip() and word.strip() not in seen_plain_words
            )
    return words


def _max_confidence(result_items: list[dict[str, Any]]) -> float | None:
    """Return the strongest confidence score from Aliyun result items."""

    scores: list[float] = []
    for item in result_items:
        try:
            scores.append(float(item.get("confidence")))
        except (TypeError, ValueError):
            continue
    return max(scores) if scores else None


def _unique(values: Any) -> list[str]:
    """Deduplicate non-empty strings while keeping source order."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
