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

from runtime.types import DiagnosisSubmission, EvidenceRef, RolloutStateKeys

_ALLOWED_DBT_SUBCOMMANDS = frozenset(
    {"parse", "compile", "ls", "run", "test", "build"}
)
_ALLOWED_DBT_RESOURCE_TYPES = frozenset(
    {"model", "test", "source", "seed", "snapshot", "exposure"}
)
_RUN_HISTORY_RECORD_TYPES = frozenset({"summary", "model", "test", "warning"})
_EXTRA_READ_GLOBS = ("debug_context/**", "target/**", "logs/**")


def _dbt_argv(project_root: str, dbt_args: list[str]) -> list[str]:
    """Resolve how to invoke dbt: prefer ``dbt`` on PATH, else ``python -m dbt``."""
    exe = shutil.which("dbt")
    if exe:
        return [exe, *dbt_args, "--project-dir", project_root]
    return [sys.executable, "-m", "dbt", *dbt_args, "--project-dir", project_root]


def _append_trace(state_container: dict[str, Any] | None, entry: dict[str, Any]) -> None:
    """Append a bounded tool-trace entry for evaluator inspection."""
    if state_container is None:
        return
    trace = state_container.setdefault(RolloutStateKeys.TOOL_TRACE, [])
    if isinstance(trace, list) and len(trace) < 500:
        trace.append(entry)


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
        _append_trace(_state, {"tool": "list_files", "path": path, "max_entries": max_entries})
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
                rel = str(path_obj.resolve().relative_to(root.resolve())).replace("\\", "/")
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

    cmd = _dbt_argv(project_root, args)
    env = {**os.environ, "DBT_PROFILES_DIR": profiles_dir}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
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


def _validate_evidence_ref(raw_ref: Any) -> tuple[EvidenceRef | None, str | None]:
    """Validate one evidence reference encoded as a strict string."""
    if not isinstance(raw_ref, str) or not raw_ref.strip():
        return None, "evidence entries must be non-empty strings"
    parts = [part.strip() for part in raw_ref.split("|")]
    kind = parts[0].lower()
    if kind == "file_span":
        if len(parts) != 4:
            return None, "file_span evidence must be file_span|path|start_line|end_line"
        raw_path = parts[1]
        try:
            start_line = int(parts[2])
            end_line = int(parts[3])
        except ValueError:
            return None, "file_span start_line/end_line must be integers"
        if not raw_path:
            return None, "file_span evidence requires a non-empty path"
        if start_line < 1:
            return None, "file_span evidence requires start_line >= 1"
        if end_line < start_line:
            return None, "file_span evidence requires end_line >= start_line"
        return {
            "kind": "file_span",
            "path": _normalize_rel_path(raw_path),
            "start_line": start_line,
            "end_line": end_line,
        }, None
    if kind == "sample_rows":
        if len(parts) < 3:
            return None, (
                "sample_rows evidence must be "
                "sample_rows|table|match_json[|min_rows]"
            )
        raw_table = parts[1]
        try:
            min_rows = int(parts[-1])
            raw_match_json = "|".join(parts[2:-1])
        except ValueError:
            min_rows = 1
            raw_match_json = "|".join(parts[2:])
        if not raw_table:
            return None, "sample_rows evidence requires a non-empty table"
        match_json, match_err = _normalize_evidence_match(raw_match_json)
        if match_err is not None:
            return None, match_err
        if min_rows < 1:
            return None, "sample_rows evidence requires min_rows >= 1"
        return {
            "kind": "sample_rows",
            "table": raw_table,
            "match_json": match_json,
            "min_rows": min_rows,
        }, None
    if kind == "run_history":
        if len(parts) < 3:
            return None, (
                "run_history evidence must be run_history|record_type|..."
            )
        record_type = parts[1].lower()
        if record_type not in _RUN_HISTORY_RECORD_TYPES:
            return None, (
                f"run_history evidence requires record_type in "
                f"{sorted(_RUN_HISTORY_RECORD_TYPES)}"
            )
        out: EvidenceRef = {"kind": "run_history", "record_type": record_type}
        if record_type == "model":
            if len(parts) < 4:
                return None, "run_history model evidence must be run_history|model|model_name|status"
            model = parts[2]
            status = parts[3]
            if not model:
                return None, "run_history model evidence requires a non-empty model"
            out["model"] = model
            if status:
                out["status"] = status.lower()
            if len(parts) > 4 and parts[4]:
                out["contains"] = parts[4]
        elif record_type == "test":
            if len(parts) < 4:
                return None, "run_history test evidence must be run_history|test|name|status"
            name = parts[2]
            status = parts[3]
            if not name:
                return None, "run_history test evidence requires a non-empty name"
            out["name"] = name
            if status:
                out["status"] = status.lower()
            if len(parts) > 4 and parts[4]:
                out["contains"] = parts[4]
        elif record_type in {"summary", "warning"}:
            contains = "|".join(parts[2:])
            if not contains:
                return None, f"run_history {record_type} evidence requires contains"
            out["contains"] = contains
        return out, None
    return None, "unsupported evidence kind"


