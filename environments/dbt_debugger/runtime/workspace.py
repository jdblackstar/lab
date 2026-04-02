"""Per-rollout workspace materialization (stub for StatefulToolEnv phase)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def materialize_scenario_workspace(
    spec: dict[str, Any],
    parent_dir: Path,
) -> Path:  # noqa: ARG001
    """Write ``dbt_project.files`` under a new directory tree.

    Not used by the corpus-phase ``SingleTurnEnv``; reserved for
    ``setup_state`` when the executable harness lands.

    Args:
        spec: Full scenario dict including ``dbt_project.files``.
        parent_dir: Existing directory that will contain a new child folder.

    Returns:
        Path to the project root (where ``dbt_project.yml`` lives).

    Raises:
        NotImplementedError: Until the harness is implemented.
    """
    raise NotImplementedError(
        "Workspace materialization will be implemented with StatefulToolEnv.setup_state."
    )


def cleanup_workspace(workspace_root: Path) -> None:  # noqa: ARG001
    """Remove a rollout workspace recursively (idempotent).

    Args:
        workspace_root: Directory created for one rollout.

    Raises:
        NotImplementedError: Until the harness is implemented.
    """
    raise NotImplementedError("Use shutil.rmtree in @vf.cleanup once harness exists.")
