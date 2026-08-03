"""Policy for preventing target-specific writeup searches."""

from __future__ import annotations

import re


WRITEUP_TERMS = re.compile(
    r"\b(write[ -]?up|walkthrough|official\s+solution|challenge\s+solution|solve\s+script|flag\s+for)\b",
    re.IGNORECASE,
)
GENERAL_RESEARCH_TERMS = re.compile(
    r"\b(software|library|api|documentation|manual|algorithm|optimization|mathematics|theorem|research\s+paper)\b",
    re.IGNORECASE,
)


def _challenge_tokens(challenge: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9_+-]{4,}", challenge.lower())
    ignored = {
        "challenge",
        "original",
        "clarifications",
        "description",
        "please",
        "using",
        "with",
        "from",
        "this",
        "that",
        "there",
        "have",
        "find",
        "solve",
    }
    return {word for word in words[:100] if word not in ignored}


def target_writeup_search_reason(query: str, challenge_markdown: str) -> str | None:
    """Return a blocking reason only for obvious target-specific solution searches."""

    if not WRITEUP_TERMS.search(query):
        return None
    normalized = query.lower()
    tokens = _challenge_tokens(challenge_markdown)
    target_matches = sorted(token for token in tokens if token in normalized)
    ctf_specific = bool(re.search(r"\b(ctf|picoctf|hackthebox|tryhackme|challenge)\b", normalized))
    if target_matches or ctf_specific:
        details = f" (matched target terms: {', '.join(target_matches[:4])})" if target_matches else ""
        return "Target-specific writeup/solution searches are prohibited" + details + "."
    if GENERAL_RESEARCH_TERMS.search(query):
        return None
    return None


def is_target_writeup_search(query: str, challenge_markdown: str) -> bool:
    return target_writeup_search_reason(query, challenge_markdown) is not None
