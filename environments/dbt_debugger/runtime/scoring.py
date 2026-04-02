"""Deterministic diagnosis scoring (stub for StatefulToolEnv rubric)."""

from __future__ import annotations

from typing import Any


def score_diagnosis(  # noqa: ARG001
    submission: dict[str, Any],
    ground_truth: dict[str, Any],
    rubric_hints: dict[str, Any],
) -> dict[str, Any]:
    """Compare a structured submission to evaluator-only ground truth.

    Planned checks:
    - root cause alignment (normalized strings / key phrases)
    - affected model set overlap
    - fix vs no-fix for ``has_bug: false``
    - required evidence citations present in submission

    Args:
        submission: Parsed ``submit_diagnosis`` payload from the model.
        ground_truth: Scenario ``ground_truth`` object.
        rubric_hints: Scenario ``rubric_hints`` object.

    Returns:
        A dict with numeric partial scores and audit details.

    Raises:
        NotImplementedError: Until wired into a ``vf.Rubric``.
    """
    raise NotImplementedError
