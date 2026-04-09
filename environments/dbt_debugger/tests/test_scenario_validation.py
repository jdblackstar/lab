"""Focused tests for scenario validation guardrails."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from validation.validate_scenarios import _validate_one

_ROOT = Path(__file__).resolve().parent.parent


def _scenario_path(name: str) -> Path:
    """Return the gold scenario path for one scenario id."""
    return _ROOT / "scenarios" / "gold" / f"{name}.json"


def _spec(name: str) -> dict[str, Any]:
    """Return one gold scenario payload by scenario id."""
    return json.loads(_scenario_path(name).read_text(encoding="utf-8"))


def test_campaign_replay_scenario_passes_validation() -> None:
    """The cleaned campaign replay scenario should pass single-file validation."""
    errors = _validate_one(
        _scenario_path("campaign_spend_replay_restatement"),
        _spec("campaign_spend_replay_restatement"),
    )
    assert errors == []


def test_validator_rejects_negated_accepted_phrase_overlap() -> None:
    """Accepted negated phrases must not be able to satisfy forbidden claims."""
    spec = deepcopy(_spec("campaign_spend_replay_restatement"))
    spec["rubric_hints"]["accepted_diagnoses"][0]["root_cause_all_of"][3] = [
        "not duplicated",
        "no duplication",
        "no dbt bug",
        "no warehouse bug",
    ]
    errors = _validate_one(_scenario_path("campaign_spend_replay_restatement"), spec)
    assert any("overlaps forbidden_claims[0]" in error for error in errors)
    assert any("no dbt bug" in error and "not duplicated" in error for error in errors)
