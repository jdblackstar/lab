"""Validate gold scenario JSON files against schema and corpus rules.

Run from repo root or this directory:

    uv run python validation/validate_scenarios.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from claim_text_matching import (
    claim_group_matches,
    iter_claim_pattern_options,
    option_is_negated_phrase,
)

REQUIRED_CATEGORIES = frozenset(
    {"join", "incremental", "source_schema", "logic", "macro", "config", "no_bug"}
)
TARGET_TIER_COUNTS = {1: 2, 2: 3, 3: 3, 4: 2}
MIN_TOTAL_SCENARIOS = 10
MIN_NO_BUG_SCENARIOS = 4


def _pattern_negated_options(pattern: Any, source: str) -> list[tuple[str, str]]:
    """Return all explicitly negated options from one claim pattern."""
    if not _is_claim_pattern(pattern):
        return []
    return [
        (source, option)
        for option in iter_claim_pattern_options(pattern)
        if option_is_negated_phrase(option)
    ]


def _variant_overlaps_forbidden_claim(
    variant: dict[str, Any],
    forbidden: list[list[str]],
) -> list[str]:
    """Return accepted negated phrases that can satisfy every group in *forbidden*."""
    root_options = _pattern_negated_options(
        variant.get("root_cause_all_of"),
        "root_cause_all_of",
    )
    fix_variants = variant.get("fix_variants") or []
    phrase_sets = [
        root_options + _pattern_negated_options(pattern, f"fix_variants[{idx}]")
        for idx, pattern in enumerate(fix_variants)
    ] or [root_options]
    for phrase_set in phrase_sets:
        matched_descriptors: set[str] = set()
        for group in forbidden:
            group_matches = {
                f"{source}: {option}"
                for source, option in phrase_set
                if claim_group_matches(option, group)
            }
            if not group_matches:
                break
            matched_descriptors.update(group_matches)
        else:
            return sorted(matched_descriptors)
    return []


def _scenario_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "scenarios" / "gold"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_claim_group(value: Any) -> bool:
    """Return whether *value* is a non-empty synonym group."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _is_claim_pattern(value: Any) -> bool:
    """Return whether *value* is a non-empty list of claim groups."""
    return isinstance(value, list) and bool(value) and all(
        _is_claim_group(item) for item in value
    )


