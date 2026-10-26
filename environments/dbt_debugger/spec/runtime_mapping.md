# Static scenario corpus → verifiers v1 runtime mapping

This document ties the JSON corpus in `dbt_debugger/scenarios/gold/` to the verifiers v1 taskset in `dbt_debugger/` (`verifiers>=0.4.0`, `import verifiers.v1 as vf`).

## Package contract

`dbt_debugger/__init__.py` exports, via `__all__`:

- `DbtDebuggerTaskset` (`vf.Taskset`): loads one `DbtDebuggerTask` per gold scenario.
- `DbtDebuggerEnv` (`vf.SingleAgentEnv` subclass): pins the run defaults below.

There is no `load_environment()`; the v1 loader resolves both classes and their typed configs from `__all__`.

| v0 (`verifiers` 0.1.x)                         | v1 (this package)                                                              |
| ---------------------------------------------- | ------------------------------------------------------------------------------ |
| Dataset row (`question`, `info`)               | `DbtDebuggerData(vf.TaskData)`: `prompt`, `scenario_id`, `difficulty_tier`     |
| `load_environment(**kwargs)`                   | `DbtDebuggerTaskset` + `DbtDebuggerConfig`                                     |
| `StatefulToolEnv` tools + `args_to_skip`       | `DbtDebuggerToolset(vf.Toolset)`, one server per rollout (`Task.toolsets`)     |
| `setup_state()` workspace materialization      | `DbtDebuggerToolset.setup_task()`                                              |
| Dict state                                     | `DbtDebuggerState(vf.State)` + `trace.info` after `finalize`                   |
| `@vf.stop _diagnosis_accepted`                 | `@vf.stop diagnosis_accepted` on the task                                      |
| `Rubric` reward + metrics                      | `@vf.reward diagnosis_reward`, `@vf.metric` on the task                        |
| `max_turns=20` constructor arg                 | `DbtDebuggerEnvConfig.agent.max_turns = 20` (`--env.agent.max-turns`)          |
| `@vf.cleanup` workspace removal                | Server exit stack + the subprocess runtime's workdir teardown                  |

## Run configuration

| Knob                    | Default                         | CLI                                              |
| ----------------------- | ------------------------------- | ------------------------------------------------ |
| One scenario            | all 10                          | `--select.include.ids join_fanout_exec_revenue`  |
| Difficulty tier         | all                             | `--env.taskset.difficulty-tier 3`                |
| Number of tasks         | all                             | `-n 2`                                           |
| Max model turns         | `20`                            | `--env.agent.max-turns 25`                       |
| Harness                 | `null` (tools only)             | code-executing harnesses are refused             |
| Harness runtime         | local `subprocess`              | `--env.agent.runtime.type ...`                   |
| Tool server runtime     | local `subprocess`              | `--env.taskset.task.tools.runtime.type ...`      |

Code-executing harnesses (for example `bash`) are refused because a shell on the evaluator host could read the answer keys bundled under `dbt_debugger/scenarios/gold/` instead of debugging the project.

## Task data

Each JSON file becomes one task:

| Field             | Source                                   | Notes                                                   |
| ----------------- | ---------------------------------------- | ------------------------------------------------------- |
| `prompt`          | `symptom.message` + task instructions    | Do **not** embed `ground_truth`.                        |
| `id`              | `scenario_id`                            | Also the task `key`, so selection is order-independent. |
| `name`            | `title`                                  | Display only.                                           |
| `scenario_id`     | `scenario_id`                            | The tool server and scoring load the full spec by id.   |
| `difficulty_tier` | `difficulty_tier`                        | Reported as `difficulty_metric`.                        |

`TaskData` rides on every trace and is sent to the tool server, so the full spec (ground truth, rubric hints) is never stored on it; both sides load it from the bundled JSON.

## Tool server responsibilities

`DbtDebuggerToolset.setup_task(task_data)` runs once per rollout in the tool server process:

