from __future__ import annotations

import re


_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "from",
    "in",
    "into",
    "new",
    "of",
    "on",
    "our",
    "the",
    "to",
    "with",
    "your",
}


def compact_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def significant_terms(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9']+", text.lower())
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 2]
