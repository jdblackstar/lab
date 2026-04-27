"""Tool callables for ``StatefulToolEnv`` (filesystem, dbt, diagnosis)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any

from claim_text_matching import text_contains_option
from runtime.sample_rows import matching_sample_rows
from runtime.types import DiagnosisSubmission, EvidenceRef, RolloutStateKeys

_ALLOWED_DBT_SUBCOMMANDS = frozenset({"parse", "compile", "ls", "run", "test", "build"})
_ALLOWED_DBT_RESOURCE_TYPES = frozenset(
    {"model", "test", "source", "seed", "snapshot", "exposure"}
)
_RUN_HISTORY_RECORD_TYPES = frozenset({"summary", "model", "test", "warning"})
_EXTRA_READ_GLOBS = ("debug_context/**", "target/**", "logs/**")


def dbt_argv(project_root: str, dbt_args: list[str]) -> list[str]:
    """Build argv for invoking dbt: prefer ``dbt`` on PATH, else ``python -m dbt``.

    Used by ``run_dbt_command`` and by tests so compile smoke checks match runtime.
    """
    exe = shutil.which("dbt")
    if exe:
        return [exe, *dbt_args, "--project-dir", project_root]
    return [sys.executable, "-m", "dbt", *dbt_args, "--project-dir", project_root]


def _append_trace(
    state_container: dict[str, Any] | None, entry: dict[str, Any]
) -> None:
    """Append a bounded tool-trace entry for evaluator inspection."""
    if state_container is None:
        return
    trace = state_container.setdefault(RolloutStateKeys.TOOL_TRACE, [])
    if isinstance(trace, list) and len(trace) < 500:
        trace.append(entry)


def _collected_evidence_list(state_container: dict[str, Any]) -> list[EvidenceRef]:
    """Return the rollout-local evidence list, creating it when missing."""
    evidence = state_container.setdefault(RolloutStateKeys.COLLECTED_EVIDENCE, [])
    if not isinstance(evidence, list):
        evidence = []
        state_container[RolloutStateKeys.COLLECTED_EVIDENCE] = evidence
    return evidence


def _append_collected_evidence(
    state_container: dict[str, Any],
    evidence_ref: EvidenceRef,
) -> tuple[int, bool]:
    """Store one normalized evidence ref unless it is already present."""
    evidence = _collected_evidence_list(state_container)
    encoded = json.dumps(evidence_ref, sort_keys=True)
    for idx, existing in enumerate(evidence):
        if isinstance(existing, dict) and json.dumps(existing, sort_keys=True) == encoded:
            return idx, False
    evidence.append(dict(evidence_ref))
    return len(evidence) - 1, True


def _tool_error(message: str) -> str:
    """Return one normalized tool error string."""
    return f"Error: {message}"


def _json_tool_response(
    *,
    status: str,
    message: str,
    evidence_ref: EvidenceRef | None = None,
    evidence_count: int | None = None,
    added: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Render one structured tool response for evidence-collection helpers."""
    payload: dict[str, Any] = {"status": status, "message": message}
    if evidence_ref is not None:
        payload["evidence"] = evidence_ref
    if evidence_count is not None:
        payload["evidence_count"] = evidence_count
    if added is not None:
        payload["added"] = added
    if extra:
        payload.update(extra)
    return json.dumps(payload, indent=2, sort_keys=True)


def _normalize_rel_path(path: str) -> str:
    """Return a POSIX relative path with no leading ``./`` or ``..`` segments."""
    p = path.strip().replace("\\", "/").lstrip("/")
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError("Path must not contain '..'")
        parts.append(seg)
    return "/".join(parts)


@lru_cache(maxsize=512)
def _path_segments(path: str) -> tuple[str, ...]:
    """Return normalized POSIX path segments for glob matching."""
    normalized = _normalize_rel_path(path)
    if not normalized:
        return ()
    return tuple(seg for seg in normalized.split("/") if seg)


@lru_cache(maxsize=512)
def _glob_segments(pattern: str) -> tuple[str, ...]:
    """Return normalized glob pattern segments."""
    cleaned = pattern.replace("\\", "/").strip().lstrip("/")
    if not cleaned:
        return ()
    return tuple(seg for seg in cleaned.split("/") if seg not in ("", "."))


