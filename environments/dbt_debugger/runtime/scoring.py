"""Deterministic diagnosis scoring for ``StatefulToolEnv`` rubrics."""

from __future__ import annotations

import json
import re
from typing import Any

from claim_text_matching import (
    STOPWORDS,
    claim_group_matches,
    iter_claim_pattern_options,
    normalize_text,
    option_is_negated_phrase,
    stem_variants,
    text_contains_option,
)
from runtime.types import ClaimPattern, DiagnosisVariant, EvidenceRef, EvidenceRequirement


def _token_spans(normalized_text: str) -> list[tuple[int, int, str]]:
    """Return ``(start, end, token)`` spans for tokens in normalized text."""
    return [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(r"[a-z0-9_]+", normalized_text)
    ]


def _matching_option_spans(
    normalized_text: str,
    option: str,
) -> list[tuple[int, int]]:
    """Return spans where *option* matches under the claim-matching rules."""
    normalized_option = normalize_text(option)
    if not normalized_option:
        return []
    if any(ch in normalized_option for ch in (" ", "_", "/", ".", "-", "+")):
        spans: list[tuple[int, int]] = []
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


def _claim_pattern_matches(text: str, pattern: ClaimPattern) -> bool:
    """Return whether *text* satisfies all claim groups in *pattern*."""
    return all(claim_group_matches(text, group) for group in pattern)


def _accepted_negation_spans(
    text: str,
    variants: list[DiagnosisVariant],
) -> list[tuple[int, int]]:
    """Return spans of matched accepted phrases that explicitly negate a bad claim."""
    normalized_text = normalize_text(text)
    spans: set[tuple[int, int]] = set()
    for variant in variants:
        root_pattern = variant.get("root_cause_all_of") or []
        for option in iter_claim_pattern_options(root_pattern):
            if option_is_negated_phrase(option):
                spans.update(_matching_option_spans(normalized_text, option))
        for fix_pattern in variant.get("fix_variants") or []:
            for option in iter_claim_pattern_options(fix_pattern):
                if option_is_negated_phrase(option):
                    spans.update(_matching_option_spans(normalized_text, option))
    return sorted(spans)


def _span_is_protected(
    span: tuple[int, int],
    protected_spans: list[tuple[int, int]],
) -> bool:
    """Return whether *span* is fully covered by one protected accepted phrase span."""
    start, end = span
    return any(
        protected_start <= start and end <= protected_end
        for protected_start, protected_end in protected_spans
    )


def _forbidden_option_matches_text(
    normalized_text: str,
    option: str,
    protected_spans: list[tuple[int, int]],
) -> bool:
    """Return whether *option* matches outside accepted negated phrase spans."""
    return any(
        not _span_is_protected(span, protected_spans)
        for span in _matching_option_spans(normalized_text, option)
    )


def _forbidden_claim_group_matches(
    normalized_text: str,
    alternatives: list[str],
    protected_spans: list[tuple[int, int]],
) -> bool:
    """Return whether one forbidden group matches outside protected accepted phrases."""
    return any(
        _forbidden_option_matches_text(normalized_text, option, protected_spans)
        for option in alternatives
        if option
    )


def _forbidden_claim_pattern_matches(
    normalized_text: str,
    pattern: ClaimPattern,
    protected_spans: list[tuple[int, int]],
) -> bool:
    """Return whether all groups in a forbidden pattern match outside protected spans."""
    return all(
        _forbidden_claim_group_matches(normalized_text, group, protected_spans)
        for group in pattern
    )


def _claim_pattern_coverage(text: str, pattern: ClaimPattern) -> float:
    """Return the fraction of claim groups in *pattern* satisfied by *text*."""
    if not pattern:
        return 1.0
    hits = sum(1 for group in pattern if claim_group_matches(text, group))
    return hits / max(1, len(pattern))


def _iter_project_files(spec: dict[str, Any]) -> dict[str, str]:
    """Return a path->content mapping across bundled project files/macros/seeds."""
    dbt_project = spec.get("dbt_project") or {}
    out: dict[str, str] = {}
    for key in ("files", "macros", "seeds"):
        for entry in dbt_project.get(key, []) or []:
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path", "")).strip().replace("\\", "/")
            content = entry.get("content", "")
            if path and isinstance(content, str):
                out[path] = content
    return out


