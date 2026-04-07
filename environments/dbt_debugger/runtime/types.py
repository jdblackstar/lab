"""Typed helpers for dbt-debugger rollout state and scoring contracts."""

from __future__ import annotations

from typing import Any, TypedDict

ClaimGroup = list[str]
ClaimPattern = list[ClaimGroup]


class DiagnosisVariant(TypedDict, total=False):
    """Accepted diagnosis variant for deterministic scoring."""

    required_models: list[str]
    allowed_models: list[str]
    root_cause_all_of: ClaimPattern
    fix_variants: list[ClaimPattern]


class EvidenceRef(TypedDict, total=False):
    """Structured evidence citation submitted by the model."""

    kind: str
    path: str
    start_line: int
    end_line: int
    table: str
    match_json: str
    min_rows: int
    record_type: str
    name: str
    model: str
    status: str
    contains: str


class EvidenceRequirement(TypedDict, total=False):
    """Evaluator-side evidence requirement aligned to project artifacts."""

    kind: str
    path: str
    table: str
    match: dict[str, Any]
    min_rows: int
    record_type: str
    name: str
    model: str
    status: str
    contains: str
    all_of: list[str]


class DiagnosisSubmission(TypedDict, total=False):
    """Structured payload stored after a valid ``submit_diagnosis`` call."""

    has_bug: bool
    root_cause: str
    affected_models: list[str]
    fix: str
    evidence: list[EvidenceRef]


class RolloutStateKeys:
    """String keys for ``vf.State`` in the ``StatefulToolEnv`` implementation."""

    WORKSPACE_ROOT = "workspace_root"
    PROJECT_ROOT = "project_root"
    CONTEXT_ROOT = "context_root"
    PROFILES_DIR = "profiles_dir"
    DUCKDB_PATH = "duckdb_path"
    SCENARIO_SPEC = "scenario_spec"
    ARTIFACT_MANIFEST = "artifact_manifest"
    TOOL_VISIBLE_GLOBS = "tool_visible_globs"
    IMMUTABLE_PATHS = "immutable_paths"
    SUBMITTED_DIAGNOSIS = "submitted_diagnosis"
    VERIFICATION_RESULT = "verification_result"
    TOOL_TRACE = "tool_trace"
    VALID_MODEL_NAMES = "valid_model_names"
    SCENARIO_ID = "scenario_id"
    WORKSPACE_CLEANUP = "workspace_cleanup"


def as_plain_dict(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *spec* for mutation-safe storage in state."""
    return dict(spec)
