"""Per-rollout dbt workspace and the model-visible debugging tools, served over MCP.

One server runs per rollout (constructed in ``DbtDebuggerTask.toolsets``). Its
``setup_task`` materializes the scenario's dbt + DuckDB workspace; paths, globs, and the
scenario spec stay inside this process and never reach the tool schemas. Evidence, the
submitted diagnosis, and the tool trace live in ``DbtDebuggerState``, which verifiers
syncs with the host around every tool call so the task can stop and score on it.
"""

# No `from __future__ import annotations`: MCP reads the tool signatures at runtime.
import asyncio
import contextlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

import verifiers.v1 as vf
from dbt_debugger import tools
from dbt_debugger.scenarios import load_scenario_spec, model_names
from dbt_debugger.types import RolloutStateKeys
from dbt_debugger.workspace import cleanup_workspace, materialize_scenario_workspace

if TYPE_CHECKING:
    from dbt_debugger.taskset import DbtDebuggerData

logger = logging.getLogger(__name__)


class DbtDebuggerState(vf.State):
    """Rollout state shared by the tool server (writes) and the task (stop + scoring)."""

    collected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    """Normalized evidence refs stored by the ``add_*_evidence`` tools."""
    submitted_diagnosis: dict[str, Any] | None = None
    """The accepted ``submit_diagnosis`` payload; set once, ends the rollout."""
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    """Bounded log of successful tool calls, for inspection."""


@dataclass(frozen=True)
class _Workspace:
    """Server-local context for this rollout's scenario."""

    scenario_id: str
    spec: dict[str, Any]
    project_root: str
    profiles_dir: str
    duckdb_path: str
    tool_visible_globs: list[str]
    immutable_paths: list[str]
    valid_model_names: list[str]


def _remove_workspace(workspace_root: Path) -> None:
    result = cleanup_workspace(workspace_root)
    if not result.removed:
        logger.warning("dbt-debugger workspace cleanup: %s", result.message)


class DbtDebuggerToolset(vf.Toolset[vf.ToolsetConfig, DbtDebuggerState]):
    TOOL_PREFIX = None
    """Advertise the v0 tool names verbatim; the prompt refers to them by name."""

    _workspace: _Workspace | None = None

    async def setup_task(self, task: "DbtDebuggerData") -> None:
        spec = load_scenario_spec(task.scenario_id)
        materialized = await asyncio.to_thread(materialize_scenario_workspace, spec)
        # The server's TMPDIR is its runtime workdir, which the runtime also removes.
        self._exit_stack.callback(_remove_workspace, materialized.workspace_root)
        manifest = spec["artifact_manifest"]
        self._workspace = _Workspace(
            scenario_id=task.scenario_id,
            spec=spec,
            project_root=str(materialized.project_root.resolve()),
            profiles_dir=str(materialized.profiles_dir.resolve()),
            duckdb_path=str(materialized.duckdb_path.resolve()),
            tool_visible_globs=list(manifest["tool_visible_globs"]),
            immutable_paths=list(manifest["immutable_paths"]),
            valid_model_names=model_names(spec),
        )

    @property
    def workspace(self) -> _Workspace:
        if self._workspace is None:
            raise RuntimeError("dbt-debugger tool server has no task workspace")
        return self._workspace

    @contextlib.contextmanager
    def _rollout_state(self) -> Iterator[dict[str, Any]]:
        """Expose the typed state as the dict the tool functions mutate, then write it back."""
        state = self.state
        container: dict[str, Any] = {
            RolloutStateKeys.SCENARIO_SPEC: self.workspace.spec,
            RolloutStateKeys.COLLECTED_EVIDENCE: state.collected_evidence,
            RolloutStateKeys.SUBMITTED_DIAGNOSIS: state.submitted_diagnosis,
            RolloutStateKeys.TOOL_TRACE: state.tool_trace,
        }
        try:
            yield container
        finally:
            state.collected_evidence = container[RolloutStateKeys.COLLECTED_EVIDENCE]
            state.submitted_diagnosis = container[RolloutStateKeys.SUBMITTED_DIAGNOSIS]
            state.tool_trace = container[RolloutStateKeys.TOOL_TRACE]

    @vf.tool
    async def list_files(self, path: str = ".", max_entries: int = 200) -> str:
        """List files under *path* (project-relative). Hidden internal paths are never visible."""
        ws = self.workspace
        with self._rollout_state() as state:
            return await tools.list_files(
                path,
                max_entries,
                project_root=ws.project_root,
                tool_visible_globs=tools._globs_for_list_and_search(
                    ws.tool_visible_globs
                ),
                immutable_paths=ws.immutable_paths,
                _state=state,
            )

    @vf.tool
    async def read_file(
        self, path: str, start_line: int = 1, end_line: int = 220
    ) -> str:
        """Read a text file with line numbers (1-based inclusive range)."""
        ws = self.workspace
        with self._rollout_state() as state:
            return await tools.read_file(
                path,
                start_line,
                end_line,
                project_root=ws.project_root,
                tool_visible_globs=ws.tool_visible_globs,
                immutable_paths=ws.immutable_paths,
                _state=state,
            )

    @vf.tool
    async def search_project(
        self, pattern: str, glob_pattern: str = "**/*", max_matches: int = 50
    ) -> str:
        """Search file contents under the project (regex *pattern*)."""
        ws = self.workspace
        with self._rollout_state() as state:
            return await tools.search_project(
                pattern,
                glob_pattern,
                max_matches,
                project_root=ws.project_root,
                tool_visible_globs=tools._globs_for_list_and_search(
                    ws.tool_visible_globs
                ),
                immutable_paths=ws.immutable_paths,
                _state=state,
            )

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
        ws = self.workspace
        with self._rollout_state() as state:
            return await tools.run_dbt_command(
                subcommand,
                select,
                exclude,
                resource_types,
                full_refresh,
                fail_fast,
                timeout_seconds,
                project_root=ws.project_root,
                profiles_dir=ws.profiles_dir,
                duckdb_path=ws.duckdb_path,
                _state=state,
            )

    @vf.tool
    async def read_artifact(
        self, path: str, start_line: int = 1, end_line: int = 220
    ) -> str:
        """Read logs or ``target/`` artifacts (plus normal project files allowed by globs)."""
        ws = self.workspace
        with self._rollout_state() as state:
            return await tools.read_artifact(
                path,
                start_line,
                end_line,
                project_root=ws.project_root,
                tool_visible_globs=ws.tool_visible_globs,
                _state=state,
            )

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
        with self._rollout_state() as state:
            return await tools.add_file_evidence(
                path,
                start_line,
                end_line,
                project_root=self.workspace.project_root,
                rollout_state=state,
            )

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
        with self._rollout_state() as state:
            return await tools.add_sample_rows_evidence(
                table, match_json, min_rows, rollout_state=state
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
        with self._rollout_state() as state:
            return await tools.add_run_history_evidence(
                record_type,
                model,
                name,
                status,
                contains,
                valid_model_names=self.workspace.valid_model_names,
                rollout_state=state,
            )

    @vf.tool
    async def list_collected_evidence(self) -> str:
        """List all evidence refs currently stored for the rollout."""
        with self._rollout_state() as state:
            return await tools.list_collected_evidence(rollout_state=state)

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
        ws = self.workspace
        with self._rollout_state() as state:
            return await tools.submit_diagnosis(
                has_bug,
                root_cause,
                buggy_models,
                fix,
                scenario_id=ws.scenario_id,
                valid_model_names=ws.valid_model_names,
                rollout_state=state,
            )


if __name__ == "__main__":
    DbtDebuggerToolset.run()