def _glob_matches_segments(
    path_segments: tuple[str, ...],
    pattern_segments: tuple[str, ...],
) -> bool:
    """Return ``True`` when *path_segments* match *pattern_segments*."""
    memo: dict[tuple[int, int], bool] = {}

    def _match(path_idx: int, pat_idx: int) -> bool:
        key = (path_idx, pat_idx)
        if key in memo:
            return memo[key]
        if pat_idx == len(pattern_segments):
            result = path_idx == len(path_segments)
        else:
            token = pattern_segments[pat_idx]
            if token == "**":
                if _match(path_idx, pat_idx + 1):
                    result = True
                elif path_idx < len(path_segments):
                    result = _match(path_idx + 1, pat_idx)
                else:
                    result = False
            elif path_idx >= len(path_segments):
                result = False
            elif fnmatchcase(path_segments[path_idx], token):
                result = _match(path_idx + 1, pat_idx + 1)
            else:
                result = False
        memo[key] = result
        return result

    return _match(0, 0)


def _path_matches_globs(rel_posix: str, globs: list[str]) -> bool:
    """Return ``True`` if *rel_posix* matches any manifest glob with real ``**`` semantics."""
    path_segments = _path_segments(rel_posix)
    for raw in globs:
        pattern = raw.replace("\\", "/").strip()
        if not pattern:
            continue
        if _glob_matches_segments(path_segments, _glob_segments(pattern)):
            return True
    return False


def _effective_read_globs(tool_visible_globs: list[str]) -> list[str]:
    """Extend manifest read globs with rollout debug artifacts."""
    return list(tool_visible_globs) + list(_EXTRA_READ_GLOBS)


def _resolve_under_root(rel: str, project_root: Path) -> Path:
    """Resolve a project-relative path while preventing root escape."""
    rel_n = _normalize_rel_path(rel)
    if not rel_n:
        return project_root.resolve()
    candidate = (project_root / rel_n).resolve()
    root = project_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path escapes project root") from exc
    return candidate


def _is_immutable(rel_posix: str, immutable_paths: list[str]) -> bool:
    """Return whether *rel_posix* is immutable under the manifest."""
    return rel_posix in immutable_paths


async def list_files(
    path: str = ".",
    max_entries: int = 200,
    *,
    project_root: str = "",
    tool_visible_globs: list[str] | None = None,
    immutable_paths: list[str] | None = None,
    _state: dict[str, Any] | None = None,
) -> str:
    """List files under *path* (project-relative). Hidden internal paths are never visible."""
    globs = ["**/*"] if tool_visible_globs is None else list(tool_visible_globs)
    imm = immutable_paths or []
    root = Path(project_root)
    if not root.is_dir():
        return "Error: invalid project_root"

    def _run() -> str:
        try:
            base = _resolve_under_root(path, root)
        except ValueError as exc:
            return f"Error: {exc}"
        if not base.exists():
            return f"Error: path not found: {path!r}"
        root_r = root.resolve()
        rel_base = str(base.resolve().relative_to(root_r)).replace("\\", "/")
        if base.is_file():
            if not _path_matches_globs(rel_base, globs):
                return "Error: path not allowed by artifact manifest"
            tag = " [immutable]" if _is_immutable(rel_base, imm) else ""
            return f"FILE {rel_base}{tag}"
        entries: list[str] = []
        count = 0
        for dirpath, dirnames, filenames in os.walk(base, topdown=True):
            dirnames.sort()
            filenames.sort()
            rel_dir = os.path.relpath(dirpath, root_r).replace("\\", "/")
            if rel_dir in (".", ""):
                rel_dir = ""
            for name in dirnames:
                if count >= max_entries:
                    return "\n".join(
                        entries + [f"... truncated after {max_entries} entries"]
                    )
                rel = f"{rel_dir}/{name}".strip("/") if rel_dir else name
                if _path_matches_globs(rel, globs):
                    tag = " [immutable]" if _is_immutable(rel, imm) else ""
                    entries.append(f"DIR  {rel}{tag}")
                    count += 1
            for name in filenames:
                if count >= max_entries:
                    return "\n".join(
                        entries + [f"... truncated after {max_entries} entries"]
                    )
                rel = f"{rel_dir}/{name}".strip("/") if rel_dir else name
                if _path_matches_globs(rel, globs):
                    tag = " [immutable]" if _is_immutable(rel, imm) else ""
                    entries.append(f"FILE {rel}{tag}")
                    count += 1
        return "\n".join(entries) if entries else "(empty)"

    result = await asyncio.to_thread(_run)
    if not result.startswith("Error:"):
        _append_trace(
            _state, {"tool": "list_files", "path": path, "max_entries": max_entries}
        )
    return result


