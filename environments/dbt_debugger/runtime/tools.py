"""Tool callables for StatefulToolEnv (stubs).

Implementations will mirror the surface documented in ``spec/runtime_mapping.md``:
``list_files``, ``read_file``, ``search_project``, ``run_dbt_command``,
``read_artifact``, ``submit_diagnosis``.
"""

from __future__ import annotations


async def list_files(
    path: str = ".", max_entries: int = 200, workspace_root: str = ""
) -> str:  # noqa: ARG001
    """List files under *path* (workspace-relative). *workspace_root* is hidden from the model."""
    raise NotImplementedError


async def read_file(
    path: str,
    start_line: int = 1,
    end_line: int = 220,
    workspace_root: str = "",
) -> str:  # noqa: ARG001
    """Read a text file with line numbers."""
    raise NotImplementedError


async def search_project(
    pattern: str, glob_pattern: str = "**/*", workspace_root: str = ""
) -> str:  # noqa: ARG001
    """Search file contents under the workspace."""
    raise NotImplementedError


async def run_dbt_command(
    args: str,
    timeout_seconds: int = 120,
    workspace_root: str = "",
) -> str:  # noqa: ARG001
    """Run ``dbt`` with the given argument string (shell split in real impl)."""
    raise NotImplementedError


async def read_artifact(path: str, workspace_root: str = "") -> str:  # noqa: ARG001
    """Read a build artifact (e.g. under ``target/``) if allowed by manifest."""
    raise NotImplementedError


async def submit_diagnosis(payload_json: str, scenario_id: str = "") -> str:  # noqa: ARG001
    """Accept structured diagnosis JSON; *scenario_id* is injected by the env."""
    raise NotImplementedError