def _validate_diagnosis_payload(
    has_bug: bool,
    root_cause: str,
    affected_models: list[str],
    fix: str,
    evidence: list[str],
    *,
    valid_model_names: list[str],
) -> tuple[DiagnosisSubmission | None, str | None]:
    """Validate diagnosis shape without consulting evaluator-only answer fields."""
    rc = root_cause.strip()
    fx = fix.strip()
    if not rc or not fx:
        return None, "root_cause and fix must be non-empty strings"
    if not isinstance(affected_models, list):
        return None, "affected_models must be a list of model names"
    valid = set(valid_model_names)
    models: list[str] = []
    for raw_model in affected_models:
        if not isinstance(raw_model, str) or not raw_model.strip():
            return None, "affected_models must contain non-empty strings"
        model = raw_model.strip()
        if model not in valid:
            return None, f"Unknown model in affected_models: {model!r}"
        models.append(model)
    if not isinstance(evidence, list) or not evidence:
        return None, "evidence must be a non-empty list of structured citations"
    normalized_evidence: list[EvidenceRef] = []
    for idx, raw_ref in enumerate(evidence):
        evidence_ref, evidence_err = _validate_evidence_ref(raw_ref)
        if evidence_err is not None or evidence_ref is None:
            return None, f"evidence[{idx}]: {evidence_err}"
        normalized_evidence.append(evidence_ref)
    payload: DiagnosisSubmission = {
        "has_bug": bool(has_bug),
        "root_cause": rc,
        "affected_models": sorted(set(models)),
        "fix": fx,
        "evidence": normalized_evidence,
    }
    return payload, None


async def submit_diagnosis(
    has_bug: bool,
    root_cause: str,
    affected_models: list[str],
    fix: str,
    evidence: list[str],
    *,
    scenario_id: str = "",
    valid_model_names: list[str] | None = None,
    rollout_state: dict[str, Any] | None = None,
) -> str:
    """Submit a structured diagnosis for evaluator-only scoring.

    Args:
        has_bug: Whether the dbt project itself contains a bug.
        root_cause: Plain-language explanation of the primary cause.
        affected_models: dbt models directly affected by the diagnosis.
        fix: Plain-language remediation, or why no dbt fix is needed.
        evidence: One or more grounded citations encoded as strings. Supported shapes:
            ``file_span|models/x.sql|1|20``
            ``sample_rows|raw_orders|{"order_id":1001}|2``
            ``run_history|model|fct_orders|success``
            ``run_history|summary|All models succeeded``
    """
    state = rollout_state
    if state is None:
        return "Error: internal state missing"
    if state.get(RolloutStateKeys.SUBMITTED_DIAGNOSIS) is not None:
        return "Error: diagnosis already submitted"
    payload, err = _validate_diagnosis_payload(
        has_bug,
        root_cause,
        affected_models,
        fix,
        evidence,
        valid_model_names=valid_model_names or [],
    )
    if err is not None or payload is None:
        return f"Error: {err}"
    state[RolloutStateKeys.SUBMITTED_DIAGNOSIS] = dict(payload)
    _append_trace(state, {"tool": "submit_diagnosis", "scenario_id": scenario_id})
    return json.dumps(
        {"status": "accepted", "message": "Diagnosis stored for evaluator-only scoring."},
        indent=2,
    )
