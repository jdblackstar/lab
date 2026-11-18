"""dbt-debugger taskset: diagnose seeded dbt incidents with scoped tools and cited evidence.

Each task is one bundled gold scenario. Its rollout gets a fresh dbt + DuckDB workspace
behind ``DbtDebuggerToolset``; the agent investigates, stores evidence, and submits a
structured diagnosis, which is scored deterministically against the scenario's
``rubric_hints`` (no LLM judge).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import verifiers.v1 as vf
from dbt_debugger.evidence import project_files
from dbt_debugger.scenarios import build_prompt, gold_paths, load_scenario_spec
from dbt_debugger.scoring import Audit, score_diagnosis
from dbt_debugger.toolset import DbtDebuggerState, DbtDebuggerToolset

MAX_TURNS = 20
"""Default model-turn cap per rollout (v0's ``max_turns``)."""

AUDIT_METRICS: tuple[tuple[str, bool], ...] = (
    ("strict_pass", False),
    ("has_bug_match", True),
    ("buggy_models_match", True),
    ("diagnosis_variant_ok", True),
    ("root_cause_coverage", False),
    ("fix_coverage", False),
    ("required_evidence_coverage", False),
    ("forbidden_ok", True),
    ("no_bug_semantic_partial", False),
)
"""Audit fields reported as metrics; ``True`` marks fields recorded as 0/1 truthiness."""


class DbtDebuggerData(vf.TaskData):
    scenario_id: str
    """Stem of the scenario JSON under ``scenarios/gold/``."""
    difficulty_tier: int
    """Scenario difficulty, 1 (easiest) to 4."""


class DbtDebuggerTaskConfig(vf.TaskConfig):
    tools: vf.ToolsetConfig = vf.ToolsetConfig()
    """Placement of the per-rollout tool server (local subprocess by default)."""


class DbtDebuggerTask(
    vf.Task[DbtDebuggerData, DbtDebuggerState, DbtDebuggerTaskConfig]
):
    @property
    def key(self) -> str:
        return self.data.scenario_id

    @property
    def spec(self) -> dict[str, Any]:
        """The full scenario, including evaluator-only fields; never sent to the model."""
        return load_scenario_spec(self.data.scenario_id)

    @classmethod
    def toolsets(cls, config: DbtDebuggerTaskConfig) -> list[vf.Toolset]:
        return [DbtDebuggerToolset(config.tools)]

    @vf.stop(priority=10)
    async def diagnosis_accepted(self, trace: vf.Trace) -> bool:
        return trace.state.submitted_diagnosis is not None

    async def finalize(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        """Persist the rollout's tool-side state on the trace for scoring and review."""
        state = trace.state
        trace.info["submitted_diagnosis"] = state.submitted_diagnosis
        trace.info["collected_evidence"] = state.collected_evidence
        trace.info["tool_trace"] = state.tool_trace
        trace.info["verification_result"] = dataclasses.asdict(self.audit(trace))

    def audit(self, trace: vf.Trace) -> Audit:
        """Deterministic audit of the persisted submission (pure, so safe to recompute)."""
        return score_diagnosis(trace.info.get("submitted_diagnosis"), self.spec)

    @vf.reward(weight=1.0)
    async def diagnosis_reward(self, trace: vf.Trace) -> float:
        """1.0 iff every deterministic check passes."""
        return self.audit(trace).strict_pass

    @vf.metric
    async def difficulty_metric(self) -> float:
        return float(self.data.difficulty_tier)

    @vf.metric
    async def audit_metrics(self, trace: vf.Trace) -> dict[str, float]:
        audit = self.audit(trace)
        out: dict[str, float] = {}
        for field, truthy in AUDIT_METRICS:
            value = getattr(audit, field)
            out[field] = 1.0 if truthy and value else float(value)
        return out

    async def validate(self, runtime: vf.Runtime) -> bool:
        """Gold check: collect the required evidence and submit the documented ground
        truth through the real tools; the stored diagnosis must strictly pass."""
        spec = self.spec
        toolset = DbtDebuggerToolset(vf.ToolsetConfig())
        async with toolset._exit_stack:
            await toolset.setup_task(self.data)
            for requirement in spec["rubric_hints"]["required_evidence"]:
                result = await _collect_gold_evidence(toolset, requirement)
                if result.startswith("Error:"):
                    raise ValueError(f"gold evidence rejected: {result}")
            truth = spec["ground_truth"]
            result = await toolset.submit_diagnosis(
                bool(spec["has_bug"]),
                str(truth["root_cause"]),
                list(truth.get("affected_models") or []),
                str(truth["fix"]),
            )
            if result.startswith("Error:"):
                raise ValueError(f"gold diagnosis rejected: {result}")
            audit = score_diagnosis(toolset.state.submitted_diagnosis, spec)
            return audit.strict_pass == 1.0


async def _collect_gold_evidence(
    toolset: DbtDebuggerToolset, requirement: dict[str, Any]
) -> str:
    """Store the evidence ref that satisfies one ``required_evidence`` entry."""
    kind = requirement["kind"]
    if kind == "file_span":
        # The whole file contains every anchor the requirement names.
        path = requirement["path"]
        content = project_files(toolset.workspace.spec)[path]
        return await toolset.add_file_evidence(
            path, 1, max(1, len(content.splitlines()))
        )
    if kind == "sample_rows":
        return await toolset.add_sample_rows_evidence(
            requirement["table"],
            json.dumps(requirement["match"]),
            int(requirement.get("min_rows", 1)),
        )
    if kind == "run_history":
        return await toolset.add_run_history_evidence(
            requirement["record_type"],
            str(requirement.get("model", "")),
            str(requirement.get("name", "")),
            str(requirement.get("status", "")),
            str(requirement.get("contains", "")),
        )
    raise ValueError(f"unknown required_evidence kind {kind!r}")


class DbtDebuggerConfig(vf.TasksetConfig):
    difficulty_tier: int | None = None
    """Keep only scenarios of this difficulty tier (1-4). Pick single scenarios with
    ``--select.include.ids <scenario_id>``."""
    task: DbtDebuggerTaskConfig = DbtDebuggerTaskConfig()


class DbtDebuggerTaskset(vf.Taskset[DbtDebuggerTask, DbtDebuggerConfig]):
    def load(self) -> list[DbtDebuggerTask]:
        tasks = []
        for path in gold_paths():
            spec = load_scenario_spec(path.stem)
            tier = int(spec["difficulty_tier"])
            if self.config.difficulty_tier not in (None, tier):
                continue
            data = DbtDebuggerData(
                id=spec["scenario_id"],
                name=spec["title"],
                prompt=build_prompt(spec),
                scenario_id=spec["scenario_id"],
                difficulty_tier=tier,
            )
            tasks.append(DbtDebuggerTask(data, self.config.task))
        if not tasks:
            raise ValueError("No scenarios matched the given filters")
        return tasks


class DbtDebuggerEnvConfig(vf.SingleAgentEnvConfig):
    agent: vf.AgentConfig = vf.AgentConfig(
        harness={"id": "null"},
        runtime=vf.SubprocessConfig(),
        max_turns=MAX_TURNS,
    )
    """The tools-only ``null`` harness on the local subprocess runtime, capped at
    ``MAX_TURNS`` model turns (``--env.agent.max-turns`` to change it)."""


class DbtDebuggerEnv(vf.SingleAgentEnv, vf.Env[DbtDebuggerEnvConfig]):
    """The single-agent env with dbt-debugger's defaults pinned.

    Harnesses that execute code are refused: a shell on the evaluator host could read the
    bundled answer keys under ``scenarios/gold/`` instead of debugging the project.
    """

    def __init__(self, config: DbtDebuggerEnvConfig) -> None:
        super().__init__(config)
        for role, harness_config in config.agent_harnesses().items():
            if vf.load_harness(harness_config).EXECUTES_CODE:
                raise ValueError(
                    f"dbt-debugger needs a tools-only harness; {role!r} uses "
                    f"{harness_config.id!r}, which executes code and could read the "
                    "scenario answer keys. Use --env.agent.harness.id null."
                )
