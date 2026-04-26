# Static scenario corpus → Verifiers runtime mapping

This document ties the JSON corpus in `scenarios/gold/` to the eventual `vf.StatefulToolEnv` implementation. It satisfies the **runtime shape** and **executable harness** planning steps from the benchmark roadmap.

## Why `StatefulToolEnv`

Per [Verifiers Environments](https://docs.primeintellect.ai/verifiers/environments), `ToolEnv`/`MCPEnv` are for stateless tools. A dbt debugging rollout needs:

- A **fresh project directory** per example (isolation, reproducibility).
- **Hidden arguments** (workspace paths, scenario spec pointers) injected on each tool call via `args_to_skip` + `update_tool_args()`.
- Optional **cleanup** of temp dirs after each rollout (`@vf.cleanup`).

That matches the documented `StatefulToolEnv` pattern.

## `load_environment()` contract

Expose explicit keyword parameters so `prime eval run` can slice the benchmark:


| Parameter         | Purpose                               | CLI mapping                                                                                        |
| ----------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `scenario_id`     | Single scenario                       | `--env-args '{"scenario_id":"join_fanout_exec_revenue"}'`                                          |
| `difficulty_tier` | Filter by tier                        | `--env-args '{"difficulty_tier":3}'`                                                               |
| `scenario_set`    | Future sets (`gold`, `synth`)         | `--env-args '{"scenario_set":"gold"}'`                                                             |
| `max_scenarios`   | Cap rows after filters                | `--env-args '{"max_scenarios":2}'`                                                                 |
| `max_turns`       | Tool turns (future `StatefulToolEnv`) | `--extra-env-kwargs '{"max_turns":25}'` or add to `load_environment()` when the tool harness lands |


**Implementation note:** `--env-args` passes JSON into `load_environment()`; `--extra-env-kwargs` passes kwargs to the environment constructor ([Evaluation docs](https://docs.primeintellect.ai/verifiers/evaluation)). The corpus-phase `SingleTurnEnv` does not expose multi-turn tooling; add `max_turns` to `load_environment()` once `StatefulToolEnv` replaces it.

## Dataset rows

Each JSON file becomes one dataset row:


| Column                 | Source                                                   | Notes                                    |
| ---------------------- | -------------------------------------------------------- | ---------------------------------------- |
| `question` or `prompt` | `symptom.message` + task instructions                    | Do **not** embed `ground_truth`.         |
| `info`                 | `scenario_id`, `difficulty_tier`, optional safe metadata | Rich spec stays in evaluator state only. |


For large corpora, switch to `vf.DatasetBuilder` (lazy builder) as described in the Environments guide.

## `setup_state()` responsibilities

1. Parse the scenario JSON for this row (or load from bundled path keyed by `scenario_id`).
2. Materialize `dbt_project.files` (+ optional seeds/macros) under a **temporary** `workspace_root`.
3. Store in `state`:
  - `workspace_root`, `project_root`
  - `scenario_spec` (full dict) **for rubric only**
  - `artifact_manifest`
  - `submitted_diagnosis` (empty until tool call)

## Tool surface (planned)


| Tool                    | Model-visible args                         | Hidden injected args                | Behavior |
| ----------------------- | ------------------------------------------ | ----------------------------------- | -------- |
| `list_files`            | `path`, `max_entries`                      | `project_root`, rollout state       | Directory listing under workspace |
| `read_file`             | `path`, line range                         | `project_root`, rollout state       | Read text file |
| `search_project`        | `pattern`, `glob`                          | `project_root`, rollout state       | Ripgrep-like search (async-friendly) |
| `run_dbt_command`       | structured subcommand + selectors          | `project_root`, `profiles_dir`, rollout state | Run a restricted `dbt` subprocess without arbitrary CLI flags |
| `read_artifact`         | `path`                                     | `project_root`, rollout state       | Read `target/` or logs if allowed by manifest |
| `add_file_evidence`     | `path`, `start_line`, `end_line`           | `project_root`, rollout state       | Validate/store one `file_span` citation from a project file |
| `add_sample_rows_evidence` | `table`, `match_json`, `min_rows`       | rollout state                       | Validate/store one `sample_rows` citation from `debug_context/sample_data.json` |
| `add_run_history_evidence` | `record_type`, optional filters         | `valid_model_names`, rollout state  | Validate/store one `run_history` citation from `debug_context/run_history.json` |
| `list_collected_evidence` | none                                     | rollout state                       | Show the evidence currently stored for the rollout |
| `submit_diagnosis`      | `has_bug`, `root_cause`, `buggy_models`, `fix` | `scenario_id`, `valid_model_names`, rollout state | Validates payload (`buggy_models` empty when `has_bug` is false), bundles previously collected evidence, and sets the stop flag |


Register each with `add_tool(..., args_to_skip=[...])` and implement `update_tool_args()` to merge hidden fields from `state`.

## Stop conditions

- `@vf.stop` when `submit_diagnosis` succeeds.
- Built-in `max_turns` / errors from Verifiers apply otherwise.

## Rubric (deterministic first)

1. Parse `submitted_diagnosis` payload (root cause, `buggy_models`, fix, previously collected structured evidence refs).
2. Compare to `rubric_hints.accepted_diagnoses` plus grounded `required_evidence`.
3. For `has_bug: false`, assert **no** forbidden claim patterns (`rubric_hints.forbidden_claims`).
4. Optional later: `vf.JudgeRubric` for explanation quality, composed via `vf.RubricGroup` ([Environments — RubricGroup](https://docs.primeintellect.ai/verifiers/environments)).

## Packaging and install

- Environment package name: `dbt-debugger` (maps to module `dbt_debugger` for `prime eval run dbt-debugger`).
- Include `scenarios/gold/*.json` in the wheel/sdist via `[tool.hatch.build]` `include` so `load_environment()` works after `prime env install dbt-debugger`.
- Defaults in `[tool.verifiers.eval]` follow [Developing Environments](https://docs.primeintellect.ai/verifiers/environments).

## Current phase (implemented)

`dbt_debugger.py` exposes `load_environment()` building a `DbtDebuggerEnv` `StatefulToolEnv` over the gold corpus. Each rollout materializes a temp dbt workspace, exposes bounded debugging tools, and scores a structured diagnosis deterministically.

## Performance hygiene

Avoid blocking the asyncio loop in `setup_state`, tools, and rubrics ([Environments — Performance](https://docs.primeintellect.ai/verifiers/environments)): use `asyncio.to_thread` for subprocesses and heavy file IO where needed.