"""The scored diagnosis contract: a scenario's ``rubric_hints`` as typed objects.

``rubric_hints`` declare which diagnoses are accepted, which evidence must be cited, and
which claims are forbidden. Scoring and the offline validator both read them through
``Rubric`` so the two cannot interpret the JSON differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dbt_debugger.claim_text_matching import claim_group_matches


@dataclass(frozen=True)
class ClaimPattern:
    """A claim as a conjunction of synonym groups.

    ``[["fanout", "duplicate"], ["promo"]]`` matches text that mentions a fanout or
    duplication *and* promos, in any wording ``text_contains_option`` accepts.
    """

    groups: tuple[tuple[str, ...], ...]

    @classmethod
    def from_json(cls, raw: list[list[str]]) -> ClaimPattern:
        return cls(tuple(tuple(group) for group in raw))

    @property
    def options(self) -> list[str]:
        """Every non-empty alternative across all groups."""
        return [option for group in self.groups for option in group if option]

    def matches(self, text: str) -> bool:
        """Return whether every group has at least one alternative in *text*."""
        return all(claim_group_matches(text, group) for group in self.groups)

    def coverage(self, text: str) -> float:
        """Return the fraction of groups satisfied by *text*; 1.0 for an empty pattern."""
        if not self.groups:
            return 1.0
        hits = sum(1 for group in self.groups if claim_group_matches(text, group))
        return hits / len(self.groups)


@dataclass(frozen=True)
class VariantResult:
    """How one submission measures up against one accepted diagnosis variant."""

    models_ok: bool
    root_ok: bool
    fix_ok: bool
    root_coverage: float
    fix_coverage: float

    @property
    def ok(self) -> bool:
        return self.models_ok and self.root_ok and self.fix_ok


@dataclass(frozen=True)
class DiagnosisVariant:
    """One accepted way to diagnose the scenario.

    A submission matches when its ``buggy_models`` include every required model and
    nothing outside the allowed set, its root cause states ``root_cause``, and its fix
    states at least one of ``fix_variants`` (always satisfied when there are none).
    """

    required_models: frozenset[str]
    allowed_models: frozenset[str]
    root_cause: ClaimPattern
    fix_variants: tuple[ClaimPattern, ...]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> DiagnosisVariant:
        """Parse one ``accepted_diagnoses`` entry; ``allowed_models`` defaults to
        exactly ``required_models``."""
        required = frozenset(raw.get("required_models") or [])
        allowed = raw.get("allowed_models")
        return cls(
            required_models=required,
            allowed_models=required if allowed is None else frozenset(allowed),
            root_cause=ClaimPattern.from_json(raw.get("root_cause_all_of") or []),
            fix_variants=tuple(
                ClaimPattern.from_json(pattern)
                for pattern in raw.get("fix_variants") or []
            ),
        )

    def evaluate(
        self, *, buggy_models: list[str], root_cause: str, fix: str
    ) -> VariantResult:
        fixes = self.fix_variants
        return VariantResult(
            models_ok=self.required_models <= set(buggy_models) <= self.allowed_models,
            root_ok=self.root_cause.matches(root_cause),
            fix_ok=any(pattern.matches(fix) for pattern in fixes) if fixes else True,
            root_coverage=self.root_cause.coverage(root_cause),
            fix_coverage=max(pattern.coverage(fix) for pattern in fixes)
            if fixes
            else 1.0,
        )


@dataclass(frozen=True)
class Rubric:
    """One scenario's ``rubric_hints``."""

    accepted_diagnoses: tuple[DiagnosisVariant, ...]
    required_evidence: tuple[dict[str, Any], ...]
    """``required_evidence`` entries as written; ``evidence.evidence_matches`` reads them."""
    forbidden_claims: tuple[ClaimPattern, ...]

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> Rubric:
        hints = spec["rubric_hints"]
        return cls(
            accepted_diagnoses=tuple(
                DiagnosisVariant.from_json(variant)
                for variant in hints["accepted_diagnoses"]
            ),
            required_evidence=tuple(hints["required_evidence"]),
            forbidden_claims=tuple(
                ClaimPattern.from_json(pattern)
                for pattern in hints.get("forbidden_claims") or []
            ),
        )
