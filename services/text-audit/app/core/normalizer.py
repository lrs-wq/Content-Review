from __future__ import annotations

import re
import unicodedata


ZERO_WIDTH_RE = re.compile("[\u200b-\u200f\ufeff]")
SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    normalized = normalized.lower()
    normalized = SPACE_RE.sub(" ", normalized).strip()
    return normalized


def compact_text(text: str) -> str:
    normalized = normalize_text(text)
    return "".join(char for char in normalized if char.isalnum())

