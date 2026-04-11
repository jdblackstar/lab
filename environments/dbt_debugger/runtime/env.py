"""``StatefulToolEnv`` implementation for the dbt-debugger benchmark."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import verifiers as vf

from runtime.scoring import score_diagnosis
from runtime.tools import (
    list_files,
    read_artifact,
    read_file,
    run_dbt_command,
    search_project,
    submit_diagnosis,
)
from runtime.types import RolloutStateKeys, as_plain_dict
from runtime.workspace import build_rollout_state_paths, cleanup_workspace, materialize_scenario_workspace


def _gold_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "scenarios" / "gold"


def _load_scenario_spec(scenario_id: str) -> dict[str, Any]:
    path = _gold_dir() / f"{scenario_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"No scenario file for scenario_id={scenario_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


_DEBUG_CONTEXT_GLOB = "debug_context/**"


def _globs_for_list_and_search(manifest_globs: list[str]) -> list[str]:
    """Append ``debug_context/**`` when missing so list/search can see debug_context."""
    out = list(manifest_globs)
    norm = {g.replace("\\", "/").strip() for g in out}
    if _DEBUG_CONTEXT_GLOB not in norm and not any(
        g.endswith("debug_context/**") for g in norm
    ):
        out.append(_DEBUG_CONTEXT_GLOB)
    return out


class DbtDebuggerEnv(vf.StatefulToolEnv):
    """Per-rollout temp dbt project, tools, and deterministic diagnosis scoring."""

    def __init__(
        self,
        *,
        dataset: Any,
        rubric: vf.Rubric,
        eval_dataset: Any | None = None,
        max_turns: int = 20,
        system_prompt: str | None = None,
        stop_errors: list[type[Exception]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            tools=[],
            dataset=dataset,
            eval_dataset=eval_dataset,
            rubric=rubric,
            max_turns=max_turns,
            system_prompt=system_prompt,
            stop_errors=stop_errors or [vf.ToolParseError],
            **kwargs,
        )
        self.add_tool(
            list_files,
            args_to_skip=["project_root", "tool_visible_globs", "immutable_paths", "_state"],
        )
        self.add_tool(
            read_file,
            args_to_skip=["project_root", "tool_visible_globs", "immutable_paths", "_state"],
        )
        self.add_tool(
            search_project,
            args_to_skip=["project_root", "tool_visible_globs", "immutable_paths", "_state"],
        )
        self.add_tool(
            run_dbt_command,
            args_to_skip=["project_root", "profiles_dir", "duckdb_path", "_state"],
        )
        self.add_tool(
            read_artifact,
            args_to_skip=["project_root", "tool_visible_globs", "_state"],
        )
        self.add_tool(
            submit_diagnosis,
            args_to_skip=["scenario_id", "valid_model_names", "rollout_state"],
        )

    def update_tool_args(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        messages: vf.Messages,
        state: vf.State,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _ = messages
        _ = kwargs
        pr = state[RolloutStateKeys.PROJECT_ROOT]
        globs = state[RolloutStateKeys.TOOL_VISIBLE_GLOBS]
        imm = state[RolloutStateKeys.IMMUTABLE_PATHS]
        assert isinstance(pr, str)
        assert isinstance(globs, list)
        assert isinstance(imm, list)

        if tool_name == "list_files":
            tool_args["project_root"] = pr
            tool_args["tool_visible_globs"] = _globs_for_list_and_search(globs)
            tool_args["immutable_paths"] = imm
            tool_args["_state"] = state
        elif tool_name == "read_file":
            tool_args["project_root"] = pr
            tool_args["tool_visible_globs"] = globs
            tool_args["immutable_paths"] = imm
            tool_args["_state"] = state
        elif tool_name == "search_project":
            tool_args["project_root"] = pr
            tool_args["tool_visible_globs"] = _globs_for_list_and_search(globs)
            tool_args["immutable_paths"] = imm
            tool_args["_state"] = state
        elif tool_name == "run_dbt_command":
            tool_args["project_root"] = pr
            tool_args["profiles_dir"] = state[RolloutStateKeys.PROFILES_DIR]
            tool_args["duckdb_path"] = state[RolloutStateKeys.DUCKDB_PATH]
            tool_args["_state"] = state
        elif tool_name == "read_artifact":
            tool_args["project_root"] = pr
            tool_args["tool_visible_globs"] = globs
            tool_args["_state"] = state
        elif tool_name == "submit_diagnosis":
            tool_args["scenario_id"] = state[RolloutStateKeys.SCENARIO_ID]
            tool_args["valid_model_names"] = state[RolloutStateKeys.VALID_MODEL_NAMES]
            tool_args["rollout_state"] = state
        return tool_args

    async def setup_state(self, state: vf.State, **kwargs: Any) -> vf.State:
        info = state.get("info") or {}
        scenario_id = str(info.get("scenario_id", ""))
        if not scenario_id:
            raise ValueError("Dataset row missing info.scenario_id")

        spec = await asyncio.to_thread(_load_scenario_spec, scenario_id)
        mw = await asyncio.to_thread(materialize_scenario_workspace, spec)

        paths = build_rollout_state_paths(mw)
        for k, v in paths.items():
            state[k] = v

        state[RolloutStateKeys.SCENARIO_ID] = scenario_id
        state[RolloutStateKeys.SCENARIO_SPEC] = as_plain_dict(spec)
        am = spec["artifact_manifest"]
        assert isinstance(am["tool_visible_globs"], list)
        assert isinstance(am["immutable_paths"], list)
        state[RolloutStateKeys.ARTIFACT_MANIFEST] = dict(am)
        state[RolloutStateKeys.TOOL_VISIBLE_GLOBS] = list(am["tool_visible_globs"])
        state[RolloutStateKeys.IMMUTABLE_PATHS] = list(am["immutable_paths"])
        names: list[str] = []
        for m in spec["dag"]["models"]:
            assert isinstance(m, dict) and "name" in m
            names.append(str(m["name"]))
        state[RolloutStateKeys.VALID_MODEL_NAMES] = names
        state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] = None
        state[RolloutStateKeys.VERIFICATION_RESULT] = None
        state[RolloutStateKeys.TOOL_TRACE] = []
        state[RolloutStateKeys.WORKSPACE_CLEANUP] = None

        return await super().setup_state(state, **kwargs)

    @vf.cleanup
    async def _remove_workspace(self, state: vf.State) -> None:
        wr = state.get(RolloutStateKeys.WORKSPACE_ROOT)
        result = await asyncio.to_thread(cleanup_workspace, wr)
        state[RolloutStateKeys.WORKSPACE_CLEANUP] = {
            "removed": result.removed,
            "message": result.message,
        }
        if not result.removed:
            raise vf.InfraError(result.message)

    @vf.stop(priority=10)
    async def _diagnosis_accepted(self, state: vf.State) -> bool:
        sub = state.get(RolloutStateKeys.SUBMITTED_DIAGNOSIS)
        return sub is not None


def build_rubric() -> vf.Rubric:
    """Rubric with deterministic diagnosis scoring and lightweight metrics."""

    async def diagnosis_reward(state: vf.State) -> float:
        """Primary reward: 1.0 iff all deterministic checks pass."""
        sub = state.get(RolloutStateKeys.SUBMITTED_DIAGNOSIS)
        spec = state[RolloutStateKeys.SCENARIO_SPEC]
        assert isinstance(spec, dict)
        audit = score_diagnosis(sub, spec)
        state[RolloutStateKeys.VERIFICATION_RESULT] = audit
        return float(audit["strict_pass"])

    async def difficulty_metric(state: vf.State) -> float:
        spec = state[RolloutStateKeys.SCENARIO_SPEC]
        assert isinstance(spec, dict)
        return float(spec["difficulty_tier"])

    rubric = vf.Rubric(funcs=[diagnosis_reward], weights=[1.0])
    rubric.add_metric(difficulty_metric)
    rubric.add_metric(_metric_strict_pass)
    rubric.add_metric(_metric_has_bug_match)
    rubric.add_metric(_metric_root_cov)
    return rubric


async def _metric_strict_pass(state: vf.State) -> float:
    vr = state[RolloutStateKeys.VERIFICATION_RESULT]
    if not isinstance(vr, dict):
        return 0.0
    return float(vr["strict_pass"])


async def _metric_has_bug_match(state: vf.State) -> float:
    vr = state[RolloutStateKeys.VERIFICATION_RESULT]
    if not isinstance(vr, dict):
        return 0.0
    return 1.0 if vr["has_bug_match"] else 0.0


async def _metric_root_cov(state: vf.State) -> float:
    vr = state[RolloutStateKeys.VERIFICATION_RESULT]
    if not isinstance(vr, dict):
        return 0.0
    return float(vr["root_cause_coverage"])
