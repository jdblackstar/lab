"""Per-rollout dbt workspace and the model-visible debugging tools, served over MCP.

One server runs per rollout (constructed in ``DbtDebuggerTask.toolsets``). Its
``setup_task`` materializes the scenario's dbt + DuckDB workspace; paths, globs, and the
scenario spec stay in ``Workspace`` inside this process and never reach the tool schemas.
Evidence, the submitted diagnosis, and the tool trace live in ``DbtDebuggerState``, which
verifiers syncs with the host around every tool call so the task can stop and score on it.

Tool docstrings become the MCP tool descriptions and ``Annotated[..., Field(...)]``
parameters become the schemas, so this module must not use
``from __future__ import annotations``.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

import verifiers.v1 as vf
from dbt_debugger.evidence import (
    RECORD_NAME_KEY,
    RUN_HISTORY_RECORD_TYPES,
    entry_matches,
    parse_match_json,
    run_history_entries,
)
from dbt_debugger.paths import (
    effective_read_globs,
    globs_for_list_and_search,
    path_matches_globs,
    resolve_under_root,
)
from dbt_debugger.sample_rows import matching_sample_rows
from dbt_debugger.scenarios import load_scenario_spec, model_names
from dbt_debugger.workspace import cleanup_workspace, materialize_scenario_workspace

if TYPE_CHECKING:
    from dbt_debugger.taskset import DbtDebuggerData

logger = logging.getLogger(__name__)

_ALLOWED_DBT_SUBCOMMANDS = frozenset({"parse", "compile", "ls", "run", "test", "build"})
_ALLOWED_DBT_RESOURCE_TYPES = frozenset(
    {"model", "test", "source", "seed", "snapshot", "exposure"}
)
_MAX_TRACE_ENTRIES = 500


def dbt_argv(project_root: str, dbt_args: list[str]) -> list[str]:
    """Build argv for invoking dbt from the running interpreter's environment.

    Prefer the ``dbt`` script installed next to ``sys.executable`` (the tool server runs
    as ``python -m`` without an activated venv), then ``dbt`` on ``PATH``, then dbt's
    console entry point through the interpreter. Tests use it too, so compile smoke
    checks match runtime.
    """
    sibling = Path(sys.executable).parent / "dbt"
    exe = str(sibling) if sibling.is_file() else shutil.which("dbt")
    if exe:
        return [exe, *dbt_args, "--project-dir", project_root]
    return [
        sys.executable,
        "-c",
        "from dbt.cli.main import cli; cli()",
        *dbt_args,
        "--project-dir",
        project_root,
    ]


class DbtDebuggerState(vf.State):
    """Rollout state shared by the tool server (writes) and the task (stop + scoring)."""

    collected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    """Normalized evidence refs stored by the ``add_*_evidence`` tools."""
    submitted_diagnosis: dict[str, Any] | None = None
    """The accepted ``submit_diagnosis`` payload; set once, ends the rollout."""
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    """Bounded log of successful tool calls, for inspection."""


@dataclass(frozen=True)
class Workspace:
    """Server-local context for this rollout's scenario; never sent to the model."""

    scenario_id: str
    spec: dict[str, Any]
    project_root: str
    profiles_dir: str
    tool_visible_globs: list[str]
    immutable_paths: list[str]
    valid_model_names: list[str]


def _remove_workspace(workspace_root: Path) -> None:
    result = cleanup_workspace(workspace_root)
    if not result.removed:
        logger.warning("dbt-debugger workspace cleanup: %s", result.message)


def _selectors(values: list[str] | None) -> list[str]:
    """Validate dbt selectors to prevent prompt-controlled option injection."""
    out = [value.strip() for value in values or [] if value.strip()]
    for value in out:
        if value.startswith("-"):
            raise ValueError(f"selector values must not start with '-': {value!r}")
    return out


