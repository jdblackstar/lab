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
    buggy_models: list[str]
    fix: str
    evidence: list[EvidenceRef]


class RolloutStateKeys:
    """Keys of the rollout-state dict the tool functions read and mutate.

    The toolset builds this dict from its typed ``DbtDebuggerState`` (plus the
    server-local scenario spec) around each tool call and writes it back afterwards.
    """

    SCENARIO_SPEC = "scenario_spec"
    COLLECTED_EVIDENCE = "collected_evidence"
    SUBMITTED_DIAGNOSIS = "submitted_diagnosis"
    TOOL_TRACE = "tool_trace"
