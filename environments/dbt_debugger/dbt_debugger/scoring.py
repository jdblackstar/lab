"""Deterministic scoring of a submitted diagnosis against the scenario's rubric."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from dbt_debugger.claim_text_matching import (
    NEGATION_TOKENS,
    STOPWORDS,
    normalize_text,
    option_is_negated_phrase,
    stem_variants,
)
from dbt_debugger.evidence import evidence_matches
from dbt_debugger.rubric import DiagnosisVariant, Rubric


@dataclass
class Audit:
    """Deterministic audit of one submission. ``strict_pass`` is the reward; the rest
    are diagnostic metrics. The defaults describe a rollout with no submission."""

    has_submission: bool = False
    strict_pass: float = 0.0
    has_bug_match: bool = False
    buggy_models_match: bool = False
    root_cause_ok: bool = False
    fix_ok: bool = False
    required_evidence_ok: bool = False
    required_evidence_coverage: float = 0.0
    forbidden_ok: bool = True
    diagnosis_variant_ok: bool = False
    root_cause_coverage: float = 0.0
    fix_coverage: float = 0.0
    no_bug_semantic_partial: float = 0.0
    expected_models: list[str] = field(default_factory=list)


def score_diagnosis(submission: dict[str, Any] | None, spec: dict[str, Any]) -> Audit:
    """Audit a stored ``submit_diagnosis`` payload against the scenario's rubric.

    A strict pass needs the right ``has_bug`` label, one accepted diagnosis variant fully
    satisfied (models, root cause, fix), every required evidence entry cited, and no
    forbidden claim stated. The coverage fields grade partial understanding.
    """
    audit = Audit(
        has_submission=submission is not None,
        expected_models=list(spec["ground_truth"]["affected_models"]),
    )
    if submission is None:
        return audit
    rubric = Rubric.from_spec(spec)
    root_cause = str(submission.get("root_cause", ""))
    fix = str(submission.get("fix", ""))
    buggy_models = list(submission.get("buggy_models") or [])

    audit.has_bug_match = bool(submission.get("has_bug")) == bool(spec["has_bug"])

    results = [
        variant.evaluate(buggy_models=buggy_models, root_cause=root_cause, fix=fix)
        for variant in rubric.accepted_diagnoses
    ]
    audit.buggy_models_match = any(result.models_ok for result in results)
    audit.root_cause_ok = any(result.root_ok for result in results)
    audit.fix_ok = any(result.fix_ok for result in results)
    audit.diagnosis_variant_ok = any(result.ok for result in results)
    audit.root_cause_coverage = max(
        (result.root_coverage for result in results), default=0.0
    )
    audit.fix_coverage = max((result.fix_coverage for result in results), default=0.0)

    evidence = submission.get("evidence") or []
    requirements = rubric.required_evidence
    hits = sum(
        1
        for requirement in requirements
        if any(evidence_matches(ref, requirement, spec) for ref in evidence)
    )
    audit.required_evidence_coverage = (
        hits / len(requirements) if requirements else 1.0
    )
    audit.required_evidence_ok = hits == len(requirements)

    diagnosis_text = " ".join([root_cause, fix, json.dumps(buggy_models)])
    audit.forbidden_ok = not states_forbidden_claim(diagnosis_text, rubric)

    strict = (
        audit.has_bug_match
        and audit.diagnosis_variant_ok
        and audit.required_evidence_ok
        and audit.forbidden_ok
    )
    audit.strict_pass = 1.0 if strict else 0.0
    if not spec["has_bug"] and audit.has_bug_match and audit.forbidden_ok:
        audit.no_bug_semantic_partial = (
            audit.root_cause_coverage
            + audit.fix_coverage
            + audit.required_evidence_coverage
        ) / 3.0
    return audit


# -- forbidden claims ----------------------------------------------------------------
#
# A forbidden claim pattern matches like an accepted one, except that an option found in
# text that explicitly negates it does not count: "the mart is not broken" must not trip
# a forbidden "broken" claim. Two negations are recognised. A negation token in the same
# clause with at most one content word before the option ("is not really broken"), and
# an accepted negated phrase from the rubric itself ("no dbt bug") covering the span.

_Span = tuple[int, int]
_TokenSpan = tuple[int, int, str]

_CLAUSE_BOUNDARY_PATTERN = re.compile(r"[.;:!?]")
_NEGATION_FILLER_TOKENS = frozenset(
    {
        "a",
        "an",
        "the",
        "any",
        "all",
        "and",
        "at",
        "be",
        "been",
        "being",
        "am",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "to",
        "of",
        "in",
        "on",
        "with",
        "for",
        "that",
        "this",
        "it",
        "or",
        "really",
        "very",
    }
)
_NEGATION_CANCEL_TOKENS = frozenset({"just", "only"})


def states_forbidden_claim(text: str, rubric: Rubric) -> bool:
    """Return whether *text* states any ``forbidden_claims`` pattern outside negation."""
    normalized = normalize_text(text)
    protected = _accepted_negation_spans(normalized, rubric.accepted_diagnoses)
    token_spans = _token_spans(normalized)
    return any(
        all(
            _forbidden_group_matches(normalized, group, protected, token_spans)
            for group in pattern.groups
        )
        for pattern in rubric.forbidden_claims
    )


def _token_spans(normalized_text: str) -> list[_TokenSpan]:
    """Return ``(start, end, token)`` spans for tokens in normalized text."""
    return [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(r"[a-z0-9_]+", normalized_text)
    ]


def _matching_option_spans(normalized_text: str, option: str) -> list[_Span]:
    """Return spans where *option* matches under the claim-matching rules."""
    normalized_option = normalize_text(option)
    if not normalized_option:
        return []
    if any(ch in normalized_option for ch in (" ", "_", "/", ".", "-", "+")):
        spans: list[_Span] = []
        start = normalized_text.find(normalized_option)
        while start >= 0:
            spans.append((start, start + len(normalized_option)))
            start = normalized_text.find(normalized_option, start + 1)
        return spans
    option_stems = stem_variants(normalized_option)
    return [
        (start, end)
        for start, end, raw in _token_spans(normalized_text)
        if len(raw) > 2
        and raw not in STOPWORDS
        and bool(option_stems & stem_variants(raw))
    ]


def _accepted_negation_spans(
    normalized_text: str, variants: tuple[DiagnosisVariant, ...]
) -> list[_Span]:
    """Return spans of accepted phrases that themselves negate a bad claim."""
    spans: set[_Span] = set()
    for variant in variants:
        for pattern in (variant.root_cause, *variant.fix_variants):
            for option in pattern.options:
                if option_is_negated_phrase(option):
                    spans.update(_matching_option_spans(normalized_text, option))
    return sorted(spans)


def _span_is_protected(span: _Span, protected_spans: list[_Span]) -> bool:
    """Return whether *span* is fully covered by one accepted negated phrase."""
    start, end = span
    return any(
        protected_start <= start and end <= protected_end
        for protected_start, protected_end in protected_spans
    )


def _span_is_locally_negated(
    normalized_text: str, span: _Span, token_spans: list[_TokenSpan]
) -> bool:
    """Return whether a matched forbidden span is negated within its clause."""
    start, end = span
    token_indexes = [
        idx
        for idx, (token_start, token_end, _) in enumerate(token_spans)
        if token_start < end and start < token_end
    ]
    if not token_indexes:
        return False
    first_token_index = token_indexes[0]
    content_tokens_between = 0
    interstitial_tokens: list[str] = []
    for idx in range(first_token_index - 1, -1, -1):
        _, token_end, token = token_spans[idx]
        next_token_start = token_spans[idx + 1][0]
        between = normalized_text[token_end:next_token_start]
        if _CLAUSE_BOUNDARY_PATTERN.search(between):
            break
        if token in NEGATION_TOKENS:
            return not bool(set(interstitial_tokens) & _NEGATION_CANCEL_TOKENS)
        interstitial_tokens.append(token)
        if token not in _NEGATION_FILLER_TOKENS:
            content_tokens_between += 1
            if content_tokens_between > 1:
                break
    return False


def _forbidden_group_matches(
    normalized_text: str,
    alternatives: tuple[str, ...],
    protected_spans: list[_Span],
    token_spans: list[_TokenSpan],
) -> bool:
    """Return whether one forbidden group matches outside protected or negated spans."""
    return any(
        not _span_is_protected(span, protected_spans)
        and not _span_is_locally_negated(normalized_text, span, token_spans)
        for option in alternatives
        if option
        for span in _matching_option_spans(normalized_text, option)
    )
