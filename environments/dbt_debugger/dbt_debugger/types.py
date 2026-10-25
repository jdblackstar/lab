"""Typed shapes of the scenario scoring contract (``rubric_hints``) and evidence refs."""

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
