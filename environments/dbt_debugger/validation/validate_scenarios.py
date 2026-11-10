"""Validate gold scenario JSON files against schema and corpus rules.

Run from repo root or this directory:

    uv run python validation/validate_scenarios.py

Each file is checked against ``scenario.schema.json`` first; the checks below assume
the schema passed and only verify what a schema cannot: cross-references between
sections, that every ``required_evidence`` entry is satisfiable by the bundled
artifacts, and that the documented ground truth passes the scored contract.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from dbt_debugger.claim_text_matching import claim_group_matches, option_is_negated_phrase
from dbt_debugger.evidence import (
    entry_matches,
    missing_anchors,
    project_files,
    run_history_entries,
)
from dbt_debugger.rubric import ClaimPattern, DiagnosisVariant, Rubric
from dbt_debugger.sample_rows import matching_sample_rows
from dbt_debugger.scenarios import GOLD_DIR

REQUIRED_CATEGORIES = frozenset(
    {"join", "incremental", "source_schema", "logic", "macro", "config", "no_bug"}
)
TARGET_TIER_COUNTS = {1: 2, 2: 3, 3: 3, 4: 2}
MIN_TOTAL_SCENARIOS = 10
MIN_NO_BUG_SCENARIOS = 4


def _schema_path() -> Path:
    return Path(__file__).resolve().parent / "scenario.schema.json"


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _format_schema_error(error: ValidationError) -> str:
    location = ".".join(str(part) for part in error.absolute_path)
    return f"schema {location}: {error.message}" if location else f"schema: {error.message}"


def _schema_errors(data: dict[str, Any]) -> list[str]:
    errors = sorted(
        _schema_validator().iter_errors(data),
        key=lambda error: (
            ".".join(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    return [_format_schema_error(error) for error in errors]


# -- rubric contract -----------------------------------------------------------------


def _negated_options(pattern: ClaimPattern, source: str) -> list[tuple[str, str]]:
    """Return ``(source, option)`` for each accepted option that is itself a negation."""
    return [
        (source, option)
        for option in pattern.options
        if option_is_negated_phrase(option)
    ]


def _variant_overlaps_forbidden_claim(
    variant: DiagnosisVariant, forbidden: ClaimPattern
) -> list[str]:
    """Return accepted negated phrases that together satisfy every group in *forbidden*.

    Scoring exempts accepted negated phrases ("no dbt bug") from forbidden-claim
    matching, so an accepted phrase that also spells out a forbidden claim would make
    that forbidden claim unenforceable.
    """
    root_options = _negated_options(variant.root_cause, "root_cause_all_of")
    for idx, fix in enumerate(variant.fix_variants):
        phrases = root_options + _negated_options(fix, f"fix_variants[{idx}]")
        matched: set[str] = set()
        for group in forbidden.groups:
            hits = {
                f"{source}: {option}"
                for source, option in phrases
                if claim_group_matches(option, group)
            }
            if not hits:
                break
            matched.update(hits)
        else:
            return sorted(matched)
    return []


def _validate_rubric_contract(
    data: dict[str, Any], rubric: Rubric, errors: list[str]
) -> None:
    """Accepted diagnoses must name real models; accepted negations must not be able
    to satisfy a forbidden claim; no-bug scenarios must forbid something."""
    model_names = {model["name"] for model in data["dag"]["models"]}
    for idx, variant in enumerate(rubric.accepted_diagnoses):
        unknown_required = sorted(variant.required_models - model_names)
        if unknown_required:
            errors.append(
                f"accepted_diagnoses[{idx}] required_models reference unknown models: "
                f"{unknown_required!r}"
            )
        unknown_allowed = sorted(variant.allowed_models - model_names)
        if unknown_allowed:
            errors.append(
                f"accepted_diagnoses[{idx}] allowed_models reference unknown models: "
                f"{unknown_allowed!r}"
            )
        if not variant.required_models <= variant.allowed_models:
            errors.append(
                f"accepted_diagnoses[{idx}] required_models must be a subset of "
                "allowed_models"
            )
        for forbidden_idx, forbidden in enumerate(rubric.forbidden_claims):
            overlap = _variant_overlaps_forbidden_claim(variant, forbidden)
            if overlap:
                errors.append(
                    f"accepted_diagnoses[{idx}] overlaps forbidden_claims"
                    f"[{forbidden_idx}] via accepted negated phrases: {overlap!r}"
                )
    if data["has_bug"] is False and not rubric.forbidden_claims:
        errors.append("no_bug scenarios should declare rubric_hints.forbidden_claims")


# -- required evidence ---------------------------------------------------------------


def _file_span_error(
    requirement: dict[str, Any], files: dict[str, str]
) -> str | None:
    path = requirement["path"]
    if path not in files:
        return f"file_span path not found in project files: {path!r}"
    missing = missing_anchors(files[path], requirement["all_of"])
    if missing:
        return f"file_span anchors not found in {path!r}: {missing!r}"
    return None


def _sample_rows_error(
    requirement: dict[str, Any], sample_data: dict[str, Any]
) -> str | None:
    table, match = requirement["table"], requirement["match"]
    if table not in sample_data:
        return f"sample_rows table not found in sample_data: {table!r}"
    rows = matching_sample_rows(sample_data[table], match)
    if not rows:
        return f"sample_rows match selects 0 rows in {table!r}: {match!r}"
    min_rows = requirement.get("min_rows", 1)
    if len(rows) < min_rows:
        return (
            f"sample_rows match selects {len(rows)} row(s) in {table!r}, fewer than "
            f"min_rows={min_rows}"
        )
    missing = missing_anchors(json.dumps(rows, sort_keys=True), requirement["all_of"])
    if missing:
        return f"sample_rows anchors not found in matched rows for {table!r}: {missing!r}"
    return None


def _run_history_error(
    requirement: dict[str, Any], run_history: dict[str, Any], model_names: set[str]
) -> str | None:
    record_type = requirement["record_type"]
    if record_type == "model" and requirement.get("model") not in model_names:
        return (
            "run_history model must reference dag.models: "
            f"{requirement.get('model')!r}"
        )
    if record_type == "test" and not requirement.get("name", "").strip():
        return "run_history test evidence requires name"
    if record_type in ("summary", "warning") and not requirement.get("contains", "").strip():
        return f"run_history {record_type} evidence requires contains"
    entries = run_history_entries(record_type, run_history)
    if any(entry_matches(entry, requirement) for entry in entries):
        return None
    filters = {
        key: value
        for key, value in requirement.items()
        if key not in ("kind", "record_type") and str(value).strip()
    }
    return f"run_history {record_type} requirement is not satisfiable: {filters!r}"


def _validate_required_evidence(
    data: dict[str, Any], rubric: Rubric, errors: list[str]
) -> None:
    """Every ``required_evidence`` entry must be citable from the bundled artifacts."""
    files = project_files(data)
    model_names = {model["name"] for model in data["dag"]["models"]}
    for idx, requirement in enumerate(rubric.required_evidence):
        kind = requirement["kind"]
        if kind == "file_span":
            error = _file_span_error(requirement, files)
        elif kind == "sample_rows":
            error = _sample_rows_error(requirement, data["sample_data"])
        else:
            error = _run_history_error(requirement, data["run_history"], model_names)
        if error is not None:
            errors.append(f"required_evidence[{idx}] {error}")


# -- ground truth --------------------------------------------------------------------


def _validate_ground_truth_alignment(
    data: dict[str, Any], rubric: Rubric, errors: list[str]
) -> None:
    """The documented gold answer must pass the scored diagnosis contract."""
    truth = data["ground_truth"]
    results = [
        variant.evaluate(
            buggy_models=list(truth["affected_models"]),
            root_cause=truth["root_cause"],
            fix=truth["fix"],
        )
        for variant in rubric.accepted_diagnoses
    ]
    if not any(result.models_ok for result in results):
        errors.append(
            "ground_truth.affected_models do not satisfy any accepted_diagnoses "
            "model contract"
        )
    if not any(result.ok for result in results):
        errors.append(
            "ground_truth root_cause/fix/affected_models do not satisfy any "
            "accepted_diagnoses variant"
        )


# -- one scenario --------------------------------------------------------------------


def _validate_one(path: Path, data: dict[str, Any]) -> list[str]:
    """Return a list of error strings for a single scenario file."""
    errors = _schema_errors(data)
    if errors:
        return errors

    if data["scenario_id"] != path.stem:
        errors.append(
            f"scenario_id {data['scenario_id']!r} must match filename stem {path.stem!r}"
        )

    has_bug = data["has_bug"]
    truth = data["ground_truth"]
    if has_bug is False:
        if "no_bug" not in data["failure_categories"]:
            errors.append(
                "has_bug false requires failure_categories to include 'no_bug'"
            )
        if not truth["root_cause"].startswith("No bug"):
            errors.append(
                "ground_truth.root_cause must start with 'No bug' when has_bug is false"
            )
        if truth["affected_models"]:
            errors.append(
                "ground_truth.affected_models should be empty when has_bug is false"
            )

    file_paths = set(project_files(data))
    model_names = {model["name"] for model in data["dag"]["models"]}
    for model in data["dag"]["models"]:
        if model["path"] not in file_paths:
            errors.append(f"dag model path not in dbt_project.files: {model['path']!r}")
    for name in truth["affected_models"]:
        if name not in model_names:
            errors.append(
                f"ground_truth.affected_models references unknown model: {name!r}"
            )
    for immutable in data["artifact_manifest"]["immutable_paths"]:
        if immutable not in file_paths:
            errors.append(
                f"immutable_paths entry not found in dbt_project.files: {immutable!r}"
            )

    for table_key, table in data["sample_data"].items():
        columns = {column["name"] for column in table["columns"]}
        for i, row in enumerate(table["rows"]):
            for key in row:
                if key not in columns:
                    errors.append(
                        f"sample_data.{table_key}.rows[{i}] has unknown key {key!r} "
                        "(not in columns)"
                    )

    if "```" in json.dumps(data):
        errors.append(
            "scenario JSON must not contain triple-backtick fences inside strings"
        )

    rubric = Rubric.from_spec(data)
    _validate_rubric_contract(data, rubric, errors)
    _validate_required_evidence(data, rubric, errors)
    _validate_ground_truth_alignment(data, rubric, errors)
    return errors


# -- the corpus ----------------------------------------------------------------------


def _validate_corpus(payloads: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    categories = [set(data["failure_categories"]) for data in payloads]
    if len(payloads) < MIN_TOTAL_SCENARIOS:
        errors.append(
            f"corpus: need at least {MIN_TOTAL_SCENARIOS} scenarios; found {len(payloads)}"
        )
    for category in sorted(REQUIRED_CATEGORIES):
        if not any(category in cats for cats in categories):
            errors.append(f"corpus: no scenario tagged with {category}")
    no_bug_count = sum(1 for data in payloads if data["has_bug"] is False)
    if no_bug_count < MIN_NO_BUG_SCENARIOS:
        errors.append(
            f"corpus: need at least {MIN_NO_BUG_SCENARIOS} no_bug scenarios; "
            f"found {no_bug_count}"
        )
    for tier, target in TARGET_TIER_COUNTS.items():
        count = sum(1 for data in payloads if data["difficulty_tier"] == tier)
        if count < target:
            errors.append(
                f"corpus: need at least {target} tier {tier} scenarios; found {count}"
            )
    for pure in ("logic", "config"):
        if {pure} not in categories:
            errors.append(f"corpus: need at least one pure {pure} scenario")
    return errors


def main() -> int:
    if not GOLD_DIR.is_dir():
        print(f"Missing gold directory: {GOLD_DIR}", file=sys.stderr)
        return 2
    json_files = sorted(GOLD_DIR.glob("*.json"))
    if not json_files:
        print(f"No JSON scenarios under {GOLD_DIR}", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    payloads: list[dict[str, Any]] = []
    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            all_errors.append(f"{path.name}: invalid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            all_errors.append(f"{path.name}: root must be an object")
            continue
        errors = _validate_one(path, data)
        all_errors.extend(f"{path.name}: {msg}" for msg in errors)
        if not errors:
            payloads.append(data)
    all_errors.extend(_validate_corpus(payloads))

    if all_errors:
        print("Validation failed:", file=sys.stderr)
        for line in all_errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"OK: {len(json_files)} scenario(s) in {GOLD_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
