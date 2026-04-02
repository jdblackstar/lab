"""Validate gold scenario JSON files against schema and corpus rules.

Run from repo root or this directory:

    uv run python validation/validate_scenarios.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_CATEGORIES = frozenset(
    {"join", "incremental", "source_schema", "logic", "macro", "config", "no_bug"}
)


def _scenario_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "scenarios" / "gold"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    file_paths = {f["path"] for f in data.get("dbt_project", {}).get("files", [])}

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

    return errors


def _validate_corpus(paths: list[Path], payloads: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    covered: set[str] = set()
    for data in payloads:
        for c in data.get("failure_categories", []):
            covered.add(c)
    if "join" not in covered:
        errors.append("corpus: no scenario tagged with join")
    if "incremental" not in covered:
        errors.append("corpus: no scenario tagged with incremental")
    if "source_schema" not in covered:
        errors.append("corpus: no scenario tagged with source_schema")
    if "logic" not in covered:
        errors.append("corpus: no scenario tagged with logic")
    if not ({"macro", "config"} & covered):
        errors.append("corpus: need at least one scenario tagged macro or config")
    if "no_bug" not in covered:
        errors.append("corpus: no scenario tagged with no_bug")

    tiers = [d.get("difficulty_tier") for d in payloads]
    if not any(isinstance(t, int) and t >= 3 for t in tiers):
        errors.append(
            "corpus: recommend at least one scenario with difficulty_tier >= 3"
        )

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
        all_errors.append(f"corpus: {msg}")

    if all_errors:
        print("Validation failed:", file=sys.stderr)
        for line in all_errors:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"OK: {len(json_files)} scenario(s) in {gold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
