"""Focused tests for dbt-debugger workspace, tools guardrails, and scoring."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from datasets import Dataset

from runtime.sample_rows import matching_sample_rows
from runtime.scoring import score_diagnosis
from runtime.tools import (
    add_file_evidence,
    add_run_history_evidence,
    add_sample_rows_evidence,
    dbt_argv,
    _normalize_rel_path,
    list_files,
    list_collected_evidence,
    _path_matches_globs,
    run_dbt_command,
    submit_diagnosis,
)
from runtime.types import RolloutStateKeys
from runtime.workspace import cleanup_workspace, materialize_scenario_workspace

_ROOT = Path(__file__).resolve().parent.parent


def _spec(name: str) -> dict[str, Any]:
    """Return one gold scenario payload by scenario id."""
    path = _ROOT / "scenarios" / "gold" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _all_specs() -> list[dict[str, Any]]:
    """Return all bundled gold scenario payloads."""
    scenario_dir = _ROOT / "scenarios" / "gold"
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(scenario_dir.glob("*.json"))
    ]


def _scenario_ids() -> list[str]:
    """Return sorted bundled scenario ids."""
    return [spec["scenario_id"] for spec in _all_specs()]


def _file_span_evidence(path: str, start_line: int, end_line: int) -> dict[str, Any]:
    """Build one file-span evidence payload for scorer tests."""
    return {
        "kind": "file_span",
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
    }


def _sample_rows_evidence(table: str, match_json: str, min_rows: int) -> dict[str, Any]:
    """Build one sample-rows evidence payload for scorer tests."""
    return {
        "kind": "sample_rows",
        "table": table,
        "match_json": match_json,
        "min_rows": min_rows,
    }


def _run_history_summary_evidence(contains: str) -> dict[str, Any]:
    """Build one run-history summary evidence payload for scorer tests."""
    return {
        "kind": "run_history",
        "record_type": "summary",
        "contains": contains,
    }


def _fiscal_no_bug_evidence() -> list[dict[str, Any]]:
    """Return the canonical evidence set for fiscal-vs-calendar tests."""
    return [
        _file_span_evidence("models/marts/fct_revenue_daily.sql", 1, 4),
        _run_history_summary_evidence("All models succeeded"),
    ]


def _campaign_replay_evidence() -> list[dict[str, Any]]:
    """Return the canonical evidence set for campaign replay tests."""
    return [
        _run_history_summary_evidence("vendor replay"),
        _sample_rows_evidence(
            "ads_campaign_spend",
            json.dumps({"load_batch": "vendor_replay_2026_03_30"}),
            2,
        ),
        _file_span_evidence("models/marts/fct_campaign_spend_daily.sql", 1, 6),
    ]


def _fiscal_no_bug_submission(
    root_cause: str,
    fix: str,
    *,
    buggy_models: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one fiscal-vs-calendar submission for scorer tests."""
    return {
        "has_bug": False,
        "root_cause": root_cause,
        "buggy_models": [] if buggy_models is None else buggy_models,
        "fix": fix,
        "evidence": _fiscal_no_bug_evidence() if evidence is None else evidence,
    }


def _campaign_replay_submission(root_cause: str, fix: str) -> dict[str, Any]:
    """Build one campaign replay submission for scorer tests."""
    return {
        "has_bug": False,
        "root_cause": root_cause,
        "buggy_models": [],
        "fix": fix,
        "evidence": _campaign_replay_evidence(),
    }


def _finalized_bookings_submission(root_cause: str, fix: str) -> dict[str, Any]:
    """Build one finalized-bookings submission for scorer tests."""
    return {
        "has_bug": False,
        "root_cause": root_cause,
        "buggy_models": [],
        "fix": fix,
        "evidence": [
            _file_span_evidence("models/marts/fct_daily_bookings.sql", 1, 7),
            _sample_rows_evidence("crm_bookings", '{"booking_date": "2026-03-30"}', 3),
        ],
    }


def _submission_state(has_bug: bool) -> dict[str, Any]:
    """Return minimal rollout state for submit_diagnosis unit tests."""
    return {
        RolloutStateKeys.SCENARIO_SPEC: {"has_bug": has_bug},
        RolloutStateKeys.COLLECTED_EVIDENCE: [],
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }


