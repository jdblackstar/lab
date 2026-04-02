"""Typed helpers for future dbt-debugger rollout state (StatefulToolEnv phase)."""

from __future__ import annotations

from typing import Any, TypedDict


class ScenarioInfo(TypedDict, total=False):
    """Subset of scenario fields safe to put in dataset ``info``."""

    scenario_id: str
    difficulty_tier: int


class RolloutStateKeys:
    """String keys planned for ``vf.State`` in the StatefulToolEnv implementation."""

    WORKSPACE_ROOT = "workspace_root"
    PROJECT_ROOT = "project_root"
    SCENARIO_SPEC = "scenario_spec"
    ARTIFACT_MANIFEST = "artifact_manifest"
    SUBMITTED_DIAGNOSIS = "submitted_diagnosis"
    VERIFICATION_RESULT = "verification_result"
    TOOL_TRACE = "tool_trace"


def as_plain_dict(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *spec* for mutation-safe storage in state."""
    return dict(spec)