def _project_file_paths(data: dict[str, Any]) -> set[str]:
    """Return all bundled project paths across files/macros/seeds."""
    dbt_project = data.get("dbt_project", {})
    out: set[str] = set()
    for key in ("files", "macros", "seeds"):
        for entry in dbt_project.get(key, []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                out.add(entry["path"])
    return out


def _validate_required_evidence(
    data: dict[str, Any],
    errors: list[str],
) -> None:
    """Validate structured evidence requirements against scenario artifacts."""
    hints = data.get("rubric_hints", {})
    model_names = {
        m["name"]
        for m in data.get("dag", {}).get("models", [])
        if isinstance(m, dict) and "name" in m
    }
    sample_tables = set((data.get("sample_data") or {}).keys())
    file_paths = _project_file_paths(data)
    requirements = hints.get("required_evidence", [])
    if not isinstance(requirements, list) or not requirements:
        errors.append("rubric_hints.required_evidence must be a non-empty array")
        return
    for idx, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            errors.append(f"required_evidence[{idx}] must be an object")
            continue
        kind = requirement.get("kind")
        if kind == "file_span":
            path = requirement.get("path")
            all_of = requirement.get("all_of")
            if path not in file_paths:
                errors.append(
                    f"required_evidence[{idx}] file_span path not found in project files: {path!r}"
                )
            if not _is_claim_group(all_of):
                errors.append(
                    f"required_evidence[{idx}] file_span all_of must be a non-empty string array"
                )
        elif kind == "sample_rows":
            table = requirement.get("table")
            match = requirement.get("match")
            all_of = requirement.get("all_of")
            if table not in sample_tables:
                errors.append(
                    f"required_evidence[{idx}] sample_rows table not found in sample_data: {table!r}"
                )
            if not isinstance(match, dict) or not match:
                errors.append(
                    f"required_evidence[{idx}] sample_rows match must be a non-empty object"
                )
            if "min_rows" in requirement and (
                not isinstance(requirement.get("min_rows"), int)
                or int(requirement["min_rows"]) < 1
            ):
                errors.append(
                    f"required_evidence[{idx}] sample_rows min_rows must be >= 1"
                )
            if not _is_claim_group(all_of):
                errors.append(
                    f"required_evidence[{idx}] sample_rows all_of must be a non-empty string array"
                )
        elif kind == "run_history":
            record_type = requirement.get("record_type")
            if record_type not in {"summary", "model", "test", "warning"}:
                errors.append(
                    f"required_evidence[{idx}] run_history record_type invalid: {record_type!r}"
                )
            if record_type == "model" and requirement.get("model") not in model_names:
                errors.append(
                    f"required_evidence[{idx}] run_history model must reference dag.models: {requirement.get('model')!r}"
                )
            if record_type == "test" and not str(requirement.get("name", "")).strip():
                errors.append(
                    f"required_evidence[{idx}] run_history test evidence requires name"
                )
            if record_type in {"summary", "warning"} and not str(
                requirement.get("contains", "")
            ).strip():
                errors.append(
                    f"required_evidence[{idx}] run_history {record_type} evidence requires contains"
                )
        else:
            errors.append(
                f"required_evidence[{idx}] kind must be file_span, sample_rows, or run_history"
            )


def _validate_rubric_contract(
    data: dict[str, Any],
    errors: list[str],
) -> None:
    """Validate accepted diagnosis variants and forbidden claim patterns."""
    hints = data.get("rubric_hints", {})
    model_names = {
        m["name"]
        for m in data.get("dag", {}).get("models", [])
        if isinstance(m, dict) and "name" in m
    }
    accepted = hints.get("accepted_diagnoses", [])
    valid_variants: list[tuple[int, dict[str, Any]]] = []
    if not isinstance(accepted, list) or not accepted:
        errors.append("rubric_hints.accepted_diagnoses must be a non-empty array")
    else:
        for idx, variant in enumerate(accepted):
            if not isinstance(variant, dict):
                errors.append(f"accepted_diagnoses[{idx}] must be an object")
                continue
            required_models = variant.get("required_models", [])
            raw_allowed_models = variant.get("allowed_models")
            allowed_models = (
                list(required_models)
                if raw_allowed_models is None
                else raw_allowed_models
            )
            if not isinstance(required_models, list) or not all(
                isinstance(item, str) for item in required_models
            ):
                errors.append(
                    f"accepted_diagnoses[{idx}].required_models must be a string array"
                )
                continue
            if not isinstance(allowed_models, list) or not all(
                isinstance(item, str) for item in allowed_models
            ):
                errors.append(
                    f"accepted_diagnoses[{idx}].allowed_models must be a string array"
                )
                continue
            variant_valid = True
            missing_required = [item for item in required_models if item not in model_names]
            if missing_required:
                errors.append(
                    f"accepted_diagnoses[{idx}] required_models reference unknown models: {missing_required!r}"
                )
                variant_valid = False
            missing_allowed = [item for item in allowed_models if item not in model_names]
            if missing_allowed:
                errors.append(
                    f"accepted_diagnoses[{idx}] allowed_models reference unknown models: {missing_allowed!r}"
                )
                variant_valid = False
            if not set(required_models).issubset(set(allowed_models)):
                errors.append(
                    f"accepted_diagnoses[{idx}] required_models must be a subset of allowed_models"
                )
                variant_valid = False
            if not _is_claim_pattern(variant.get("root_cause_all_of")):
                errors.append(
                    f"accepted_diagnoses[{idx}].root_cause_all_of must be a non-empty claim pattern"
                )
                variant_valid = False
            fix_variants = variant.get("fix_variants")
            if not isinstance(fix_variants, list) or not fix_variants:
                errors.append(
                    f"accepted_diagnoses[{idx}].fix_variants must be a non-empty array"
                )
                variant_valid = False
            elif not all(_is_claim_pattern(pattern) for pattern in fix_variants):
                errors.append(
                    f"accepted_diagnoses[{idx}].fix_variants must contain only claim patterns"
                )
                variant_valid = False
            if variant_valid:
                valid_variants.append((idx, variant))
    forbidden_claims = hints.get("forbidden_claims", [])
    if data.get("has_bug") is False and not forbidden_claims:
        errors.append("no_bug scenarios should declare rubric_hints.forbidden_claims")
    valid_forbidden_claims: list[tuple[int, list[list[str]]]] = []
    if forbidden_claims and (
        not isinstance(forbidden_claims, list)
        or not all(_is_claim_pattern(pattern) for pattern in forbidden_claims)
    ):
        errors.append("rubric_hints.forbidden_claims must contain only claim patterns")
    elif isinstance(forbidden_claims, list):
        valid_forbidden_claims = [
            (idx, pattern)
            for idx, pattern in enumerate(forbidden_claims)
            if _is_claim_pattern(pattern)
        ]
    for accepted_idx, variant in valid_variants:
        for forbidden_idx, forbidden in valid_forbidden_claims:
            overlapping_phrases = _variant_overlaps_forbidden_claim(variant, forbidden)
            if overlapping_phrases:
                errors.append(
                    "accepted_diagnoses"
                    f"[{accepted_idx}] overlaps forbidden_claims[{forbidden_idx}] "
                    "via accepted negated phrases: "
                    f"{overlapping_phrases!r}"
                )
    _validate_required_evidence(data, errors)


def _validate_one(path: Path, data: dict[str, Any]) -> list[str]:
    """Return a list of error strings for a single scenario file."""
    errors: list[str] = []
    stem = path.stem
    sid = data.get("scenario_id")
    if sid != stem:
        errors.append(f"scenario_id {sid!r} must match filename stem {stem!r}")

    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    cats = data.get("failure_categories", [])
    if not isinstance(cats, list) or not cats:
        errors.append("failure_categories must be a non-empty array")

    has_bug = data.get("has_bug")
    if has_bug is False:
        if "no_bug" not in cats:
            errors.append(
                "has_bug false requires failure_categories to include 'no_bug'"
            )
        rc = str(data.get("ground_truth", {}).get("root_cause", ""))
        if not rc.startswith("No bug"):
            errors.append(
                "ground_truth.root_cause must start with 'No bug' when has_bug is false"
            )

    dag_models = data.get("dag", {}).get("models", [])
    model_names = {m["name"] for m in dag_models if isinstance(m, dict) and "name" in m}
    file_paths = _project_file_paths(data)

    for m in dag_models:
        if not isinstance(m, dict):
            continue
        p = m.get("path")
        if p not in file_paths:
            errors.append(f"dag model path not in dbt_project.files: {p!r}")

    gt_models = data.get("ground_truth", {}).get("affected_models", [])
    for name in gt_models:
        if name not in model_names:
            errors.append(
                f"ground_truth.affected_models references unknown model: {name!r}"
            )

    if has_bug is False and gt_models:
        errors.append(
            "ground_truth.affected_models should be empty when has_bug is false"
        )

    imm = data.get("artifact_manifest", {}).get("immutable_paths", [])
    for p in imm:
        if p not in file_paths:
            errors.append(
                f"immutable_paths entry not found in dbt_project.files: {p!r}"
            )

    sample_data = data.get("sample_data", {})
    for table_key, table in sample_data.items():
        if not isinstance(table, dict):
            errors.append(f"sample_data.{table_key} must be an object")
            continue
        col_names = {c["name"] for c in table.get("columns", []) if isinstance(c, dict)}
        for i, row in enumerate(table.get("rows", [])):
            if not isinstance(row, dict):
                errors.append(f"sample_data.{table_key}.rows[{i}] must be an object")
                continue
            for k in row:
                if k not in col_names:
                    errors.append(
                        f"sample_data.{table_key}.rows[{i}] has unknown key {k!r} "
                        f"(not in columns)"
                    )

    content_blob = json.dumps(data)
    if "```" in content_blob:
        errors.append(
            "scenario JSON must not contain triple-backtick fences inside strings"
        )

    _validate_rubric_contract(data, errors)

    return errors


def _validate_corpus(_paths: list[Path], payloads: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    category_counts = {cat: 0 for cat in REQUIRED_CATEGORIES}
    for data in payloads:
        for c in data.get("failure_categories", []):
            if c in category_counts:
                category_counts[c] += 1
    if len(payloads) < MIN_TOTAL_SCENARIOS:
        errors.append(
            f"corpus: need at least {MIN_TOTAL_SCENARIOS} scenarios; found {len(payloads)}"
        )
    for category in REQUIRED_CATEGORIES:
        if category_counts[category] < 1:
            errors.append(f"corpus: no scenario tagged with {category}")
    no_bug_count = sum(1 for data in payloads if data.get("has_bug") is False)
    if no_bug_count < MIN_NO_BUG_SCENARIOS:
        errors.append(
            f"corpus: need at least {MIN_NO_BUG_SCENARIOS} no_bug scenarios; found {no_bug_count}"
        )
    tier_counts = {
        tier: sum(1 for data in payloads if data.get("difficulty_tier") == tier)
        for tier in TARGET_TIER_COUNTS
    }
    for tier, target in TARGET_TIER_COUNTS.items():
        if tier_counts[tier] < target:
            errors.append(
                f"corpus: need at least {target} tier {tier} scenarios; found {tier_counts[tier]}"
            )
    if not any(set(data.get("failure_categories", [])) == {"logic"} for data in payloads):
        errors.append("corpus: need at least one pure logic scenario")
    if not any(set(data.get("failure_categories", [])) == {"config"} for data in payloads):
        errors.append("corpus: need at least one pure config scenario")

    return errors


def main() -> int:
    gold = _scenario_dir()
    if not gold.is_dir():
        print(f"Missing gold directory: {gold}", file=sys.stderr)
        return 2

    json_files = sorted(gold.glob("*.json"))
    if not json_files:
        print(f"No JSON scenarios under {gold}", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    payloads: list[dict[str, Any]] = []
    for path in json_files:
        try:
            data = _load_json(path)
        except json.JSONDecodeError as exc:
            all_errors.append(f"{path.name}: invalid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            all_errors.append(f"{path.name}: root must be an object")
            continue
        payloads.append(data)
        for msg in _validate_one(path, data):
            all_errors.append(f"{path.name}: {msg}")

    for msg in _validate_corpus(json_files, payloads):
        all_errors.append(msg)

    if all_errors:
        print("Validation failed:", file=sys.stderr)
        for line in all_errors:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"OK: {len(json_files)} scenario(s) in {gold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
