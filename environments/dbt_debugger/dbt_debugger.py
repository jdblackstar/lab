"""DBT debugger benchmark — scenario corpus and placeholder Verifiers environment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset


def _gold_paths() -> list[Path]:
    """Return sorted paths to bundled gold scenario JSON files."""
    root = Path(__file__).resolve().parent / "scenarios" / "gold"
    return sorted(root.glob("*.json"))


def _row_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Build one HF dataset row from a scenario dict (no ground truth in prompt)."""
    title = str(spec["title"])
    message = str(spec["symptom"]["message"])
    instructions = (
        "You are a senior analytics engineer debugging a dbt project.\n"
        "This rollout is corpus-only: tools are not wired yet. Reason about the "
        "likely root cause from the stakeholder report and the scenario title.\n\n"
        f"Scenario title: {title}\n\n"
        f"Stakeholder report:\n{message}\n"
    )
    return {
        "question": instructions,
        "answer": "n/a",
        "info": {
            "scenario_id": spec["scenario_id"],
            "difficulty_tier": spec["difficulty_tier"],
        },
    }


def load_environment(
    scenario_id: str | None = None,
    difficulty_tier: int | None = None,
    scenario_set: str = "gold",
    max_scenarios: int = -1,
) -> vf.Environment:
    """Return a Verifiers environment over bundled gold scenarios.

    Corpus phase: uses ``SingleTurnEnv`` with a zero-weight placeholder rubric so
    ``prime eval run`` can smoke-test packaging and prompts. A future version
    swaps in ``StatefulToolEnv`` with dbt tools and deterministic diagnosis
    scoring (see ``spec/runtime_mapping.md``).

    Args:
        scenario_id: If set, keep only this scenario stem (must match a JSON file).
        difficulty_tier: If set, filter scenarios by ``difficulty_tier``.
        scenario_set: Reserved for future splits; only ``gold`` is bundled.
        max_scenarios: Cap rows after filtering; ``-1`` means no cap.

    Returns:
        A ``vf.SingleTurnEnv`` over the filtered dataset.
    """
    if scenario_set != "gold":
        raise ValueError(f"Only scenario_set='gold' is supported; got {scenario_set!r}")

    paths = _gold_paths()
    if scenario_id is not None:
        paths = [p for p in paths if p.stem == scenario_id]
        if not paths:
            raise ValueError(f"No scenario file for scenario_id={scenario_id!r}")

    rows: list[dict[str, Any]] = []
    for path in paths:
        spec = json.loads(path.read_text(encoding="utf-8"))
        if (
            difficulty_tier is not None
            and spec.get("difficulty_tier") != difficulty_tier
        ):
            continue
        rows.append(_row_from_spec(spec))

    if max_scenarios > 0:
        rows = rows[:max_scenarios]

    if not rows:
        raise ValueError("No scenarios matched the given filters")

    dataset = Dataset.from_list(rows)

    async def _placeholder_reward(completion: Any, info: Any) -> float:  # noqa: ARG001
        """Always zero; corpus phase — scoring comes in StatefulToolEnv later."""
        return 0.0

    async def _difficulty_metric(completion: Any, info: Any) -> float:  # noqa: ARG001
        """Log difficulty tier as a numeric metric for traceability."""
        return float(info.get("difficulty_tier", -1))

    rubric = vf.Rubric(funcs=[_placeholder_reward], weights=[0.0])
    rubric.add_metric(_difficulty_metric)

    # SingleTurnEnv fixes max_turns=1 internally; multi-turn/tooling will use
    # StatefulToolEnv later (see spec/runtime_mapping.md).
    return vf.SingleTurnEnv(dataset=dataset, eval_dataset=dataset, rubric=rubric)
