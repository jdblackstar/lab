"""DBT debugger benchmark — scenario corpus and Verifiers ``StatefulToolEnv``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset

from runtime.env import DbtDebuggerEnv, build_rubric


def _load_dotenv_files() -> None:
    """Load ``.env`` files into the process environment (non-destructive).

    With ``python-dotenv`` defaults, the first file that defines a key wins; keys
    already present in the process environment are never overwritten.

    Precedence (highest first): current working directory, then this package
    directory, then lab/repo root (``.../lab/.env`` when the package lives under
    ``environments/dbt_debugger``). Repo root therefore supplies defaults for
    keys omitted in cwd/package files.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    pkg_dir = Path(__file__).resolve().parent
    repo_root = pkg_dir.parent.parent
    load_dotenv()
    load_dotenv(pkg_dir / ".env")
    load_dotenv(repo_root / ".env")


def _gold_paths() -> list[Path]:
    """Return sorted paths to bundled gold scenario JSON files."""
    root = Path(__file__).resolve().parent / "scenarios" / "gold"
    return sorted(root.glob("*.json"))


def _row_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Build one HF dataset row from a scenario dict (no ground truth in prompt)."""
    message = str(spec["symptom"]["message"])
    instructions = (
        "You are a senior analytics engineer debugging a dbt project in a local sandbox.\n"
        "You have tools to inspect project files, explore supporting debug context, run "
        "bounded dbt commands, read build artifacts under target/, and submit a structured "
        "diagnosis.\n"
        "Start by exploring the workspace with the tools rather than assuming where the "
        "issue lives.\n"
        "When you are done, call submit_diagnosis exactly once with your conclusion, "
        "affected models, fix, and grounded evidence citations.\n\n"
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
    max_turns: int = 20,
) -> vf.Environment:
    """Return a Verifiers ``StatefulToolEnv`` over bundled gold scenarios.

    Each rollout materializes a temporary dbt + DuckDB workspace, exposes debugging tools,
    and scores a structured ``submit_diagnosis`` against the evaluator-only rubric
    contract in ``rubric_hints``.

    Args:
        scenario_id: If set, keep only this scenario stem (must match a JSON file).
        difficulty_tier: If set, filter scenarios by ``difficulty_tier``.
        scenario_set: Reserved for future splits; only ``gold`` is bundled.
        max_scenarios: Cap rows after filtering; ``-1`` means no cap.
        max_turns: Maximum tool/model turns per rollout (passed to the environment).

    Returns:
        A :class:`DbtDebuggerEnv` over the filtered dataset.
    """
    _load_dotenv_files()
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
        rows = rows[: max_scenarios]

    if not rows:
        raise ValueError("No scenarios matched the given filters")

    dataset = Dataset.from_list(rows)
    rubric = build_rubric()

    return DbtDebuggerEnv(
        dataset=dataset,
        eval_dataset=dataset,
        rubric=rubric,
        max_turns=max_turns,
    )
