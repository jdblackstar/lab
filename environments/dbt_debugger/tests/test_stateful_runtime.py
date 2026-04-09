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

from runtime.scoring import score_diagnosis
from runtime.tools import (
    _normalize_rel_path,
    list_files,
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
            ["dbt", "compile", "--project-dir", str(workspace.project_root)],
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
        "affected_models": ["int_order_lines", "fct_daily_revenue"],
        "fix": (
            "Deduplicate or pre-aggregate promos so the join is one row per order "
            "before fct_daily_revenue sums amount."
        ),
        "evidence": [
            {
                "kind": "file_span",
                "path": "models/intermediate/int_order_lines.sql",
                "start_line": 1,
                "end_line": 14,
            },
            {
                "kind": "sample_rows",
                "table": "raw_order_promos",
                "match_json": "{\"order_id\": 1001}",
                "min_rows": 2,
            },
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["strict_pass"] == 1.0


def test_wrong_mechanism_with_right_models_fails() -> None:
    spec = _spec("join_fanout_exec_revenue")
    submission = {
        "has_bug": True,
        "root_cause": "int_order_lines is stale because an incremental cutoff skipped backfilled rows.",
        "affected_models": ["int_order_lines", "fct_daily_revenue"],
        "fix": "Widen the incremental lookback window on int_order_lines.",
        "evidence": [
            {
                "kind": "file_span",
                "path": "models/intermediate/int_order_lines.sql",
                "start_line": 1,
                "end_line": 14,
            },
            {
                "kind": "sample_rows",
                "table": "raw_order_promos",
                "match_json": "{\"order_id\": 1001}",
                "min_rows": 2,
            },
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["affected_models_match"] is True
    assert audit["root_cause_ok"] is False
    assert audit["strict_pass"] == 0.0


def test_no_bug_semantic_answer_passes_without_magic_phrase() -> None:
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = {
        "has_bug": False,
        "root_cause": (
            "Both decks are querying the same mart; the discrepancy comes from fiscal "
            "QTD versus calendar QTD filters in BI rather than warehouse logic."
        ),
        "affected_models": [],
        "fix": (
            "Standardize the saved views or publish an explore with explicit date logic "
            "so the fiscal and calendar definitions are not mixed."
        ),
        "evidence": [
            {
                "kind": "file_span",
                "path": "models/marts/fct_revenue_daily.sql",
                "start_line": 1,
                "end_line": 4,
            },
            {
                "kind": "run_history",
                "record_type": "summary",
                "contains": "All models succeeded",
            },
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["strict_pass"] == 1.0


def test_forbidden_claim_pattern_still_fails_on_rewording() -> None:
    spec = _spec("no_bug_fiscal_vs_calendar")
    submission = {
        "has_bug": False,
        "root_cause": "The warehouse mart is definitely broken and is corrupting revenue.",
        "affected_models": [],
        "fix": "Rewrite fct_revenue_daily to fix the regression.",
        "evidence": [
            {
                "kind": "file_span",
                "path": "models/marts/fct_revenue_daily.sql",
                "start_line": 1,
                "end_line": 4,
            },
            {
                "kind": "run_history",
                "record_type": "summary",
                "contains": "All models succeeded",
            },
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["forbidden_ok"] is False
    assert audit["strict_pass"] == 0.0


def test_negated_accepted_root_cause_phrase_does_not_fail_strict_pass() -> None:
    """Accepted negated root-cause phrases must not trip forbidden claim patterns."""
    spec = deepcopy(_spec("campaign_spend_replay_restatement"))
    spec["rubric_hints"]["accepted_diagnoses"][0]["root_cause_all_of"][3] = [
        "not duplicated",
        "no duplication",
        "no dbt bug",
        "no warehouse bug",
    ]
    submission = {
        "has_bug": False,
        "root_cause": (
            "The vendor replay backfilled missing source rows, and the downstream "
            "full-refresh loaded them correctly. There was no dbt bug, and the "
            "historical spend was not duplicated."
        ),
        "affected_models": [],
        "fix": "No fix needed; communicate the replay restatement to stakeholders.",
        "evidence": [
            {
                "kind": "run_history",
                "record_type": "summary",
                "contains": "vendor replay",
            },
            {
                "kind": "sample_rows",
                "table": "ads_campaign_spend",
                "match_json": json.dumps({"load_batch": "vendor_replay_2026_03_30"}),
                "min_rows": 2,
            },
            {
                "kind": "file_span",
                "path": "models/marts/fct_campaign_spend_daily.sql",
                "start_line": 1,
                "end_line": 6,
            },
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["root_cause_ok"] is True
    assert audit["forbidden_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_negated_accepted_fix_phrase_does_not_fail_strict_pass() -> None:
    """Accepted negated fix phrases must not trip forbidden claim patterns."""
    spec = _spec("campaign_spend_replay_restatement")
    submission = {
        "has_bug": False,
        "root_cause": (
            "A vendor replay supplied late source rows, and a clean downstream "
            "full-refresh loaded the updated source truth. The row keys remain "
            "distinct and dbt logic is correct."
        ),
        "affected_models": [],
        "fix": (
            "No warehouse rewrite of fct_campaign_spend_daily is needed; communicate "
            "the vendor replay restatement to stakeholders."
        ),
        "evidence": [
            {
                "kind": "run_history",
                "record_type": "summary",
                "contains": "vendor replay",
            },
            {
                "kind": "sample_rows",
                "table": "ads_campaign_spend",
                "match_json": json.dumps({"load_batch": "vendor_replay_2026_03_30"}),
                "min_rows": 2,
            },
            {
                "kind": "file_span",
                "path": "models/marts/fct_campaign_spend_daily.sql",
                "start_line": 1,
                "end_line": 6,
            },
        ],
    }
    audit = score_diagnosis(submission, spec)
    assert audit["fix_ok"] is True
    assert audit["forbidden_ok"] is True
    assert audit["strict_pass"] == 1.0


def test_submit_diagnosis_does_not_branch_on_hidden_has_bug() -> None:
    state_bug: dict[str, Any] = {
        RolloutStateKeys.SCENARIO_SPEC: {"has_bug": True},
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }
    state_no_bug: dict[str, Any] = {
        RolloutStateKeys.SCENARIO_SPEC: {"has_bug": False},
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }

    async def _submit(state: dict[str, Any]) -> str:
        return await submit_diagnosis(
            True,
            "There is a bug in model_a.",
            ["model_a"],
            "Fix model_a.",
            ["file_span|models/model_a.sql|1|2"],
            scenario_id="hidden",
            valid_model_names=["model_a"],
            rollout_state=state,
        )

    bug_response = asyncio.run(_submit(state_bug))
    no_bug_response = asyncio.run(_submit(state_no_bug))
    assert bug_response == no_bug_response
    assert state_bug[RolloutStateKeys.SUBMITTED_DIAGNOSIS] == state_no_bug[
        RolloutStateKeys.SUBMITTED_DIAGNOSIS
    ]


def test_submit_diagnosis_response_hides_internal_metadata() -> None:
    state: dict[str, Any] = {
        RolloutStateKeys.SCENARIO_SPEC: {"has_bug": True},
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }

    async def _submit() -> str:
        return await submit_diagnosis(
            True,
            "model_a has a bug",
            ["model_a"],
            "Fix model_a",
            ["file_span|models/model_a.sql|1|2"],
            scenario_id="secret-scenario",
            valid_model_names=["model_a"],
            rollout_state=state,
        )

    response = json.loads(asyncio.run(_submit()))
    assert response == {
        "status": "accepted",
        "message": "Diagnosis stored for evaluator-only scoring.",
    }


def test_submit_diagnosis_rejects_second_submission() -> None:
    state: dict[str, Any] = {
        RolloutStateKeys.SCENARIO_SPEC: {"has_bug": True},
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }

    async def _submit(root_cause: str, fix: str) -> str:
        return await submit_diagnosis(
            True,
            root_cause,
            ["model_a"],
            fix,
            ["file_span|models/model_a.sql|1|2"],
            scenario_id="secret-scenario",
            valid_model_names=["model_a"],
            rollout_state=state,
        )

    first = json.loads(asyncio.run(_submit("first cause", "first fix")))
    second = asyncio.run(_submit("second cause", "second fix"))
    assert first["status"] == "accepted"
    assert "already submitted" in second
    assert state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] == {
        "has_bug": True,
        "root_cause": "first cause",
        "affected_models": ["model_a"],
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


def test_submit_diagnosis_validation_rejects_unknown_model() -> None:
    state: dict[str, Any] = {
        RolloutStateKeys.SCENARIO_SPEC: {"has_bug": True},
        RolloutStateKeys.SUBMITTED_DIAGNOSIS: None,
    }

    async def _submit() -> str:
        return await submit_diagnosis(
            True,
            "x",
            ["not_a_model"],
            "fix",
            ["file_span|models/model_a.sql|1|2"],
            scenario_id="join_fanout_exec_revenue",
            valid_model_names=["model_a"],
            rollout_state=state,
        )

    message = asyncio.run(_submit())
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


def test_cleanup_workspace_surfaces_rmtree_failure(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert "submit_diagnosis" in names
