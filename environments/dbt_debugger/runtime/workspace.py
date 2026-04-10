"""Per-rollout workspace materialization for ``StatefulToolEnv``."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import yaml

from runtime.types import RolloutStateKeys


@dataclass(frozen=True)
class MaterializedWorkspace:
    """Paths and metadata for one rollout workspace."""

    workspace_root: Path
    project_root: Path
    context_root: Path
    profiles_dir: Path
    duckdb_path: Path


@dataclass(frozen=True)
class CleanupResult:
    """Outcome of a workspace cleanup attempt."""

    removed: bool
    message: str


_WORKSPACE_MARKER = ".dbt_debugger_workspace.json"


def _parse_sources_from_spec(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract (schema, table) pairs from ``models/sources.yml`` in the scenario spec."""
    files = spec.get("dbt_project", {}).get("files", [])
    for f in files:
        if not isinstance(f, dict):
            continue
        path = str(f.get("path", ""))
        if path.endswith("sources.yml") or path.endswith("sources.yaml"):
            content = f.get("content", "")
            if not isinstance(content, str):
                break
            data = yaml.safe_load(content) or {}
            out: list[tuple[str, str]] = []
            for src in data.get("sources", []) or []:
                if not isinstance(src, dict):
                    continue
                schema = str(src.get("schema", "") or src.get("name", ""))
                for tbl in src.get("tables", []) or []:
                    if isinstance(tbl, str):
                        out.append((schema, tbl))
                    elif isinstance(tbl, dict) and "name" in tbl:
                        out.append((schema, str(tbl["name"])))
            return out
    return []


def _match_sample_key_to_source(
    key: str, sources: list[tuple[str, str]]
) -> tuple[str, str]:
    """Map a ``sample_data`` key to ``(schema, table)`` using naming conventions.

    Supported:
    - ``{schema}_{table}`` where ``table`` may contain underscores (longest match).
    - ``source_{schema}__{table}`` (double underscore separates schema from table tail).
    """
    if key.startswith("source_") and "__" in key:
        rest = key.removeprefix("source_")
        schema_part, table_part = rest.split("__", 1)
        candidate = (schema_part, table_part.replace("__", "_"))
        if candidate in sources:
            return candidate

    for schema, table in sorted(sources, key=lambda st: len(st[1]), reverse=True):
        prefix = f"{schema}_"
        if key.startswith(prefix) and key[len(prefix) :] == table:
            return schema, table

    raise ValueError(
        f"sample_data key {key!r} does not match any declared source as "
        f"{{schema}}_{{table}}; sources={sources!r}"
    )


def _logical_type_to_duckdb(col_type: str) -> str:
    t = col_type.lower().strip()
    if t == "string":
        return "VARCHAR"
    if t == "integer":
        return "BIGINT"
    if t == "numeric":
        return "DOUBLE"
    if t == "timestamp":
        return "TIMESTAMP"
    if t == "boolean":
        return "BOOLEAN"
    return "VARCHAR"


def _load_sample_tables(con: duckdb.DuckDBPyConnection, spec: dict[str, Any]) -> None:
    """Create schemas/tables in DuckDB from ``sample_data`` keyed by source convention."""
    sources = _parse_sources_from_spec(spec)
    if not sources:
        raise ValueError("No sources found in dbt_project.files; cannot load sample_data")
    sample_data = spec.get("sample_data") or {}
    if not isinstance(sample_data, dict):
        raise ValueError("sample_data must be an object")

    for key, table_obj in sample_data.items():
        if not isinstance(table_obj, dict):
            continue
        schema_name, table_name = _match_sample_key_to_source(str(key), sources)
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
        columns = table_obj.get("columns", [])
        rows = table_obj.get("rows", [])
        if not isinstance(columns, list) or not columns:
            raise ValueError(f"sample_data.{key} must declare non-empty columns")
        col_defs = ", ".join(
            f'"{c["name"]}" {_logical_type_to_duckdb(str(c.get("type", "string")))}'
            for c in columns
            if isinstance(c, dict) and "name" in c
        )
        fq = f'"{schema_name}"."{table_name}"'
        con.execute(f"CREATE OR REPLACE TABLE {fq} ({col_defs})")
        if not rows:
            continue
        col_names = [c["name"] for c in columns if isinstance(c, dict) and "name" in c]
        placeholders = ", ".join(["?"] * len(col_names))
        col_list = ", ".join(f'"{n}"' for n in col_names)
        insert_sql = f"INSERT INTO {fq} ({col_list}) VALUES ({placeholders})"
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"sample_data.{key}.rows[{i}] must be an object")
            values = [row.get(n) for n in col_names]
            con.execute(insert_sql, values)


def _write_profiles_yml(profiles_dir: Path, duckdb_path: Path, profile_name: str) -> None:
    """Write a rollout-local dbt profile pointing at the DuckDB file."""
    profiles_dir.mkdir(parents=True, exist_ok=True)
    # dbt-duckdb expects path to the database file
    text = (
        f"{profile_name}:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: duckdb\n"
        f"      path: {json.dumps(str(duckdb_path.resolve()))}\n"
        "      threads: 4\n"
    )
    (profiles_dir / "profiles.yml").write_text(text, encoding="utf-8")


