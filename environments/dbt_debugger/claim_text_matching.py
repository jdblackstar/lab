"""Shared text normalization and claim-option matching for diagnosis rubrics.

Used by runtime scoring and offline scenario validation so behavior cannot drift.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "as",
        "at",
        "by",
        "from",
        "that",
        "this",
        "it",
        "not",
        "no",
        "if",
        "then",
        "than",
        "into",
        "over",
        "via",
    }
)

NEGATION_TOKENS = frozenset({"no", "not", "never", "without", "neither", "nor"})


def normalize_text(value: str) -> str:
    """Lowercase, strip accents lightly, and collapse whitespace."""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def stem_token(token: str) -> str:
    """Apply a tiny suffix-stripper so simple rephrasings still match."""
    for suffix in (
        "ively",
        "ingly",
        "edly",
        "ation",
        "ments",
        "ment",
        "ings",
        "ing",
        "ied",
        "ies",
        "ed",
        "ly",
        "s",
    ):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            if suffix == "ies":
                return token[: -len(suffix)] + "y"
            if suffix == "ied":
                return token[: -len(suffix)] + "y"
            return token[: -len(suffix)]
    return token


def stem_variants(token: str) -> set[str]:
    """Return stem forms that align e-final bases with *-ed* / *-ing* stems."""
    stem = stem_token(token)
    variants = {stem}
    if stem.endswith("e") and len(stem) > 4:
        variants.add(stem[:-1])
    return variants


def tokens(value: str) -> set[str]:
    """Return normalized token stems for lightweight semantic matching."""
    parts = re.findall(r"[a-z0-9_]+", normalize_text(value))
    out: set[str] = set()
    for part in parts:
        if len(part) > 2 and part not in STOPWORDS:
            out.update(stem_variants(part))
    return out


def text_contains_option(text: str, option: str) -> bool:
    """Return whether *text* contains a claim option."""
    normalized_option = normalize_text(option)
    if not normalized_option:
        return False
    if any(ch in normalized_option for ch in (" ", "_", "/", ".", "-", "+")):
        return normalized_option in normalize_text(text)
    return bool(stem_variants(normalized_option) & tokens(text))


def claim_group_matches(text: str, alternatives: list[str]) -> bool:
    """Return whether *text* satisfies at least one alternative in a claim group."""
    return any(text_contains_option(text, option) for option in alternatives if option)


def iter_claim_pattern_options(pattern: Sequence[Sequence[str]]) -> list[str]:
    """Return all non-empty options declared across a claim pattern."""
    return [option for group in pattern for option in group if option]


def option_is_negated_phrase(option: str) -> bool:
    """Return whether *option* is a multi-word accepted phrase with explicit negation."""
    normalized_option = normalize_text(option)
    if not any(ch in normalized_option for ch in (" ", "_", "/", ".", "-", "+")):
        return False
    option_tokens = set(re.findall(r"[a-z0-9_]+", normalized_option))
    return bool(option_tokens & NEGATION_TOKENS)