def _matching_sample_rows(
    table_blob: dict[str, Any],
    match: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return sample rows matching all key/value pairs in *match*."""
    rows = table_blob.get("rows") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(row.get(key) == value for key, value in match.items()):
            out.append(row)
    return out


def _file_evidence_matches(
    evidence_ref: EvidenceRef,
    requirement: EvidenceRequirement,
    files: dict[str, str],
) -> bool:
    """Return whether a file-span citation grounds the required artifact fact."""
    if evidence_ref.get("kind") != "file_span" or requirement.get("kind") != "file_span":
        return False
    path = str(evidence_ref.get("path", ""))
    if path != str(requirement.get("path", "")):
        return False
    content = files.get(path)
    if content is None:
        return False
    start_line = int(evidence_ref.get("start_line", 0))
    end_line = int(evidence_ref.get("end_line", 0))
    if start_line < 1 or end_line < start_line:
        return False
    lines = content.splitlines()
    end_line = min(end_line, len(lines))
    segment = "\n".join(lines[start_line - 1 : end_line])
    return all(
        text_contains_option(segment, anchor)
        for anchor in requirement.get("all_of") or []
    )


def _sample_evidence_matches(
    evidence_ref: EvidenceRef,
    requirement: EvidenceRequirement,
    sample_data: dict[str, Any],
) -> bool:
    """Return whether a sample-row citation grounds the required source fact."""
    if evidence_ref.get("kind") != "sample_rows" or requirement.get("kind") != "sample_rows":
        return False
    table = str(evidence_ref.get("table", ""))
    if table != str(requirement.get("table", "")):
        return False
    table_blob = sample_data.get(table)
    if not isinstance(table_blob, dict):
        return False
    submitted_match_json = evidence_ref.get("match_json")
    required_match = requirement.get("match") or {}
    if not isinstance(submitted_match_json, str) or not submitted_match_json.strip():
        return False
    try:
        submitted_match = json.loads(submitted_match_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(submitted_match, dict) or not submitted_match:
        return False
    for key, value in required_match.items():
        if submitted_match.get(key) != value:
            return False
    matched_rows = _matching_sample_rows(table_blob, submitted_match)
    if len(matched_rows) < int(requirement.get("min_rows", 1)):
        return False
    evidence_blob = json.dumps(matched_rows, sort_keys=True)
    return all(
        text_contains_option(evidence_blob, anchor)
        for anchor in requirement.get("all_of") or []
    )


def _run_history_evidence_matches(
    evidence_ref: EvidenceRef,
    requirement: EvidenceRequirement,
    run_history: dict[str, Any],
) -> bool:
    """Return whether a run-history citation grounds the required operational fact."""
    if evidence_ref.get("kind") != "run_history" or requirement.get("kind") != "run_history":
        return False
    record_type = str(evidence_ref.get("record_type", ""))
    if record_type != str(requirement.get("record_type", "")):
        return False
    if record_type == "summary":
        summary = str(run_history.get("summary", ""))
        required_contains = str(requirement.get("contains", "")).strip()
        cited_contains = str(evidence_ref.get("contains", "")).strip()
        if required_contains and not text_contains_option(summary, required_contains):
            return False
        if cited_contains and not text_contains_option(summary, cited_contains):
            return False
        return True
    if record_type == "warning":
        warnings = [str(item) for item in run_history.get("warnings", []) if isinstance(item, str)]
        required_contains = str(requirement.get("contains", "")).strip()
        cited_contains = str(evidence_ref.get("contains", "")).strip()
        for warning in warnings:
            if required_contains and not text_contains_option(warning, required_contains):
                continue
            if cited_contains and not text_contains_option(warning, cited_contains):
                continue
            return True
        return False
    records_key = "model_results" if record_type == "model" else "tests"
    records = run_history.get(records_key) or []
    required_name_key = "model" if record_type == "model" else "name"
    required_name = str(requirement.get(required_name_key, "")).strip()
    cited_name = str(evidence_ref.get(required_name_key, "")).strip()
    required_status = str(requirement.get("status", "")).strip().lower()
    cited_status = str(evidence_ref.get("status", "")).strip().lower()
    required_contains = str(requirement.get("contains", "")).strip()
    cited_contains = str(evidence_ref.get("contains", "")).strip()
    for record in records:
        if not isinstance(record, dict):
            continue
        record_name = str(record.get(required_name_key, "")).strip()
        if required_name and record_name != required_name:
            continue
        if cited_name and record_name != cited_name:
            continue
        record_status = str(record.get("status", "")).strip().lower()
        if required_status and record_status != required_status:
            continue
        if cited_status and record_status != cited_status:
            continue
        if required_contains and not text_contains_option(
            json.dumps(record, sort_keys=True),
            required_contains,
        ):
            continue
        if cited_contains and not text_contains_option(
            json.dumps(record, sort_keys=True),
            cited_contains,
        ):
            continue
        return True
    return False


def _evidence_requirement_satisfied(
    requirement: EvidenceRequirement,
    evidence_refs: list[EvidenceRef],
    spec: dict[str, Any],
) -> bool:
    """Return whether any submitted evidence ref satisfies one requirement."""
    files = _iter_project_files(spec)
    sample_data = spec.get("sample_data") or {}
    run_history = spec.get("run_history") or {}
    for evidence_ref in evidence_refs:
        if _file_evidence_matches(evidence_ref, requirement, files):
            return True
        if _sample_evidence_matches(evidence_ref, requirement, sample_data):
            return True
        if _run_history_evidence_matches(evidence_ref, requirement, run_history):
            return True
    return False


def _evaluate_variant(
    submission: dict[str, Any],
    variant: DiagnosisVariant,
) -> dict[str, Any]:
    """Evaluate one accepted diagnosis variant against the submission."""
    required_models = set(variant.get("required_models") or [])
    raw_allowed = variant.get("allowed_models")
    allowed_models = (
        set(raw_allowed) if raw_allowed is not None else set(required_models)
    )
    submitted_models = set(submission.get("affected_models") or [])
    models_ok = required_models.issubset(submitted_models) and submitted_models.issubset(
        allowed_models
    )
    root_cause_text = str(submission.get("root_cause", ""))
    fix_text = str(submission.get("fix", ""))
    root_pattern = variant.get("root_cause_all_of") or []
    root_ok = _claim_pattern_matches(root_cause_text, root_pattern)
    root_coverage = _claim_pattern_coverage(root_cause_text, root_pattern)
    fix_variants = variant.get("fix_variants") or []
    if fix_variants:
        fix_ok = any(_claim_pattern_matches(fix_text, pattern) for pattern in fix_variants)
        fix_coverage = max(_claim_pattern_coverage(fix_text, pattern) for pattern in fix_variants)
    else:
        fix_ok = True
        fix_coverage = 1.0
    return {
        "models_ok": models_ok,
        "root_ok": root_ok,
        "fix_ok": fix_ok,
        "root_coverage": root_coverage,
        "fix_coverage": fix_coverage,
        "variant_ok": models_ok and root_ok and fix_ok,
    }


def score_diagnosis(
    submission: dict[str, Any] | None,
    scenario_spec: dict[str, Any],
) -> dict[str, Any]:
    """Compare a structured submission to the scenario's evaluator-only scoring contract."""
    ground_truth = scenario_spec.get("ground_truth") or {}
    rubric_hints = scenario_spec.get("rubric_hints") or {}
    out: dict[str, Any] = {
        "has_submission": submission is not None,
        "strict_pass": 0.0,
        "has_bug_match": False,
        "affected_models_match": False,
        "root_cause_ok": False,
        "fix_ok": False,
        "required_evidence_ok": False,
        "required_evidence_coverage": 0.0,
        "forbidden_ok": True,
        "diagnosis_variant_ok": False,
        "root_cause_coverage": 0.0,
        "fix_coverage": 0.0,
    }
    if submission is None:
        return out

    out["has_bug_match"] = bool(submission.get("has_bug")) == bool(scenario_spec.get("has_bug"))

    variants = [
        item
        for item in (rubric_hints.get("accepted_diagnoses") or [])
        if isinstance(item, dict)
    ]
    if variants:
        variant_results = [_evaluate_variant(submission, variant) for variant in variants]
        out["affected_models_match"] = any(item["models_ok"] for item in variant_results)
        out["root_cause_ok"] = any(item["root_ok"] for item in variant_results)
        out["fix_ok"] = any(item["fix_ok"] for item in variant_results)
        out["diagnosis_variant_ok"] = any(item["variant_ok"] for item in variant_results)
        out["root_cause_coverage"] = max(item["root_coverage"] for item in variant_results)
        out["fix_coverage"] = max(item["fix_coverage"] for item in variant_results)

    evidence_refs = [
        item
        for item in (submission.get("evidence") or [])
        if isinstance(item, dict)
    ]
    requirements = [
        item
        for item in (rubric_hints.get("required_evidence") or [])
        if isinstance(item, dict)
    ]
    if requirements:
        evidence_hits = sum(
            1
            for requirement in requirements
            if _evidence_requirement_satisfied(requirement, evidence_refs, scenario_spec)
        )
        out["required_evidence_coverage"] = evidence_hits / max(1, len(requirements))
        out["required_evidence_ok"] = evidence_hits == len(requirements)
    else:
        out["required_evidence_coverage"] = 1.0
        out["required_evidence_ok"] = True

    diagnosis_blob = " ".join(
        [
            str(submission.get("root_cause", "")),
            str(submission.get("fix", "")),
            json.dumps(submission.get("affected_models") or []),
        ]
    )
    normalized_diagnosis_blob = normalize_text(diagnosis_blob)
    protected_spans = _accepted_negation_spans(diagnosis_blob, variants)
    for forbidden in rubric_hints.get("forbidden_claims") or []:
        if isinstance(forbidden, list) and _forbidden_claim_pattern_matches(
            normalized_diagnosis_blob,
            forbidden,
            protected_spans,
        ):
            out["forbidden_ok"] = False
            break

    strict = (
        out["has_bug_match"]
        and out["diagnosis_variant_ok"]
        and out["required_evidence_ok"]
        and out["forbidden_ok"]
    )
    out["strict_pass"] = 1.0 if strict else 0.0
    out["expected_models"] = ground_truth.get("affected_models") or []
    return out
