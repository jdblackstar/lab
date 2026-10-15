"""Bundled gold scenario corpus: loading and the model-facing prompt."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

GOLD_DIR = Path(__file__).resolve().parent / "scenarios" / "gold"


def gold_paths() -> list[Path]:
    """Return sorted paths to bundled gold scenario JSON files."""
    return sorted(GOLD_DIR.glob("*.json"))


@cache
def load_scenario_spec(scenario_id: str) -> dict[str, Any]:
    """Return one gold scenario by id. The cached dict is shared; do not mutate it."""
    path = GOLD_DIR / f"{scenario_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"No scenario file for scenario_id={scenario_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def model_names(spec: dict[str, Any]) -> list[str]:
    """Return the DAG model names a diagnosis may cite."""
    models = spec["dag"]["models"]
    names = [str(m["name"]) for m in models if isinstance(m, dict) and "name" in m]
    if len(names) != len(models):
        raise ValueError(f"{spec['scenario_id']}: every dag model needs a name")
    return names


def build_prompt(spec: dict[str, Any]) -> str:
    """Return the user prompt for one scenario (no ground truth in it)."""
    message = str(spec["symptom"]["message"])
    return (
        "You are a senior analytics engineer debugging a dbt project in a local sandbox.\n"
        "You have tools to inspect project files, explore supporting debug context, run "
        "bounded dbt commands, read build artifacts under target/, and submit a structured "
        "diagnosis.\n"
        "Start by exploring the workspace with the tools rather than assuming where the "
        "issue lives.\n"
        "As you investigate, store evidence with the dedicated evidence tools:\n"
        "- add_file_evidence(path, start_line, end_line) for project SQL/YAML files\n"
        "- add_sample_rows_evidence(table, match_json, min_rows) for facts from "
        "debug_context/sample_data.json\n"
        "- add_run_history_evidence(...) for facts from debug_context/run_history.json\n"
        "- list_collected_evidence() if you want to review what is stored so far\n"
        "When you are ready, call submit_diagnosis with: has_bug (whether the dbt project "
        "has a defect), root_cause, buggy_models (models that must change to fix a real bug; "
        'use an empty list when has_bug is false), and fix (or "No fix needed — ..." when '
        "there is no dbt bug). submit_diagnosis uses the evidence you already collected.\n"
        "If an evidence tool or submit_diagnosis returns an error, correct the payload and "
        "try again.\n\n"
        f"Stakeholder report:\n{message}\n"
    )