async def read_file(
    path: str,
    start_line: int = 1,
    end_line: int = 220,
    *,
    project_root: str = "",
    tool_visible_globs: list[str] | None = None,
    immutable_paths: list[str] | None = None,
    _state: dict[str, Any] | None = None,
) -> str:
    """Read a text file with line numbers (1-based inclusive range)."""
    base = ["**/*"] if tool_visible_globs is None else list(tool_visible_globs)
    globs = _effective_read_globs(base)
    imm = immutable_paths or []
    root = Path(project_root)

    def _run() -> tuple[str, str | None]:
        try:
            target = _resolve_under_root(path, root)
        except ValueError as exc:
            return f"Error: {exc}", None
        if not target.is_file():
            return f"Error: not a file: {path!r}", None
        rel = str(target.resolve().relative_to(root.resolve())).replace("\\", "/")
        if not _path_matches_globs(rel, globs):
            return "Error: path not allowed for read", None
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Error: cannot read file: {exc}", None
        lines = text.splitlines()
        start = max(1, start_line)
        end = max(start, end_line)
        chunk = lines[start - 1 : end]
        out = [f"{i + start}| {line}" for i, line in enumerate(chunk)]
        imm_tag = " [immutable source]" if _is_immutable(rel, imm) else ""
        if not chunk:
            n = len(lines)
            header = (
                f"# {rel}{imm_tag} (no lines in range; file has {n} line(s); "
                f"requested {start}-{end})\n"
            )
        else:
            last_shown = min(end, start + len(chunk) - 1)
            header = f"# {rel}{imm_tag} (lines {start}-{last_shown})\n"
        return header + "\n".join(out), rel

    result, rel = await asyncio.to_thread(_run)
    if rel is not None:
        _append_trace(
            _state,
            {
                "tool": "read_file",
                "path": rel,
                "start_line": max(1, start_line),
                "end_line": max(max(1, start_line), end_line),
            },
        )
    return result


async def search_project(
    pattern: str,
    glob_pattern: str = "**/*",
    max_matches: int = 50,
    *,
    project_root: str = "",
    tool_visible_globs: list[str] | None = None,
    immutable_paths: list[str] | None = None,
    _state: dict[str, Any] | None = None,
) -> str:
    """Search file contents under the project (regex *pattern*)."""
    _ = immutable_paths
    if not pattern.strip():
        return "Error: empty pattern"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex: {exc}"
    base = ["**/*"] if tool_visible_globs is None else list(tool_visible_globs)
    globs = _effective_read_globs(base)
    root = Path(project_root)

    def _run() -> str:
        matches: list[str] = []
        count = 0
        for path_obj in root.rglob("*"):
            if not path_obj.is_file():
                continue
            try:
                rel = str(path_obj.resolve().relative_to(root.resolve())).replace(
                    "\\", "/"
                )
            except ValueError:
                continue
            if not _path_matches_globs(rel, globs):
                continue
            if not _path_matches_globs(rel, [glob_pattern]):
                continue
            try:
                text = path_obj.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{rel}:{line_number}:{line[:500]}")
                    count += 1
                    if count >= max_matches:
                        return "\n".join(
                            matches + [f"... truncated after {max_matches} matches"]
                        )
        return "\n".join(matches) if matches else "(no matches)"

    result = await asyncio.to_thread(_run)
    if not result.startswith("Error:"):
        _append_trace(
            _state,
            {
                "tool": "search_project",
                "pattern": pattern,
                "glob_pattern": glob_pattern,
                "max_matches": max_matches,
            },
        )
    return result


def _normalize_selectors(values: list[str] | None) -> tuple[list[str], str | None]:
    """Validate dbt selectors to prevent prompt-controlled option injection."""
    if values is None:
        return [], None
    if not isinstance(values, list):
        return [], "selectors must be a list of strings"
    out: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            return [], "selectors must be a list of strings"
        value = raw.strip()
        if not value:
            continue
        if value.startswith("-"):
            return [], f"selector values must not start with '-': {value!r}"
        out.append(value)
    return out, None