def _submit_for_test(
    state: dict[str, Any],
    *,
    has_bug: bool,
    root_cause: str,
    buggy_models: list[str],
    fix: str,
    scenario_id: str = "secret-scenario",
    valid_model_names: list[str] | None = None,
) -> str:
    """Run ``submit_diagnosis`` synchronously inside unit tests."""

    async def _run() -> str:
        return await submit_diagnosis(
            has_bug,
            root_cause,
            buggy_models,
            fix,
            scenario_id=scenario_id,
            valid_model_names=valid_model_names,
            rollout_state=state,
        )

    return asyncio.run(_run())


def _seed_evidence(
    state: dict[str, Any],
    *evidence_refs: dict[str, Any],
) -> None:
    """Replace the rollout's collected evidence with normalized refs."""
    state[RolloutStateKeys.COLLECTED_EVIDENCE] = [dict(ref) for ref in evidence_refs]


def test_normalize_rel_path_rejects_parent() -> None:
    with pytest.raises(ValueError, match=r"\.\."):
        _normalize_rel_path("../etc/passwd")


def test_path_matches_globs_handles_recursive_patterns() -> None:
    assert _path_matches_globs("models/staging/x.sql", ["models/**", "dbt_project.yml"])
    assert _path_matches_globs("dbt_project.yml", ["models/**", "dbt_project.yml"])
    assert _path_matches_globs("models/a/b/test.sql", ["models/**/*.sql"])
    assert not _path_matches_globs("secrets.env", ["models/**"])
    assert not _path_matches_globs("secrets.env", ["**/*.sql"])
    assert not _path_matches_globs("models/schema.yml", ["models/**/*.sql"])


def test_matching_sample_rows_skips_non_dict_rows_and_matches_all_pairs() -> None:
    """Sample-row evidence should use one shared exact-match interpretation."""
    table = {
        "rows": [
            {"order_id": 1001, "status": "paid", "amount": 10},
            ["not", "a", "row"],
            {"order_id": 1001, "status": "pending", "amount": 12},
            {"order_id": 1002, "status": "paid", "amount": 8},
        ]
    }

    rows = matching_sample_rows(table, {"order_id": 1001, "status": "paid"})

    assert rows == [{"order_id": 1001, "status": "paid", "amount": 10}]