def _write_context_files(context_root: Path, spec: dict[str, Any]) -> None:
    """Materialize agent-visible debug context without exposing the DAG upfront."""
    context_root.mkdir(parents=True, exist_ok=True)
    (context_root / "sample_data.json").write_text(
        json.dumps(spec.get("sample_data", {}), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (context_root / "run_history.json").write_text(
        json.dumps(spec.get("run_history", {}), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_project_files(project_root: Path, spec: dict[str, Any]) -> None:
    """Write ``dbt_project.files`` (+ seeds/macros) under *project_root*."""
    dbt = spec.get("dbt_project", {})
    files = dbt.get("files", [])
    for entry in files:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("path", "")).strip().replace("\\", "/")
        if not rel or rel.startswith("/") or ".." in rel.split("/"):
            raise ValueError(f"Invalid dbt_project.files path: {rel!r}")
        content = entry.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        dest = project_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    for key in ("macros", "seeds"):
        for entry in dbt.get(key, []) or []:
            if not isinstance(entry, dict):
                continue
            rel = str(entry.get("path", "")).strip().replace("\\", "/")
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                raise ValueError(f"Invalid dbt_project.{key} path: {rel!r}")
            content = entry.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            dest = project_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")


def _read_profile_name(project_root: Path) -> str:
    """Parse ``profile:`` from ``dbt_project.yml``."""
    p = project_root / "dbt_project.yml"
    if not p.is_file():
        return "debug_project"
    text = p.read_text(encoding="utf-8")
    m = re.search(r"^profile:\s*(\S+)", text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return "debug_project"


def _write_workspace_marker(workspace_root: Path, spec: dict[str, Any]) -> None:
    """Write a sentinel so cleanup only removes environment-owned temp dirs."""
    payload = {
        "kind": "dbt_debugger_workspace",
        "scenario_id": str(spec.get("scenario_id", "")),
        "schema_version": 1,
    }
    (workspace_root / _WORKSPACE_MARKER).write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _has_workspace_marker(workspace_root: Path) -> bool:
    """Return ``True`` when *workspace_root* looks like one of our temp dirs."""
    marker = workspace_root / _WORKSPACE_MARKER
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("kind") == "dbt_debugger_workspace"


def materialize_scenario_workspace(
    spec: dict[str, Any],
    parent_dir: Path | None = None,
) -> MaterializedWorkspace:
    """Write the dbt project, debug context, profile, and DuckDB tables for one rollout.

    Args:
        spec: Full scenario JSON (validated corpus object).
        parent_dir: Optional parent for the temp directory; defaults to system temp.

    Returns:
        Paths for project, hidden internals, and DuckDB.

    Raises:
        ValueError: If the spec cannot be materialized or sample_data cannot be mapped.
    """
    base = Path(
        tempfile.mkdtemp(prefix="dbt_debugger_", dir=str(parent_dir) if parent_dir else None)
    )
    try:
        internal = base / ".internal"
        internal.mkdir(parents=True, exist_ok=True)
        _write_workspace_marker(base, spec)
        project_root = base / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        context_root = project_root / "debug_context"
        profiles_dir = internal / "profiles"
        duckdb_path = internal / "rollout.duckdb"

        _write_project_files(project_root, spec)
        _write_context_files(context_root, spec)
        profile_name = _read_profile_name(project_root)
        _write_profiles_yml(profiles_dir, duckdb_path, profile_name)

        con = duckdb.connect(str(duckdb_path))
        try:
            _load_sample_tables(con, spec)
        finally:
            con.close()

        return MaterializedWorkspace(
            workspace_root=base,
            project_root=project_root,
            context_root=context_root,
            profiles_dir=profiles_dir,
            duckdb_path=duckdb_path,
        )
    except BaseException:
        shutil.rmtree(base, ignore_errors=True)
        raise


def cleanup_workspace(workspace_root: Path | str | None) -> CleanupResult:
    """Remove a rollout workspace recursively and surface cleanup failures.

    Args:
        workspace_root: Temp directory created for one rollout, or None/no-op.
    """
    if workspace_root is None:
        return CleanupResult(removed=True, message="No workspace root recorded")
    path = Path(workspace_root)
    if not path.exists():
        return CleanupResult(removed=True, message="Workspace already absent")
    if not path.is_dir():
        return CleanupResult(removed=False, message="Workspace root is not a directory")
    if not _has_workspace_marker(path):
        return CleanupResult(
            removed=False,
            message="Refusing to delete directory without dbt_debugger workspace marker",
        )
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return CleanupResult(
            removed=False,
            message=f"Workspace cleanup failed: {type(exc).__name__}: {exc}",
        )
    if path.exists():
        return CleanupResult(
            removed=False,
            message="Workspace cleanup returned without removing the directory",
        )
    return CleanupResult(removed=True, message="Workspace removed")


def build_rollout_state_paths(mw: MaterializedWorkspace) -> dict[str, Any]:
    """Populate ``vf.State`` keys under :class:`RolloutStateKeys` from a materialized workspace."""
    return {
        RolloutStateKeys.WORKSPACE_ROOT: str(mw.workspace_root.resolve()),
        RolloutStateKeys.PROJECT_ROOT: str(mw.project_root.resolve()),
        RolloutStateKeys.CONTEXT_ROOT: str(mw.context_root.resolve()),
        RolloutStateKeys.PROFILES_DIR: str(mw.profiles_dir.resolve()),
        RolloutStateKeys.DUCKDB_PATH: str(mw.duckdb_path.resolve()),
    }