def _normalize_resource_types(values: list[str] | None) -> tuple[list[str], str | None]:
    """Validate ``dbt ls`` resource-type filters against an allowlist."""
    if values is None:
        return [], None
    if not isinstance(values, list):
        return [], "resource_types must be a list of strings"
    out: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            return [], "resource_types must be a list of strings"
        value = raw.strip().lower()
        if not value:
            continue
        if value not in _ALLOWED_DBT_RESOURCE_TYPES:
            return [], (
                f"disallowed resource_type {value!r}; "
                f"allowed={sorted(_ALLOWED_DBT_RESOURCE_TYPES)}"
            )
        out.append(value)
    return out, None


async def run_dbt_command(
    subcommand: str,
    select: list[str] | None = None,
    exclude: list[str] | None = None,
    resource_types: list[str] | None = None,
    full_refresh: bool = False,
    fail_fast: bool = False,
    timeout_seconds: int = 120,
    *,
    project_root: str = "",
    profiles_dir: str = "",
    duckdb_path: str = "",
    _state: dict[str, Any] | None = None,
) -> str:
    """Run a restricted ``dbt`` command without exposing arbitrary CLI flags.

    Args:
        subcommand: One of ``parse``, ``compile``, ``ls``/``list``, ``run``, ``test``, or ``build``.
        select: Optional dbt selectors passed after ``--select``.
        exclude: Optional dbt selectors passed after ``--exclude``.
        resource_types: Optional resource-type filters for ``ls``.
        full_refresh: Only valid for ``run`` or ``build``.
        fail_fast: Only valid for ``run``, ``test``, or ``build``.
        timeout_seconds: Subprocess timeout in seconds.
    """
    _ = duckdb_path
    sub = subcommand.lower().strip()
    if sub == "list":
        sub = "ls"
    if sub not in _ALLOWED_DBT_SUBCOMMANDS:
        return (
            f"Error: disallowed dbt subcommand {sub!r}; "
            f"allowed={sorted(_ALLOWED_DBT_SUBCOMMANDS)}"
        )
    selected, select_err = _normalize_selectors(select)
    if select_err is not None:
        return f"Error: {select_err}"
    excluded, exclude_err = _normalize_selectors(exclude)
    if exclude_err is not None:
        return f"Error: {exclude_err}"
    rtypes, rtype_err = _normalize_resource_types(resource_types)
    if rtype_err is not None:
        return f"Error: {rtype_err}"
    if full_refresh and sub not in {"run", "build"}:
        return "Error: full_refresh is only supported for run/build"
    if fail_fast and sub not in {"run", "test", "build"}:
        return "Error: fail_fast is only supported for run/test/build"
    if rtypes and sub != "ls":
        return "Error: resource_types is only supported for ls/list"

    args: list[str] = [sub]
    if selected:
        args.extend(["--select", *selected])
    if excluded:
        args.extend(["--exclude", *excluded])
    if rtypes:
        for value in rtypes:
            args.extend(["--resource-type", value])
    if full_refresh:
        args.append("--full-refresh")
    if fail_fast:
        args.append("--fail-fast")

    cmd = dbt_argv(project_root, args)
    env = {**os.environ, "DBT_PROFILES_DIR": profiles_dir}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        out_bytes, _ = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: dbt timed out after {timeout_seconds}s"
    text = out_bytes.decode("utf-8", errors="replace")
    status = proc.returncode if proc.returncode is not None else -1
    result = f"exit_code={status}\n{text[-40000:]}"
    if status == 0:
        _append_trace(
            _state,
            {
                "tool": "run_dbt_command",
                "subcommand": sub,
                "select": selected,
                "exclude": excluded,
                "resource_types": rtypes,
                "full_refresh": full_refresh,
                "fail_fast": fail_fast,
            },
        )
    return result


async def read_artifact(
    path: str,
    start_line: int = 1,
    end_line: int = 220,
    *,
    project_root: str = "",
    tool_visible_globs: list[str] | None = None,
    _state: dict[str, Any] | None = None,
) -> str:
    """Read logs or ``target/`` artifacts (plus normal project files allowed by globs)."""
    return await read_file(
        path,
        start_line=start_line,
        end_line=end_line,
        project_root=project_root,
        tool_visible_globs=tool_visible_globs,
        immutable_paths=[],
        _state=_state,
    )