1. Load the scenario JSON keyed by `scenario_id`.
2. Materialize `dbt_project.files` (+ optional seeds/macros), `debug_context/`, a rollout-local `profiles.yml`, and DuckDB source tables under a temporary workspace (inside the server runtime's workdir).
3. Keep `project_root`, `profiles_dir`, the manifest globs, valid model names, and the spec on the server. None of them appear in tool schemas.

Rollout state that the task needs lives in `DbtDebuggerState` (`collected_evidence`, `submitted_diagnosis`, `tool_trace`) and is synced with the host around every tool call.

## Tool surface

`TOOL_PREFIX = None`, so tools are advertised under the bare names the prompt uses. Descriptions and parameter schemas match v0; parameters with defaults are optional.

| Tool                       | Model-visible args                               | Server-side context                       | Behavior |
| -------------------------- | ------------------------------------------------ | ----------------------------------------- | -------- |
| `list_files`               | `path`, `max_entries`                            | project root, globs + `debug_context/**`  | Directory listing under workspace |
| `read_file`                | `path`, line range                               | project root, globs                       | Read text file |
| `search_project`           | `pattern`, `glob_pattern`, `max_matches`         | project root, globs + `debug_context/**`  | Regex search |
| `run_dbt_command`          | structured subcommand + selectors                | project root, `profiles_dir`              | Run a restricted `dbt` subprocess without arbitrary CLI flags |
| `read_artifact`            | `path`, line range                               | project root, globs                       | Read `target/` or logs |
| `add_file_evidence`        | `path`, `start_line`, `end_line`                 | project root, state                       | Validate/store one `file_span` citation from a project file |
| `add_sample_rows_evidence` | `table`, `match_json`, `min_rows`                | spec, state                               | Validate/store one `sample_rows` citation from `debug_context/sample_data.json` |
| `add_run_history_evidence` | `record_type`, optional filters                  | spec, valid model names, state            | Validate/store one `run_history` citation from `debug_context/run_history.json` |
| `list_collected_evidence`  | none                                             | state                                     | Show the evidence currently stored for the rollout |
| `submit_diagnosis`         | `has_bug`, `root_cause`, `buggy_models`, `fix`   | scenario id, valid model names, state     | Validates payload (`buggy_models` empty when `has_bug` is false), bundles collected evidence, and sets `submitted_diagnosis` |

## Stop conditions

- `@vf.stop diagnosis_accepted` fires before the next model call once `submitted_diagnosis` is set.
- The agent's `max_turns` limit (default 20) applies otherwise.

## Scoring (deterministic)

`DbtDebuggerTask.finalize` copies the state into `trace.info` (`submitted_diagnosis`, `collected_evidence`, `tool_trace`, `verification_result`). Scoring recomputes the pure `score_diagnosis` audit from `trace.info`, so metrics never depend on reward execution order:

1. Parse the submitted payload (root cause, `buggy_models`, fix, collected structured evidence refs).
2. Compare to `rubric_hints.accepted_diagnoses` plus grounded `required_evidence`.
3. For `has_bug: false`, assert **no** forbidden claim patterns (`rubric_hints.forbidden_claims`).

`diagnosis_reward` is `strict_pass`; `difficulty_metric` and the audit fields (`strict_pass`, `has_bug_match`, `buggy_models_match`, `diagnosis_variant_ok`, `root_cause_coverage`, `fix_coverage`, `required_evidence_coverage`, `forbidden_ok`, `no_bug_semantic_partial`) are metrics.

## Model-free validation

`DbtDebuggerTask.validate` is the `vf-validate` gold check: it materializes the workspace, stores the `required_evidence` through the real evidence tools, submits `ground_truth` through `submit_diagnosis`, and requires a strict pass. The noop check confirms an untouched rollout scores 0.

## Packaging and install

- Environment package name: `dbt-debugger` (module `dbt_debugger`).
- The wheel ships the `dbt_debugger` package, including `dbt_debugger/scenarios/gold/*.json`, so the taskset works after `prime env install dbt-debugger`.

## Performance hygiene

Avoid blocking the event loop in tool server setup, tools, and scoring: use `asyncio.to_thread` for heavy file IO and asyncio subprocesses for dbt.