def _resource_types(values: list[str] | None) -> list[str]:
    """Validate ``dbt ls`` resource-type filters against an allowlist."""
    out = [value.strip().lower() for value in values or [] if value.strip()]
    for value in out:
        if value not in _ALLOWED_DBT_RESOURCE_TYPES:
            raise ValueError(
                f"disallowed resource_type {value!r}; "
                f"allowed={sorted(_ALLOWED_DBT_RESOURCE_TYPES)}"
            )
    return out


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
    if rel_path.startswith(("target/", "logs/")):
        return (
            "Artifacts under target/ or logs/ are not valid file evidence. "
            "Cite the underlying project file, sample rows, or run history fact instead."
        )
    return None


class DbtDebuggerToolset(vf.Toolset[vf.ToolsetConfig, DbtDebuggerState]):
    TOOL_PREFIX = None
    """Advertise the tool names verbatim; the prompt refers to them by name."""

    _workspace: Workspace | None = None

    async def setup_task(self, task: "DbtDebuggerData") -> None:
        spec = load_scenario_spec(task.scenario_id)
        materialized = await asyncio.to_thread(materialize_scenario_workspace, spec)
        # The server's TMPDIR is its runtime workdir, which the runtime also removes.
        self._exit_stack.callback(_remove_workspace, materialized.workspace_root)
        manifest = spec["artifact_manifest"]
        self._workspace = Workspace(
            scenario_id=task.scenario_id,
            spec=spec,
            project_root=str(materialized.project_root.resolve()),
            profiles_dir=str(materialized.profiles_dir.resolve()),
            tool_visible_globs=list(manifest["tool_visible_globs"]),
            immutable_paths=list(manifest["immutable_paths"]),
            valid_model_names=model_names(spec),
        )

    @property
    def workspace(self) -> Workspace:
        if self._workspace is None:
            raise RuntimeError("dbt-debugger tool server has no task workspace")
        return self._workspace

    # -- shared helpers -------------------------------------------------------------

    def _resolve(self, path: str) -> tuple[Path, str]:
        """Resolve *path* under the project root to ``(absolute, project-relative)``."""
        root = Path(self.workspace.project_root).resolve()
        target = resolve_under_root(path, root)
        return target, target.relative_to(root).as_posix()

    def _trace(self, tool: str, **fields: Any) -> None:
        """Record one successful tool call, up to a bounded number per rollout."""
        trace = self.state.tool_trace
        if len(trace) < _MAX_TRACE_ENTRIES:
            trace.append({"tool": tool, **fields})

    def _store_evidence(self, ref: dict[str, Any]) -> bool:
        """Append *ref* unless an identical ref is stored; return whether it was added."""
        evidence = self.state.collected_evidence
        if ref in evidence:
            return False
        evidence.append(ref)
        return True

    def _evidence_response(
        self, message: str, ref: dict[str, Any], added: bool, **extra: Any
    ) -> str:
        payload = {
            "status": "accepted",
            "message": message,
            "evidence": ref,
            "evidence_count": len(self.state.collected_evidence),
            "added": added,
            **extra,
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    async def _read(
        self, path: str, start_line: int, end_line: int, *, tool: str, tag_immutable: bool
    ) -> str:
        try:
            target, rel = self._resolve(path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not target.is_file():
            return f"Error: not a file: {path!r}"
        ws = self.workspace
        if not path_matches_globs(rel, effective_read_globs(ws.tool_visible_globs)):
            return "Error: path not allowed for read"
        try:
            text = await asyncio.to_thread(target.read_text, encoding="utf-8")
        except OSError as exc:
            return f"Error: cannot read file: {exc}"
        lines = text.splitlines()
        start = max(1, start_line)
        end = max(start, end_line)
        chunk = lines[start - 1 : end]
        imm = " [immutable source]" if tag_immutable and rel in ws.immutable_paths else ""
        if chunk:
            header = f"# {rel}{imm} (lines {start}-{start + len(chunk) - 1})"
        else:
            header = (
                f"# {rel}{imm} (no lines in range; file has {len(lines)} line(s); "
                f"requested {start}-{end})\n"
            )
        self._trace(tool, path=rel, start_line=start, end_line=end)
        return "\n".join([header, *(f"{i}| {line}" for i, line in enumerate(chunk, start))])

    # -- investigation tools --------------------------------------------------------

    @vf.tool
    async def list_files(self, path: str = ".", max_entries: int = 200) -> str:
        """List files under *path* (project-relative). Hidden internal paths are never visible."""
        try:
            base, rel_base = self._resolve(path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not base.exists():
            return f"Error: path not found: {path!r}"
        ws = self.workspace
        globs = globs_for_list_and_search(ws.tool_visible_globs)

        def tagged(rel: str) -> str:
            return f"{rel} [immutable]" if rel in ws.immutable_paths else rel

        if base.is_file():
            if not path_matches_globs(rel_base, globs):
                return "Error: path not allowed by artifact manifest"
            self._trace("list_files", path=path, max_entries=max_entries)
            return f"FILE {tagged(rel_base)}"

        def _walk() -> str:
            root = Path(ws.project_root).resolve()
            entries: list[str] = []
            for dirpath, dirnames, filenames in os.walk(base, topdown=True):
                dirnames.sort()
                filenames.sort()
                rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
                rel_dir = "" if rel_dir == "." else rel_dir
                for kind, names in (("DIR ", dirnames), ("FILE", filenames)):
                    for name in names:
                        if len(entries) >= max_entries:
                            return "\n".join(
                                [*entries, f"... truncated after {max_entries} entries"]
                            )
                        rel = f"{rel_dir}/{name}" if rel_dir else name
                        if path_matches_globs(rel, globs):
                            entries.append(f"{kind} {tagged(rel)}")
            return "\n".join(entries) if entries else "(empty)"

        result = await asyncio.to_thread(_walk)
        self._trace("list_files", path=path, max_entries=max_entries)
        return result

    @vf.tool
    async def read_file(
        self, path: str, start_line: int = 1, end_line: int = 220
    ) -> str:
        """Read a text file with line numbers (1-based inclusive range)."""
        return await self._read(
            path, start_line, end_line, tool="read_file", tag_immutable=True
        )

    @vf.tool
    async def search_project(
        self, pattern: str, glob_pattern: str = "**/*", max_matches: int = 50
    ) -> str:
        """Search file contents under the project (regex *pattern*)."""
        if not pattern.strip():
            return "Error: empty pattern"
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Error: invalid regex: {exc}"
        ws = self.workspace
        globs = effective_read_globs(globs_for_list_and_search(ws.tool_visible_globs))

        def _search() -> str:
            root = Path(ws.project_root).resolve()
            matches: list[str] = []
            for path_obj in root.rglob("*"):
                if not path_obj.is_file():
                    continue
                try:
                    rel = path_obj.resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
                if not path_matches_globs(rel, globs) or not path_matches_globs(
                    rel, [glob_pattern]
                ):
                    continue
                try:
                    text = path_obj.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        matches.append(f"{rel}:{line_number}:{line[:500]}")
                        if len(matches) >= max_matches:
                            return "\n".join(
                                [*matches, f"... truncated after {max_matches} matches"]
                            )
            return "\n".join(matches) if matches else "(no matches)"

        result = await asyncio.to_thread(_search)
        self._trace(
            "search_project",
            pattern=pattern,
            glob_pattern=glob_pattern,
            max_matches=max_matches,
        )
        return result

    @vf.tool
    async def run_dbt_command(
        self,
        subcommand: Annotated[
            str,
            Field(
                description="One of ``parse``, ``compile``, ``ls``/``list``, ``run``, "
                "``test``, or ``build``."
            ),
        ],
        select: Annotated[
            list[str] | None,
            Field(description="Optional dbt selectors passed after ``--select``."),
        ] = None,
        exclude: Annotated[
            list[str] | None,
            Field(description="Optional dbt selectors passed after ``--exclude``."),
        ] = None,
        resource_types: Annotated[
            list[str] | None,
            Field(description="Optional resource-type filters for ``ls``."),
        ] = None,
        full_refresh: Annotated[
            bool, Field(description="Only valid for ``run`` or ``build``.")
        ] = False,
        fail_fast: Annotated[
            bool, Field(description="Only valid for ``run``, ``test``, or ``build``.")
        ] = False,
        timeout_seconds: Annotated[
            int, Field(description="Subprocess timeout in seconds.")
        ] = 120,
    ) -> str:
        """Run a restricted ``dbt`` command without exposing arbitrary CLI flags."""
        sub = subcommand.lower().strip()
        sub = "ls" if sub == "list" else sub
        if sub not in _ALLOWED_DBT_SUBCOMMANDS:
            return (
                f"Error: disallowed dbt subcommand {sub!r}; "
                f"allowed={sorted(_ALLOWED_DBT_SUBCOMMANDS)}"
            )
        try:
            selected = _selectors(select)
            excluded = _selectors(exclude)
            rtypes = _resource_types(resource_types)
        except ValueError as exc:
            return f"Error: {exc}"
        if full_refresh and sub not in {"run", "build"}:
            return "Error: full_refresh is only supported for run/build"
        if fail_fast and sub not in {"run", "test", "build"}:
            return "Error: fail_fast is only supported for run/test/build"
        if rtypes and sub != "ls":
            return "Error: resource_types is only supported for ls/list"

        args = [sub]
        if selected:
            args += ["--select", *selected]
        if excluded:
            args += ["--exclude", *excluded]
        for value in rtypes:
            args += ["--resource-type", value]
        if full_refresh:
            args.append("--full-refresh")
        if fail_fast:
            args.append("--fail-fast")

        ws = self.workspace
        proc = await asyncio.create_subprocess_exec(
            *dbt_argv(ws.project_root, args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "DBT_PROFILES_DIR": ws.profiles_dir},
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
        if status == 0:
            self._trace(
                "run_dbt_command",
                subcommand=sub,
                select=selected,
                exclude=excluded,
                resource_types=rtypes,
                full_refresh=full_refresh,
                fail_fast=fail_fast,
            )
        return f"exit_code={status}\n{text[-40000:]}"

    @vf.tool
    async def read_artifact(
        self, path: str, start_line: int = 1, end_line: int = 220
    ) -> str:
        """Read logs or ``target/`` artifacts (plus normal project files allowed by globs)."""
        # Traced as ``read_file``: it always has been, and traces are compared across runs.
        return await self._read(
            path, start_line, end_line, tool="read_file", tag_immutable=False
        )

    # -- evidence tools -------------------------------------------------------------

    @vf.tool
    async def add_file_evidence(
        self,
        path: Annotated[
            str,
            Field(
                description="Project-relative file path, such as "
                "``models/intermediate/x.sql``."
            ),
        ],
        start_line: Annotated[
            int, Field(description="1-based start line (inclusive).")
        ],
        end_line: Annotated[int, Field(description="1-based end line (inclusive).")],
    ) -> str:
        """Store one project-file citation for the final diagnosis."""
        if start_line < 1:
            return "Error: start_line must be >= 1"
        if end_line < start_line:
            return "Error: end_line must be >= start_line"
        try:
            target, rel = self._resolve(path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not target.is_file():
            return f"Error: not a file: {path!r}"
        guidance = _file_evidence_guidance(rel)
        if guidance is not None:
            return f"Error: {guidance}"
        try:
            text = await asyncio.to_thread(target.read_text, encoding="utf-8")
        except OSError as exc:
            return f"Error: cannot read file: {exc}"
        line_count = len(text.splitlines())
        if line_count < 1:
            return f"Error: file is empty: {rel!r}"
        if start_line > line_count:
            return (
                f"Error: start_line {start_line} exceeds file length "
                f"({line_count} line(s))"
            )
        clipped_end = min(end_line, line_count)
        ref = {
            "kind": "file_span",
            "path": rel,
            "start_line": start_line,
            "end_line": clipped_end,
        }
        added = self._store_evidence(ref)
        self._trace(
            "add_file_evidence",
            path=rel,
            start_line=start_line,
            end_line=clipped_end,
            added=added,
        )
        message = f"Stored file evidence for {rel} lines {start_line}-{clipped_end}."
        if clipped_end != end_line:
            message += (
                f" Requested end_line {end_line} exceeded file length, so it was "
                f"clipped to {clipped_end}."
            )
        return self._evidence_response(message, ref, added)

    @vf.tool
    async def add_sample_rows_evidence(
        self,
        table: Annotated[
            str,
            Field(
                description="Sample table key from ``debug_context/sample_data.json``."
            ),
        ],
        match_json: Annotated[
            str,
            Field(
                description="JSON object selecting one or more rows, for example\n"
                '``{"order_id": 1001}``.'
            ),
        ],
        min_rows: Annotated[
            int, Field(description="Minimum number of matching rows expected.")
        ] = 1,
    ) -> str:
        """Store one sample-row citation for the final diagnosis."""
        if min_rows < 1:
            return "Error: min_rows must be >= 1"
        sample_data = self.workspace.spec["sample_data"]
        table_obj = sample_data.get(table)
        if table_obj is None:
            return (
                f"Error: unknown sample_data table {table!r}. "
                f"Available tables: {sorted(sample_data)!r}"
            )
        try:
            match = parse_match_json(match_json)
        except ValueError as exc:
            return f"Error: {exc}"
        matched_rows = matching_sample_rows(table_obj, match)
        if len(matched_rows) < min_rows:
            return (
                f"Error: sample_rows match returned {len(matched_rows)} row(s) in "
                f"{table!r}; need at least {min_rows}"
            )
        ref = {
            "kind": "sample_rows",
            "table": table,
            "match_json": json.dumps(match, sort_keys=True),
            "min_rows": min_rows,
        }
        added = self._store_evidence(ref)
        self._trace(
            "add_sample_rows_evidence",
            table=table,
            match_json=ref["match_json"],
            min_rows=min_rows,
            added=added,
        )
        return self._evidence_response(
            f"Stored sample_rows evidence for {table!r}; "
            f"{len(matched_rows)} matching row(s).",
            ref,
            added,
            matched_rows=len(matched_rows),
            preview_rows=matched_rows[:3],
        )

    @vf.tool
    async def add_run_history_evidence(
        self,
        record_type: Annotated[
            str,
            Field(
                description="One of ``summary``, ``model``, ``test``, or ``warning``."
            ),
        ],
        model: Annotated[
            str, Field(description='Model name for ``record_type="model"``.')
        ] = "",
        name: Annotated[
            str, Field(description='Test name for ``record_type="test"``.')
        ] = "",
        status: Annotated[
            str,
            Field(
                description="Optional status filter, such as ``success`` or ``passed``."
            ),
        ] = "",
        contains: Annotated[
            str,
            Field(
                description="Optional snippet expected to appear in the matching record."
            ),
        ] = "",
    ) -> str:
        """Store one run-history citation for the final diagnosis."""
        rtype = record_type.strip().lower()
        if rtype not in RUN_HISTORY_RECORD_TYPES:
            return (
                f"Error: record_type must be one of {sorted(RUN_HISTORY_RECORD_TYPES)!r}"
            )
        status = status.strip().lower()
        contains = contains.strip()
        ref: dict[str, Any] = {"kind": "run_history", "record_type": rtype}

        if rtype in ("summary", "warning"):
            if not contains:
                return f"Error: {rtype} evidence requires contains"
            ref["contains"] = contains
        else:
            name_key = RECORD_NAME_KEY[rtype]
            target = (model if rtype == "model" else name).strip()
            if not target:
                return f"Error: {rtype} evidence requires {name_key}"
            if rtype == "model" and target not in self.workspace.valid_model_names:
                return f"Error: unknown model {target!r}"
            ref[name_key] = target
            if status:
                ref["status"] = status
            if contains:
                ref["contains"] = contains

        entries = run_history_entries(rtype, self.workspace.spec["run_history"])
        entry = next((e for e in entries if entry_matches(e, ref)), None)
        if entry is None:
            if rtype == "summary":
                return f"Error: run_history.summary does not contain {contains!r}"
            if rtype == "warning":
                return f"Error: no run_history warning contains {contains!r}"
            filters = f"{name_key}={target!r}, status={status or '*'}"
            if contains:
                filters += f", contains={contains!r}"
            return f"Error: no run_history {rtype} result matches {filters}"
        matched_key = {
            "summary": "matched_summary",
            "warning": "matched_warning",
        }.get(rtype, "matched_record")

        added = self._store_evidence(ref)
        self._trace(
            "add_run_history_evidence",
            added=added,
            **{key: value for key, value in ref.items() if key != "kind"},
        )
        return self._evidence_response(
            f"Stored run_history evidence for record_type={rtype!r}.",
            ref,
            added,
            **{matched_key: entry},
        )

    @vf.tool
    async def list_collected_evidence(self) -> str:
        """List all evidence refs currently stored for the rollout."""
        evidence = self.state.collected_evidence
        return json.dumps(
            {"status": "ok", "evidence_count": len(evidence), "evidence": evidence},
            indent=2,
            sort_keys=True,
        )

    @vf.tool
    async def submit_diagnosis(
        self,
        has_bug: Annotated[
            bool,
            Field(
                description="Whether the dbt project itself contains a defect requiring "
                "a code change."
            ),
        ],
        root_cause: Annotated[
            str, Field(description="Plain-language explanation of the primary cause.")
        ],
        buggy_models: Annotated[
            list[str],
            Field(
                description="Models that must change to fix a real bug. Must be ``[]`` "
                "when\n``has_bug`` is false (false alarm / semantics / BI-only cases)."
            ),
        ],
        fix: Annotated[
            str,
            Field(
                description="Plain-language remediation, or ``No fix needed — ...`` when "
                "there is no dbt bug.\nEvidence is collected beforehand with "
                "``add_file_evidence(...)``,\n``add_sample_rows_evidence(...)``, and "
                "``add_run_history_evidence(...)``."
            ),
        ],
    ) -> str:
        """Submit a structured diagnosis for evaluator-only scoring."""
        state = self.state
        if state.submitted_diagnosis is not None:
            return "Error: diagnosis already submitted"
        root_cause = root_cause.strip()
        fix = fix.strip()
        if not root_cause or not fix:
            return "Error: root_cause and fix must be non-empty strings"
        models = [model.strip() for model in buggy_models]
        for model in models:
            if not model:
                return "Error: buggy_models must contain non-empty strings"
            if model not in self.workspace.valid_model_names:
                return f"Error: Unknown model in buggy_models: {model!r}"
        if not has_bug and models:
            return (
                "Error: When has_bug is false, buggy_models must be empty "
                "(no dbt defect to fix)."
            )
        if not state.collected_evidence:
            return (
                "Error: no evidence collected. Use add_file_evidence(...), "
                "add_sample_rows_evidence(...), or add_run_history_evidence(...) first."
            )
        state.submitted_diagnosis = {
            "has_bug": bool(has_bug),
            "root_cause": root_cause,
            "buggy_models": sorted(set(models)),
            "fix": fix,
            "evidence": [dict(ref) for ref in state.collected_evidence],
        }
        self._trace("submit_diagnosis", scenario_id=self.workspace.scenario_id)
        return json.dumps(
            {
                "status": "accepted",
                "message": "Diagnosis stored for evaluator-only scoring.",
            },
            indent=2,
        )


if __name__ == "__main__":
    DbtDebuggerToolset.run()