def _file_evidence_guidance(rel_path: str) -> str | None:
    """Return a remediation hint when a path is not valid ``file_span`` evidence."""
    if rel_path == "debug_context/run_history.json":
        return (
            "Use add_run_history_evidence(...) for facts from "
            "debug_context/run_history.json."
        )
    if rel_path == "debug_context/sample_data.json":
        return (
            "Use add_sample_rows_evidence(...) for facts from "
            "debug_context/sample_data.json."
        )
    if rel_path.startswith("debug_context/"):
        return (
            "Only project files can be stored with add_file_evidence(...). "
            "Use add_sample_rows_evidence(...) or add_run_history_evidence(...) "
            "for debug_context facts."
        )
    if rel_path.startswith("target/") or rel_path.startswith("logs/"):
        return (
            "Artifacts under target/ or logs/ are not valid file evidence. "
            "Cite the underlying project file, sample rows, or run history fact instead."
        )
    return None


def _scalar_json_object(match_json: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse *match_json* into a non-empty scalar-valued object."""
    normalized, err = _normalize_evidence_match(match_json)
    if err is not None or normalized is None:
        return None, err
    parsed = json.loads(normalized)
    assert isinstance(parsed, dict)
    return parsed, None


def _run_history_record_matches(
    record: dict[str, Any],
    *,
    name_key: str,
    expected_name: str,
    expected_status: str,
    expected_contains: str,
) -> bool:
    """Return whether one run-history record matches the requested filters."""
    record_name = str(record.get(name_key, "")).strip()
    if expected_name and record_name != expected_name:
        return False
    record_status = str(record.get("status", "")).strip().lower()
    if expected_status and record_status != expected_status:
        return False
    if expected_contains and not text_contains_option(
        json.dumps(record, sort_keys=True),
        expected_contains,
    ):
        return False
    return True


async def add_file_evidence(
    path: str,
    start_line: int,
    end_line: int,
    *,
    project_root: str = "",
    rollout_state: dict[str, Any] | None = None,
) -> str:
    """Store one project-file citation for the final diagnosis.

    Args:
        path: Project-relative file path, such as ``models/intermediate/x.sql``.
        start_line: 1-based start line (inclusive).
        end_line: 1-based end line (inclusive).
    """
    state = rollout_state
    if state is None:
        return _tool_error("internal state missing")
    if start_line < 1:
        return _tool_error("start_line must be >= 1")
    if end_line < start_line:
        return _tool_error("end_line must be >= start_line")
    root = Path(project_root)
    if not root.is_dir():
        return _tool_error("invalid project_root")

    try:
        target = _resolve_under_root(path, root)
    except ValueError as exc:
        return _tool_error(str(exc))
    if not target.is_file():
        return _tool_error(f"not a file: {path!r}")

    rel = str(target.resolve().relative_to(root.resolve())).replace("\\", "/")
    guidance = _file_evidence_guidance(rel)
    if guidance is not None:
        return _tool_error(guidance)

    try:
        line_count = len(target.read_text(encoding="utf-8").splitlines())
    except OSError as exc:
        return _tool_error(f"cannot read file: {exc}")
    if line_count < 1:
        return _tool_error(f"file is empty: {rel!r}")
    if start_line > line_count:
        return _tool_error(
            f"start_line {start_line} exceeds file length ({line_count} line(s))"
        )
    clipped_end = min(end_line, line_count)
    evidence_ref: EvidenceRef = {
        "kind": "file_span",
        "path": rel,
        "start_line": start_line,
        "end_line": clipped_end,
    }
    index, added = _append_collected_evidence(state, evidence_ref)
    _append_trace(
        state,
        {
            "tool": "add_file_evidence",
            "path": rel,
            "start_line": start_line,
            "end_line": clipped_end,
            "added": added,
        },
    )
    line_note = ""
    if clipped_end != end_line:
        line_note = (
            f" Requested end_line {end_line} exceeded file length, so it was "
            f"clipped to {clipped_end}."
        )
    return _json_tool_response(
        status="accepted",
        message=(
            f"Stored file evidence for {rel} lines {start_line}-{clipped_end}."
            f"{line_note}"
        ),
        evidence_ref=evidence_ref,
        evidence_count=index + 1 if added else len(_collected_evidence_list(state)),
        added=added,
    )


async def add_sample_rows_evidence(
    table: str,
    match_json: str,
    min_rows: int = 1,
    *,
    rollout_state: dict[str, Any] | None = None,
) -> str:
    """Store one sample-row citation for the final diagnosis.

    Args:
        table: Sample table key from ``debug_context/sample_data.json``.
        match_json: JSON object selecting one or more rows, for example
            ``{"order_id": 1001}``.
        min_rows: Minimum number of matching rows expected.
    """
    state = rollout_state
    if state is None:
        return _tool_error("internal state missing")
    if min_rows < 1:
        return _tool_error("min_rows must be >= 1")

    spec = state.get(RolloutStateKeys.SCENARIO_SPEC) or {}
    sample_data = spec.get("sample_data") if isinstance(spec, dict) else None
    if not isinstance(sample_data, dict):
        return _tool_error("sample_data is unavailable for this rollout")
    table_obj = sample_data.get(table)
    if not isinstance(table_obj, dict):
        available = sorted(str(name) for name in sample_data.keys())
        return _tool_error(
            f"unknown sample_data table {table!r}. Available tables: {available!r}"
        )

    match_obj, err = _scalar_json_object(match_json)
    if err is not None or match_obj is None:
        return _tool_error(err or "invalid match_json")

    matched_rows = matching_sample_rows(table_obj, match_obj)
    if len(matched_rows) < min_rows:
        return _tool_error(
            f"sample_rows match returned {len(matched_rows)} row(s) in {table!r}; "
            f"need at least {min_rows}"
        )

    normalized_match_json = json.dumps(match_obj, sort_keys=True)
    evidence_ref: EvidenceRef = {
        "kind": "sample_rows",
        "table": table,
        "match_json": normalized_match_json,
        "min_rows": min_rows,
    }
    index, added = _append_collected_evidence(state, evidence_ref)
    preview_rows = matched_rows[: min(3, len(matched_rows))]
    _append_trace(
        state,
        {
            "tool": "add_sample_rows_evidence",
            "table": table,
            "match_json": normalized_match_json,
            "min_rows": min_rows,
            "added": added,
        },
    )
    return _json_tool_response(
        status="accepted",
        message=(
            f"Stored sample_rows evidence for {table!r}; "
            f"{len(matched_rows)} matching row(s)."
        ),
        evidence_ref=evidence_ref,
        evidence_count=index + 1 if added else len(_collected_evidence_list(state)),
        added=added,
        extra={"matched_rows": len(matched_rows), "preview_rows": preview_rows},
    )


async def add_run_history_evidence(
    record_type: str,
    model: str = "",
    name: str = "",
    status: str = "",
    contains: str = "",
    *,
    valid_model_names: list[str] | None = None,
    rollout_state: dict[str, Any] | None = None,
) -> str:
    """Store one run-history citation for the final diagnosis.

    Args:
        record_type: One of ``summary``, ``model``, ``test``, or ``warning``.
        model: Model name for ``record_type="model"``.
        name: Test name for ``record_type="test"``.
        status: Optional status filter, such as ``success`` or ``passed``.
        contains: Optional snippet expected to appear in the matching record.
    """
    state = rollout_state
    if state is None:
        return _tool_error("internal state missing")

    rtype = record_type.strip().lower()
    if rtype not in _RUN_HISTORY_RECORD_TYPES:
        return _tool_error(
            f"record_type must be one of {sorted(_RUN_HISTORY_RECORD_TYPES)!r}"
        )

    spec = state.get(RolloutStateKeys.SCENARIO_SPEC) or {}
    run_history = spec.get("run_history") if isinstance(spec, dict) else None
    if not isinstance(run_history, dict):
        return _tool_error("run_history is unavailable for this rollout")

    normalized_status = status.strip().lower()
    normalized_contains = contains.strip()
    evidence_ref: EvidenceRef = {"kind": "run_history", "record_type": rtype}
    match_summary: dict[str, Any] = {}

    if rtype == "summary":
        if not normalized_contains:
            return _tool_error("summary evidence requires contains")
        summary = str(run_history.get("summary", ""))
        if not text_contains_option(summary, normalized_contains):
            return _tool_error(
                f"run_history.summary does not contain {normalized_contains!r}"
            )
        evidence_ref["contains"] = normalized_contains
        match_summary["matched_summary"] = summary
    elif rtype == "warning":
        if not normalized_contains:
            return _tool_error("warning evidence requires contains")
        warnings = [
            str(item)
            for item in run_history.get("warnings", [])
            if isinstance(item, str)
        ]
        matched_warning = next(
            (
                warning
                for warning in warnings
                if text_contains_option(warning, normalized_contains)
            ),
            None,
        )
        if matched_warning is None:
            return _tool_error(
                f"no run_history warning contains {normalized_contains!r}"
            )
        evidence_ref["contains"] = normalized_contains
        match_summary["matched_warning"] = matched_warning
    elif rtype == "model":
        normalized_model = model.strip()
        if not normalized_model:
            return _tool_error("model evidence requires model")
        valid = set(valid_model_names or [])
        if valid and normalized_model not in valid:
            return _tool_error(f"unknown model {normalized_model!r}")
        records = run_history.get("model_results") or []
        matched_record = next(
            (
                record
                for record in records
                if isinstance(record, dict)
                and _run_history_record_matches(
                    record,
                    name_key="model",
                    expected_name=normalized_model,
                    expected_status=normalized_status,
                    expected_contains=normalized_contains,
                )
            ),
            None,
        )
        if matched_record is None:
            return _tool_error(
                f"no run_history model result matches model={normalized_model!r}, "
                f"status={normalized_status or '*'}"
                + (
                    f", contains={normalized_contains!r}"
                    if normalized_contains
                    else ""
                )
            )
        evidence_ref["model"] = normalized_model
        if normalized_status:
            evidence_ref["status"] = normalized_status
        if normalized_contains:
            evidence_ref["contains"] = normalized_contains
        match_summary["matched_record"] = matched_record
    else:
        normalized_name = name.strip()
        if not normalized_name:
            return _tool_error("test evidence requires name")
        records = run_history.get("tests") or []
        matched_record = next(
            (
                record
                for record in records
                if isinstance(record, dict)
                and _run_history_record_matches(
                    record,
                    name_key="name",
                    expected_name=normalized_name,
                    expected_status=normalized_status,
                    expected_contains=normalized_contains,
                )
            ),
            None,
        )
        if matched_record is None:
            return _tool_error(
                f"no run_history test result matches name={normalized_name!r}, "
                f"status={normalized_status or '*'}"
                + (
                    f", contains={normalized_contains!r}"
                    if normalized_contains
                    else ""
                )
            )
        evidence_ref["name"] = normalized_name
        if normalized_status:
            evidence_ref["status"] = normalized_status
        if normalized_contains:
            evidence_ref["contains"] = normalized_contains
        match_summary["matched_record"] = matched_record

    index, added = _append_collected_evidence(state, evidence_ref)
    _append_trace(
        state,
        {
            "tool": "add_run_history_evidence",
            "record_type": rtype,
            "added": added,
            **{
                key: value
                for key, value in evidence_ref.items()
                if key not in {"kind", "record_type"}
            },
        },
    )
    return _json_tool_response(
        status="accepted",
        message=f"Stored run_history evidence for record_type={rtype!r}.",
        evidence_ref=evidence_ref,
        evidence_count=index + 1 if added else len(_collected_evidence_list(state)),
        added=added,
        extra=match_summary,
    )


async def list_collected_evidence(
    *,
    rollout_state: dict[str, Any] | None = None,
) -> str:
    """List all evidence refs currently stored for the rollout."""
    state = rollout_state
    if state is None:
        return _tool_error("internal state missing")
    evidence = _collected_evidence_list(state)
    return json.dumps(
        {
            "status": "ok",
            "evidence_count": len(evidence),
            "evidence": evidence,
        },
        indent=2,
        sort_keys=True,
    )


def _is_scalar(value: Any) -> bool:
    """Return ``True`` for JSON-like scalar values used in evidence row matches."""
    return isinstance(value, (str, int, float, bool)) or value is None


def _normalize_evidence_match(raw_match_json: str) -> tuple[str | None, str | None]:
    """Validate and normalize a sample-row match JSON string."""
    if not isinstance(raw_match_json, str) or not raw_match_json.strip():
        return None, "sample_rows evidence requires non-empty match_json"
    try:
        raw_match = json.loads(raw_match_json)
    except json.JSONDecodeError as exc:
        return None, f"match_json must be valid JSON: {exc}"
    if not isinstance(raw_match, dict) or not raw_match:
        return None, "match_json must decode to a non-empty object"
    out: dict[str, Any] = {}
    for raw_key, raw_value in raw_match.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            return None, "match_json keys must be non-empty strings"
        if not _is_scalar(raw_value):
            return None, "match_json values must be JSON scalar values"
        out[raw_key.strip()] = raw_value
    return json.dumps(out, sort_keys=True), None


def _validate_diagnosis_payload(
    has_bug: bool,
    root_cause: str,
    buggy_models: list[str],
    fix: str,
    evidence: list[EvidenceRef],
    *,
    valid_model_names: list[str],
) -> tuple[DiagnosisSubmission | None, str | None]:
    """Validate diagnosis shape using already-collected normalized evidence refs."""
    rc = root_cause.strip()
    fx = fix.strip()
    if not rc or not fx:
        return None, "root_cause and fix must be non-empty strings"
    if not isinstance(buggy_models, list):
        return None, "buggy_models must be a list of model names"
    valid = set(valid_model_names)
    models: list[str] = []
    for raw_model in buggy_models:
        if not isinstance(raw_model, str) or not raw_model.strip():
            return None, "buggy_models must contain non-empty strings"
        model = raw_model.strip()
        if model not in valid:
            return None, f"Unknown model in buggy_models: {model!r}"
        models.append(model)
    if not has_bug and models:
        return (
            None,
            "When has_bug is false, buggy_models must be empty (no dbt defect to fix).",
        )
    if not isinstance(evidence, list) or not evidence:
        return None, (
            "no evidence collected. Use add_file_evidence(...), "
            "add_sample_rows_evidence(...), or add_run_history_evidence(...) first."
        )
    normalized_evidence: list[EvidenceRef] = []
    for idx, raw_ref in enumerate(evidence):
        if not isinstance(raw_ref, dict) or not str(raw_ref.get("kind", "")).strip():
            return None, f"internal evidence[{idx}] is malformed"
        normalized_evidence.append(dict(raw_ref))
    payload: DiagnosisSubmission = {
        "has_bug": bool(has_bug),
        "root_cause": rc,
        "buggy_models": sorted(set(models)),
        "fix": fx,
        "evidence": normalized_evidence,
    }
    return payload, None


async def submit_diagnosis(
    has_bug: bool,
    root_cause: str,
    buggy_models: list[str],
    fix: str,
    *,
    scenario_id: str = "",
    valid_model_names: list[str] | None = None,
    rollout_state: dict[str, Any] | None = None,
) -> str:
    """Submit a structured diagnosis for evaluator-only scoring.

    Args:
        has_bug: Whether the dbt project itself contains a defect requiring a code change.
        root_cause: Plain-language explanation of the primary cause.
        buggy_models: Models that must change to fix a real bug. Must be ``[]`` when
            ``has_bug`` is false (false alarm / semantics / BI-only cases).
        fix: Plain-language remediation, or ``No fix needed — ...`` when there is no dbt bug.
            Evidence is collected beforehand with ``add_file_evidence(...)``,
            ``add_sample_rows_evidence(...)``, and ``add_run_history_evidence(...)``.
    """
    state = rollout_state
    if state is None:
        return "Error: internal state missing"
    if state.get(RolloutStateKeys.SUBMITTED_DIAGNOSIS) is not None:
        return "Error: diagnosis already submitted"
    evidence = _collected_evidence_list(state)
    payload, err = _validate_diagnosis_payload(
        has_bug,
        root_cause,
        buggy_models,
        fix,
        evidence,
        valid_model_names=valid_model_names or [],
    )
    if err is not None or payload is None:
        return f"Error: {err}"
    state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] = dict(payload)
    _append_trace(state, {"tool": "submit_diagnosis", "scenario_id": scenario_id})
    return json.dumps(
        {
            "status": "accepted",
            "message": "Diagnosis stored for evaluator-only scoring.",
        },
        indent=2,
    )