@pytest.mark.parametrize("scenario_id", _scenario_ids())
def test_materialize_scenario_and_dbt_compile(scenario_id: str) -> None:
    spec = _spec(scenario_id)
    workspace = materialize_scenario_workspace(spec)
    try:
        assert (workspace.project_root / "dbt_project.yml").is_file()
        assert (workspace.context_root / "sample_data.json").is_file()
        assert (workspace.context_root / "run_history.json").is_file()
        assert not (workspace.context_root / "dag.json").exists()
        env = os.environ.copy()
        env["DBT_PROFILES_DIR"] = str(workspace.profiles_dir)
        result = subprocess.run(
            dbt_argv(str(workspace.project_root), ["compile"]),
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        cleanup_workspace(workspace.workspace_root)


def test_score_join_paraphrase_submission_strict_pass() -> None:
    spec = _spec("join_fanout_exec_revenue")
    submission = {
        "has_bug": True,
        "root_cause": (
            "int_order_lines has a join fanout because order_promos can contribute "
            "multiple promo rows per order, which duplicates revenue downstream."
        ),
        "buggy_models": ["int_order_lines", "fct_daily_revenue"],
        "fix": (
            "Deduplicate or pre-aggregate promos so the join is one row per order "
            "before fct_daily_revenue sums amount."
        ),
        "evidence": [
            _file_span_evidence("models/intermediate/int_order_lines.sql", 1, 14),
            _sample_rows_evidence("raw_order_promos", '{"order_id": 1001}', 2),
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["strict_pass"] == 1.0


def test_missing_allowed_models_defaults_to_required_models_for_scoring() -> None:
    """Scoring should treat omitted allowed_models as exactly the required set."""
    spec = deepcopy(_spec("join_fanout_exec_revenue"))
    variant = spec["rubric_hints"]["accepted_diagnoses"][0]
    variant["required_models"] = ["int_order_lines"]
    variant.pop("allowed_models", None)

    base_submission = {
        "has_bug": True,
        "root_cause": (
            "int_order_lines has a join fanout because order_promos can contribute "
            "multiple promo rows per order, which duplicates revenue downstream."
        ),
        "buggy_models": ["int_order_lines"],
        "fix": (
            "Deduplicate or pre-aggregate promos so the join is one row per order "
            "before downstream sums run."
        ),
        "evidence": [
            _file_span_evidence("models/intermediate/int_order_lines.sql", 1, 14),
            _sample_rows_evidence("raw_order_promos", '{"order_id": 1001}', 2),
        ],
    }

    base_audit = score_diagnosis(base_submission, spec)

    assert base_audit["buggy_models_match"] is True
    assert base_audit["diagnosis_variant_ok"] is True
    assert base_audit["strict_pass"] == 1.0

    expanded_submission = deepcopy(base_submission)
    expanded_submission["buggy_models"] = [
        "int_order_lines",
        "fct_daily_revenue",
    ]

    expanded_audit = score_diagnosis(expanded_submission, spec)

    assert expanded_audit["buggy_models_match"] is False
    assert expanded_audit["diagnosis_variant_ok"] is False
    assert expanded_audit["strict_pass"] == 0.0


def test_wrong_mechanism_with_right_models_fails() -> None:
    spec = _spec("join_fanout_exec_revenue")
    submission = {
        "has_bug": True,
        "root_cause": "int_order_lines is stale because an incremental cutoff skipped backfilled rows.",
        "buggy_models": ["int_order_lines", "fct_daily_revenue"],
        "fix": "Widen the incremental lookback window on int_order_lines.",
        "evidence": [
            _file_span_evidence("models/intermediate/int_order_lines.sql", 1, 14),
            _sample_rows_evidence("raw_order_promos", '{"order_id": 1001}', 2),
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["buggy_models_match"] is True
    assert audit["root_cause_ok"] is False
    assert audit["strict_pass"] == 0.0


def test_no_bug_submission_with_non_empty_buggy_models_fails_strict() -> None:
    """False alarms must submit has_bug=false with an empty buggy_models list."""
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = _fiscal_no_bug_submission(
        (
            "Both decks query fct_revenue_daily; the gap is fiscal QTD vs calendar QTD "
            "filters in BI, not warehouse logic."
        ),
        "Align dashboard filters; no dbt code change is required.",
        buggy_models=["fct_revenue_daily"],
    )
    audit = score_diagnosis(submission, spec)
    assert audit["buggy_models_match"] is False
    assert audit["strict_pass"] == 0.0


def test_wrong_sample_table_fails_required_evidence() -> None:
    spec = _spec("order_item_grain_count_gap")
    submission = {
        "has_bug": False,
        "root_cause": (
            "fct_merch_sales is item-grain; counting rows overstates orders when one order "
            "has multiple SKUs."
        ),
        "buggy_models": [],
        "fix": "Use count(distinct order_id) for order counts or build an order-grain mart.",
        "evidence": [
            {
                "kind": "file_span",
                "path": "models/marts/fct_merch_sales.sql",
                "start_line": 1,
                "end_line": 12,
            },
            {
                "kind": "sample_rows",
                "table": "commerce_orders",
                "match_json": '{"order_id": 2001}',
                "min_rows": 2,
            },
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["required_evidence_ok"] is False
    assert audit["strict_pass"] == 0.0


def test_no_bug_semantic_partial_metric_when_strict_fails() -> None:
    """Intermediate signal: understood no-bug label and safe language but incomplete rubric."""
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = _fiscal_no_bug_submission(
        "Dashboard filters differ; the mart itself is fine.",
        "Document fiscal vs calendar QTD in BI.",
    )
    audit = score_diagnosis(submission, spec)
    assert audit["has_bug_match"] is True
    assert audit["forbidden_ok"] is True
    assert audit["strict_pass"] == 0.0
    assert 0.0 < audit["no_bug_semantic_partial"] < 1.0


def test_no_bug_semantic_answer_passes_without_magic_phrase() -> None:
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = _fiscal_no_bug_submission(
        (
            "Both decks are querying the same mart; the discrepancy comes from fiscal "
            "QTD versus calendar QTD filters in BI rather than warehouse logic."
        ),
        (
            "Standardize the saved views or publish an explore with explicit date logic "
            "so the fiscal and calendar definitions are not mixed."
        ),
    )
    audit = score_diagnosis(submission, spec)
    assert audit["strict_pass"] == 1.0


def test_forbidden_claim_pattern_still_fails_on_rewording() -> None:
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = _fiscal_no_bug_submission(
        "The warehouse mart is definitely broken and is corrupting revenue.",
        "Rewrite fct_revenue_daily to fix the regression.",
    )
    audit = score_diagnosis(submission, spec)
    assert audit["forbidden_ok"] is False
    assert audit["strict_pass"] == 0.0


def test_negated_forbidden_root_cause_does_not_fail_strict_pass() -> None:
    """Locally negated forbidden root-cause claims must not fail no-bug submissions."""
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = _fiscal_no_bug_submission(
        (
            "The warehouse is not broken. Both dashboards query the same dbt mart, "
            "and nothing is wrong with the mart itself; the discrepancy comes from "
            "fiscal QTD versus calendar QTD filters in the saved view."
        ),
        (
            "Align and document the fiscal and calendar filters in BI so the same "
            "date logic is used."
        ),
    )
    audit = score_diagnosis(submission, spec)
    assert audit["diagnosis_variant_ok"] is True
    assert audit["forbidden_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_negated_forbidden_fix_does_not_fail_strict_pass() -> None:
    """Locally negated forbidden fix claims must not fail no-bug submissions."""
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = _fiscal_no_bug_submission(
        (
            "Both dashboards are querying the same dbt mart, and the discrepancy "
            "comes from fiscal QTD versus calendar QTD filters in BI rather than "
            "warehouse logic."
        ),
        (
            "Do not rewrite or rebuild fct_revenue_daily; align and document the "
            "fiscal and calendar filters in BI instead."
        ),
    )
    audit = score_diagnosis(submission, spec)
    assert audit["diagnosis_variant_ok"] is True
    assert audit["fix_ok"] is True
    assert audit["forbidden_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_finalized_bookings_no_bug_passes_without_dashboard_naming() -> None:
    """No-bug definition scenarios should not require stakeholder artifact wording."""
    spec = _spec("finalized_bookings_definition_gap")
    submission = _finalized_bookings_submission(
        (
            "There is no dbt defect here: the mart intentionally counts only finalized "
            "bookings, while the larger total includes provisional bookings outside the "
            "metric definition."
        ),
        (
            "Clarify the finalized-bookings definition or publish a separate provisional "
            "bookings metric."
        ),
    )
    audit = score_diagnosis(submission, spec)
    assert audit["root_cause_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_negated_accepted_root_cause_phrase_does_not_fail_strict_pass() -> None:
    """Accepted negated root-cause phrases must not trip forbidden claim patterns."""
    spec = deepcopy(_spec("campaign_spend_replay_restatement"))
    spec["rubric_hints"]["accepted_diagnoses"][0]["root_cause_all_of"][3] = [
        "not duplicated",
        "no duplication",
        "no dbt bug",
        "no warehouse bug",
    ]
    submission = _campaign_replay_submission(
        (
            "The vendor replay backfilled missing source rows, and the downstream "
            "full-refresh loaded them correctly. There was no dbt bug, and the "
            "historical spend was not duplicated."
        ),
        "No fix needed; communicate the replay restatement to stakeholders.",
    )
    audit = score_diagnosis(submission, spec)
    assert audit["root_cause_ok"] is True
    assert audit["forbidden_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_campaign_replay_no_bug_passes_without_refresh_mechanics_phrase() -> None:
    """Replay scenarios should not require refresh-process narration in root cause text."""
    spec = _spec("campaign_spend_replay_restatement")
    submission = _campaign_replay_submission(
        (
            "A vendor replay restated history by supplying legitimately missing source rows, "
            "so source truth changed and historical totals moved upward. There is no dbt bug."
        ),
        "Communicate the replay-driven restatement to stakeholders and annotate dashboards.",
    )
    audit = score_diagnosis(submission, spec)
    assert audit["root_cause_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_negated_accepted_fix_phrase_does_not_fail_strict_pass() -> None:
    """Accepted negated fix phrases must not trip forbidden claim patterns."""
    spec = _spec("campaign_spend_replay_restatement")
    submission = _campaign_replay_submission(
        (
            "A vendor replay supplied late source rows, and a clean downstream "
            "full-refresh loaded the updated source truth, so historical totals "
            "moved. The row keys remain distinct and dbt logic is correct."
        ),
        (
            "No warehouse rewrite of fct_campaign_spend_daily is needed; communicate "
            "the vendor replay restatement to stakeholders."
        ),
    )
    audit = score_diagnosis(submission, spec)
    assert audit["fix_ok"] is True
    assert audit["forbidden_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_add_file_evidence_rejects_debug_context_path_with_guidance() -> None:
    spec = _spec("join_fanout_exec_revenue")
    workspace = materialize_scenario_workspace(spec)
    state = {
        RolloutStateKeys.SCENARIO_SPEC: spec,
        RolloutStateKeys.COLLECTED_EVIDENCE: [],
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }
    try:

        async def _run() -> str:
            return await add_file_evidence(
                "debug_context/run_history.json",
                1,
                5,
                project_root=str(workspace.project_root),
                rollout_state=state,
            )

        message = asyncio.run(_run())
        assert "Use add_run_history_evidence" in message
        assert state[RolloutStateKeys.COLLECTED_EVIDENCE] == []
    finally:
        cleanup_workspace(workspace.workspace_root)


def test_add_sample_rows_evidence_stores_normalized_ref() -> None:
    spec = _spec("join_fanout_exec_revenue")
    state = {
        RolloutStateKeys.SCENARIO_SPEC: spec,
        RolloutStateKeys.COLLECTED_EVIDENCE: [],
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }

    async def _run() -> str:
        return await add_sample_rows_evidence(
            "raw_order_promos",
            '{"order_id": 1001}',
            2,
            rollout_state=state,
        )

    response = json.loads(asyncio.run(_run()))
    assert response["status"] == "accepted"
    assert response["matched_rows"] == 2
    assert state[RolloutStateKeys.COLLECTED_EVIDENCE] == [
        {
            "kind": "sample_rows",
            "table": "raw_order_promos",
            "match_json": '{"order_id": 1001}',
            "min_rows": 2,
        }
    ]


def test_add_run_history_evidence_stores_model_result_ref() -> None:
    spec = _spec("join_fanout_exec_revenue")
    state = {
        RolloutStateKeys.SCENARIO_SPEC: spec,
        RolloutStateKeys.COLLECTED_EVIDENCE: [],
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }

    async def _run() -> str:
        return await add_run_history_evidence(
            "model",
            model="int_order_lines",
            status="success",
            valid_model_names=["stg_orders", "stg_order_promos", "int_order_lines"],
            rollout_state=state,
        )

    response = json.loads(asyncio.run(_run()))
    assert response["status"] == "accepted"
    assert response["evidence"]["record_type"] == "model"
    assert state[RolloutStateKeys.COLLECTED_EVIDENCE] == [
        {
            "kind": "run_history",
            "record_type": "model",
            "model": "int_order_lines",
            "status": "success",
        }
    ]


def test_list_collected_evidence_returns_stored_refs() -> None:
    state = _submission_state(True)
    _seed_evidence(state, _file_span_evidence("models/model_a.sql", 1, 2))

    async def _run() -> str:
        return await list_collected_evidence(rollout_state=state)

    response = json.loads(asyncio.run(_run()))
    assert response["status"] == "ok"
    assert response["evidence_count"] == 1
    assert response["evidence"][0]["path"] == "models/model_a.sql"


def test_submit_diagnosis_does_not_branch_on_hidden_has_bug() -> None:
    state_bug = _submission_state(True)
    state_no_bug = _submission_state(False)
    seed = _file_span_evidence("models/model_a.sql", 1, 2)
    _seed_evidence(state_bug, seed)
    _seed_evidence(state_no_bug, seed)
    bug_response = _submit_for_test(
        state_bug,
        has_bug=True,
        root_cause="There is a bug in model_a.",
        buggy_models=["model_a"],
        fix="Fix model_a.",
        scenario_id="hidden",
        valid_model_names=["model_a"],
    )
    no_bug_response = _submit_for_test(
        state_no_bug,
        has_bug=True,
        root_cause="There is a bug in model_a.",
        buggy_models=["model_a"],
        fix="Fix model_a.",
        scenario_id="hidden",
        valid_model_names=["model_a"],
    )
    assert bug_response == no_bug_response
    assert (
        state_bug[RolloutStateKeys.SUBMITTED_DIAGNOSIS]
        == state_no_bug[RolloutStateKeys.SUBMITTED_DIAGNOSIS]
    )


def test_submit_diagnosis_response_hides_internal_metadata() -> None:
    state = _submission_state(True)
    _seed_evidence(state, _file_span_evidence("models/model_a.sql", 1, 2))
    response = json.loads(
        _submit_for_test(
            state,
            has_bug=True,
            root_cause="model_a has a bug",
            buggy_models=["model_a"],
            fix="Fix model_a",
            valid_model_names=["model_a"],
        )
    )
    assert response == {
        "status": "accepted",
        "message": "Diagnosis stored for evaluator-only scoring.",
    }


def test_submit_diagnosis_requires_collected_evidence() -> None:
    state = _submission_state(True)
    message = _submit_for_test(
        state,
        has_bug=True,
        root_cause="model_a has a bug",
        buggy_models=["model_a"],
        fix="Fix model_a",
        valid_model_names=["model_a"],
    )
    assert "no evidence collected" in message
    assert state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] is None


def test_submit_diagnosis_rejects_second_submission() -> None:
    state = _submission_state(True)
    _seed_evidence(state, _file_span_evidence("models/model_a.sql", 1, 2))
    first = json.loads(
        _submit_for_test(
            state,
            has_bug=True,
            root_cause="first cause",
            buggy_models=["model_a"],
            fix="first fix",
            valid_model_names=["model_a"],
        )
    )
    second = _submit_for_test(
        state,
        has_bug=True,
        root_cause="second cause",
        buggy_models=["model_a"],
        fix="second fix",
        valid_model_names=["model_a"],
    )
    assert first["status"] == "accepted"
    assert "already submitted" in second
    assert state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] == {
        "has_bug": True,
        "root_cause": "first cause",
        "buggy_models": ["model_a"],
        "fix": "first fix",
        "evidence": [
            {
                "kind": "file_span",
                "path": "models/model_a.sql",
                "start_line": 1,
                "end_line": 2,
            }
        ],
    }


def test_submit_diagnosis_rejects_nonempty_buggy_models_when_has_bug_false() -> None:
    state = _submission_state(False)
    _seed_evidence(
        state,
        _file_span_evidence("models/marts/fct_revenue_daily.sql", 1, 4),
    )
    message = _submit_for_test(
        state,
        has_bug=False,
        root_cause="No dbt defect.",
        buggy_models=["fct_revenue_daily"],
        fix="No fix needed.",
        scenario_id="no_bug_fiscal_vs_calendar",
        valid_model_names=["fct_revenue_daily"],
    )
    assert "buggy_models must be empty" in message
    assert state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] is None


def test_submit_diagnosis_validation_rejects_unknown_model() -> None:
    state = _submission_state(True)
    _seed_evidence(state, _file_span_evidence("models/model_a.sql", 1, 2))
    message = _submit_for_test(
        state,
        has_bug=True,
        root_cause="x",
        buggy_models=["not_a_model"],
        fix="fix",
        scenario_id="join_fanout_exec_revenue",
        valid_model_names=["model_a"],
    )
    assert "Unknown model" in message
    assert state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] is None


def test_run_dbt_command_rejects_option_like_selector() -> None:
    spec = _spec("macro_var_discount_bug")
    workspace = materialize_scenario_workspace(spec)
    try:

        async def _run() -> str:
            return await run_dbt_command(
                subcommand="compile",
                select=["--vars"],
                project_root=str(workspace.project_root),
                profiles_dir=str(workspace.profiles_dir),
                duckdb_path=str(workspace.duckdb_path),
            )

        message = asyncio.run(_run())
        assert "selector values must not start with '-'" in message
    finally:
        cleanup_workspace(workspace.workspace_root)


def test_cleanup_workspace_refuses_unmarked_dir(tmp_path: Path) -> None:
    rogue_dir = tmp_path / "rogue"
    rogue_dir.mkdir()
    result = cleanup_workspace(rogue_dir)
    assert result.removed is False
    assert "Refusing to delete" in result.message


def test_cleanup_workspace_surfaces_rmtree_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runtime.workspace as workspace_mod

    spec = _spec("join_fanout_exec_revenue")
    workspace = materialize_scenario_workspace(spec)
    try:

        def _boom(path: Path) -> None:
            raise OSError("handle still open")

        monkeypatch.setattr(workspace_mod.shutil, "rmtree", _boom)
        result = cleanup_workspace(workspace.workspace_root)
        assert result.removed is False
        assert "handle still open" in result.message
    finally:
        monkeypatch.undo()
        cleanup_workspace(workspace.workspace_root)


def test_list_files_respects_globs() -> None:
    from runtime.env import _globs_for_list_and_search
    from runtime.tools import list_files

    spec = _spec("join_fanout_exec_revenue")
    workspace = materialize_scenario_workspace(spec)
    try:

        async def _run() -> str:
            return await list_files(
                ".",
                max_entries=50,
                project_root=str(workspace.project_root),
                tool_visible_globs=_globs_for_list_and_search(["models/**"]),
                immutable_paths=[],
            )

        output = asyncio.run(_run())
        assert "models/staging/stg_orders.sql" in output
        assert "debug_context/sample_data.json" in output
        assert "dbt_project.yml" not in output
    finally:
        cleanup_workspace(workspace.workspace_root)


def test_list_debug_context_via_env_globs() -> None:
    """Manifest-only globs still allow listing debug_context/."""
    from runtime.env import _globs_for_list_and_search

    merged = _globs_for_list_and_search(["models/**", "dbt_project.yml"])
    assert "debug_context/**" in merged


def test_explicit_empty_manifest_globs_do_not_expand_visibility() -> None:
    from runtime.env import DbtDebuggerEnv, build_rubric

    spec = _spec("join_fanout_exec_revenue")
    workspace = materialize_scenario_workspace(spec)
    env = DbtDebuggerEnv(
        dataset=Dataset.from_list([{"question": "stub", "answer": "n/a", "info": {}}]),
        eval_dataset=Dataset.from_list(
            [{"question": "stub", "answer": "n/a", "info": {}}]
        ),
        rubric=build_rubric(),
    )
    state: dict[str, Any] = {
        RolloutStateKeys.PROJECT_ROOT: str(workspace.project_root),
        RolloutStateKeys.TOOL_VISIBLE_GLOBS: [],
        RolloutStateKeys.IMMUTABLE_PATHS: [],
    }
    try:
        tool_args = env.update_tool_args("list_files", {}, [], state)

        async def _run() -> str:
            return await list_files(
                ".",
                max_entries=50,
                project_root=tool_args["project_root"],
                tool_visible_globs=tool_args["tool_visible_globs"],
                immutable_paths=tool_args["immutable_paths"],
            )

        output = asyncio.run(_run())
        assert "debug_context" in output
        assert "dbt_project.yml" not in output
        assert "models/staging/stg_orders.sql" not in output
    finally:
        cleanup_workspace(workspace.workspace_root)


def test_corpus_targets_match_distribution() -> None:
    specs = _all_specs()
    assert len(specs) >= 10
    assert sum(1 for spec in specs if spec["has_bug"] is False) >= 4
    tier_counts = {
        tier: sum(1 for spec in specs if spec["difficulty_tier"] == tier)
        for tier in (1, 2, 3, 4)
    }
    assert tier_counts == {1: 2, 2: 3, 3: 3, 4: 2}
    assert any(set(spec["failure_categories"]) == {"logic"} for spec in specs)
    assert any(set(spec["failure_categories"]) == {"config"} for spec in specs)


def test_load_environment_returns_stateful_env() -> None:
    from dbt_debugger import load_environment

    env = load_environment(scenario_id="join_fanout_exec_revenue", max_scenarios=1)
    assert env.__class__.__name__ == "DbtDebuggerEnv"
    names = {tool.name for tool in (env.tool_defs or [])}
    assert "add_file_evidence" in names
    assert "add_sample_rows_evidence" in names
    assert "add_run_history_evidence" in names
    assert "list_collected_evidence" in names
    assert "submit_diagnosis" in names


def test_build_rubric_uses_human_readable_metric_names() -> None:
    """Eval output should expose audit metrics under their rubric field names."""
    from runtime.env import build_rubric

    rubric = build_rubric()
    names = rubric._get_reward_func_names()
    assert "buggy_models_match" in names
    assert "fix_coverage" in names
    assert "required_evidence_coverage" in names
    assert "forbidden_ok" in names
    assert "no_bug_semantic_partial" in names
    assert "_metric_buggy_models_match" not in names
    assert "_metric_fix_cov" not in names
