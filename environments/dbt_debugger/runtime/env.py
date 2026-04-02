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
    """Ensure ``debug_context/`` is listable/searchable even if omitted from the corpus manifest.

    Read tools already allow ``debug_context/**`` via ``_effective_read_globs``; without this,
    ``list_files debug_context`` returns empty and models invent wrong filenames.
    """
    out = list(manifest_globs)
    norm = {g.replace("\\", "/").strip() for g in out}
    if _DEBUG_CONTEXT_GLOB not in norm and not any(
        g.endswith("debug_context/**") for g in norm
    ):
        out.append(_DEBUG_CONTEXT_GLOB)
    return out


def _state_list(
    state: vf.State,
    key: str,
    *,
    default: list[str] | None = None,
) -> list[str]:
    """Return a copied list from rollout state while preserving explicit empties."""
    value = state.get(key)
    if value is None:
        return list(default or [])
    if isinstance(value, list):
        return list(value)
    return list(default or [])


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
        pr = state.get(RolloutStateKeys.PROJECT_ROOT, "")
        globs = _state_list(
            state,
            RolloutStateKeys.TOOL_VISIBLE_GLOBS,
            default=["**/*"],
        )
        imm = _state_list(state, RolloutStateKeys.IMMUTABLE_PATHS)

        if tool_name == "list_files":
            tool_args["project_root"] = str(pr)
            tool_args["tool_visible_globs"] = _globs_for_list_and_search(list(globs))
            tool_args["immutable_paths"] = list(imm)
            tool_args["_state"] = state
        elif tool_name == "read_file":
            tool_args["project_root"] = str(pr)
            tool_args["tool_visible_globs"] = list(globs)
            tool_args["immutable_paths"] = list(imm)
            tool_args["_state"] = state
        elif tool_name == "search_project":
            tool_args["project_root"] = str(pr)
            tool_args["tool_visible_globs"] = _globs_for_list_and_search(list(globs))
            tool_args["immutable_paths"] = list(imm)
            tool_args["_state"] = state
        elif tool_name == "run_dbt_command":
            tool_args["project_root"] = str(pr)
            tool_args["profiles_dir"] = str(state.get(RolloutStateKeys.PROFILES_DIR, ""))
            tool_args["duckdb_path"] = str(state.get(RolloutStateKeys.DUCKDB_PATH, ""))
            tool_args["_state"] = state
        elif tool_name == "read_artifact":
            tool_args["project_root"] = str(pr)
            tool_args["tool_visible_globs"] = list(globs)
            tool_args["_state"] = state
        elif tool_name == "submit_diagnosis":
            tool_args["scenario_id"] = str(state.get(RolloutStateKeys.SCENARIO_ID, ""))
            tool_args["valid_model_names"] = list(
                state.get(RolloutStateKeys.VALID_MODEL_NAMES) or []
            )
            tool_args["rollout_state"] = state
        return tool_args

    async def setup_state(self, state: vf.State, **kwargs: Any) -> vf.State:
        info = state.get("info") or {}
        scenario_id = str(info.get("scenario_id", ""))
        if not scenario_id:
            raise ValueError("Dataset row missing info.scenario_id")

        try:
            spec = await asyncio.to_thread(_load_scenario_spec, scenario_id)
            mw = await asyncio.to_thread(materialize_scenario_workspace, spec)
        except Exception as e:
            raise vf.InfraError(f"dbt-debugger setup_state failed: {e}") from e

        paths = build_rollout_state_paths(mw)
        for k, v in paths.items():
            state[k] = v

        state[RolloutStateKeys.SCENARIO_ID] = scenario_id
        state[RolloutStateKeys.SCENARIO_SPEC] = as_plain_dict(spec)
        artifact_manifest = dict(spec.get("artifact_manifest") or {})
        manifest_globs = artifact_manifest.get("tool_visible_globs")
        immutable_paths = artifact_manifest.get("immutable_paths")
        state[RolloutStateKeys.ARTIFACT_MANIFEST] = artifact_manifest
        state[RolloutStateKeys.TOOL_VISIBLE_GLOBS] = (
            list(manifest_globs)
            if isinstance(manifest_globs, list)
            else ["**/*"]
        )
        state[RolloutStateKeys.IMMUTABLE_PATHS] = (
            list(immutable_paths)
            if isinstance(immutable_paths, list)
            else []
        )
        dag_models = (spec.get("dag") or {}).get("models") or []
        state[RolloutStateKeys.VALID_MODEL_NAMES] = [
            str(m["name"]) for m in dag_models if isinstance(m, dict) and "name" in m
        ]
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
        spec = state.get(RolloutStateKeys.SCENARIO_SPEC) or {}
        audit = score_diagnosis(sub, spec)
        state[RolloutStateKeys.VERIFICATION_RESULT] = audit
        return float(audit.get("strict_pass", 0.0))

    async def difficulty_metric(state: vf.State) -> float:
        spec = state.get(RolloutStateKeys.SCENARIO_SPEC) or {}
        return float(spec.get("difficulty_tier", -1))

    rubric = vf.Rubric(funcs=[diagnosis_reward], weights=[1.0])
    rubric.add_metric(difficulty_metric)
    rubric.add_metric(_metric_strict_pass)
    rubric.add_metric(_metric_has_bug_match)
    rubric.add_metric(_metric_root_cov)
    return rubric


async def _metric_strict_pass(state: vf.State) -> float:
    vr = state.get(RolloutStateKeys.VERIFICATION_RESULT) or {}
    return float(vr.get("strict_pass", 0.0))


async def _metric_has_bug_match(state: vf.State) -> float:
    vr = state.get(RolloutStateKeys.VERIFICATION_RESULT) or {}
    return 1.0 if vr.get("has_bug_match") else 0.0


async def _metric_root_cov(state: vf.State) -> float:
    vr = state.get(RolloutStateKeys.VERIFICATION_RESULT) or {}
    return float(vr.get("root_cause_coverage", 0.0))
