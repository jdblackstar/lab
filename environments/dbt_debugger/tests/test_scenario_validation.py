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


def _validation_errors(name: str, spec: dict[str, Any] | None = None) -> list[str]:
    """Return validator errors for one gold scenario or mutated copy."""
    scenario_spec = _spec(name) if spec is None else spec
    return _validate_one(_scenario_path(name), scenario_spec)


def test_campaign_replay_scenario_passes_validation() -> None:
    """The cleaned campaign replay scenario should pass single-file validation."""
    errors = _validation_errors("campaign_spend_replay_restatement")
    assert errors == []


def test_validator_defaults_missing_allowed_models_to_required_models() -> None:
    """Missing allowed_models should inherit required_models during validation."""
    spec = deepcopy(_spec("join_fanout_exec_revenue"))
    variant = spec["rubric_hints"]["accepted_diagnoses"][0]
    variant["required_models"] = ["int_order_lines"]
    variant.pop("allowed_models", None)
    spec["ground_truth"]["affected_models"] = ["int_order_lines"]
    spec["ground_truth"]["fix"] = (
        "Deduplicate or pre-aggregate promos so int_order_lines stays one row per "
        "order before downstream sums run."
    )

    errors = _validation_errors("join_fanout_exec_revenue", spec)

    assert errors == []


def test_validator_enforces_schema_for_unknown_category_and_extra_property() -> None:
    """Schema validation should catch enum drift and unexpected top-level fields."""
    spec = deepcopy(_spec("join_fanout_exec_revenue"))
    spec["failure_categories"].append("bogus_category")
    spec["unexpected_top_level"] = "surprise"

    errors = _validation_errors("join_fanout_exec_revenue", spec)

    assert any("schema failure_categories" in error for error in errors)
    assert any(
        "schema:" in error and "unexpected_top_level" in error for error in errors
    )


def test_validator_requires_empty_ground_truth_models_for_no_bug() -> None:
    """No-bug scenarios must keep ground_truth.affected_models empty for the gold answer."""
    spec = deepcopy(_spec("no_bug_fiscal_vs_calendar"))
    spec["ground_truth"]["affected_models"] = ["fct_revenue_daily"]
    errors = _validation_errors("no_bug_fiscal_vs_calendar", spec)
    assert any(
        "affected_models should be empty when has_bug is false" in err for err in errors
    )


def test_validator_rejects_negated_accepted_phrase_overlap() -> None:
    """Accepted negated phrases must not be able to satisfy forbidden claims."""
    spec = deepcopy(_spec("campaign_spend_replay_restatement"))
    spec["rubric_hints"]["accepted_diagnoses"][0]["root_cause_all_of"][3] = [
        "not duplicated",
        "no duplication",
        "no dbt bug",
        "no warehouse bug",
    ]
    errors = _validation_errors("campaign_spend_replay_restatement", spec)
    assert any("overlaps forbidden_claims[0]" in error for error in errors)
    assert any("no dbt bug" in error and "not duplicated" in error for error in errors)


def test_validator_rejects_unsatisfiable_required_evidence_anchor() -> None:
    """Required evidence should point at text that actually exists in artifacts."""
    spec = deepcopy(_spec("join_fanout_exec_revenue"))
    spec["rubric_hints"]["required_evidence"][0]["all_of"] = [
        "definitely_missing_anchor_xyz"
    ]

    errors = _validation_errors("join_fanout_exec_revenue", spec)

    assert any(
        "file_span anchors not found" in error and "definitely_missing_anchor_xyz" in error
        for error in errors
    )


def test_validator_rejects_ground_truth_drift_from_scored_contract() -> None:
    """The documented gold answer should satisfy the accepted diagnosis contract."""
    spec = deepcopy(_spec("join_fanout_exec_revenue"))
    spec["ground_truth"]["root_cause"] = "The mart is broken for unclear reasons."
    spec["ground_truth"]["fix"] = "Rewrite everything."

    errors = _validation_errors("join_fanout_exec_revenue", spec)

    assert any(
        "ground_truth root_cause/fix/affected_models do not satisfy" in error
        for error in errors
    )
