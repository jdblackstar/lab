# How a scenario runs: taskset, tool server, and scoring

This document describes how the JSON corpus in `dbt_debugger/scenarios/gold/` becomes a verifiers rollout (`verifiers>=0.4.0`, `import verifiers.v1 as vf`): which object owns each piece of a scenario, what the model can see, and how the submitted diagnosis is scored.

```diagram
┌──────────────────────────┐      TaskData (scenario_id)      ┌──────────────────────────────┐
│ DbtDebuggerTask          │ ───────────────────────────────▶ │ DbtDebuggerToolset (per rollout) │
│  stop: diagnosis_accepted│                                  │  setup_task: materialize dbt │
│  reward: strict_pass     │ ◀─────────────────────────────── │  + DuckDB workspace          │
│  metrics: audit fields   │   DbtDebuggerState (evidence,    │  tools: files, dbt, evidence,│
│  validate: gold check    │   diagnosis, trace) after each   │  submit_diagnosis            │
└───────────┬──────────────┘   tool call                      └──────────────────────────────┘
            │ score_diagnosis(submission, spec)
            ▼
┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
│ scoring.py → Audit       │──▶│ rubric.py (Rubric,       │   │ evidence.py              │
│                          │   │ DiagnosisVariant,        │   │ evidence_matches(ref,    │
│                          │──▶│ ClaimPattern)            │   │ requirement, spec)       │
└──────────────────────────┘   └──────────────────────────┘   └──────────────────────────┘
```

## Package contract

`dbt_debugger/__init__.py` exports, via `__all__`:

- `DbtDebuggerTaskset` (`vf.Taskset`): loads one `DbtDebuggerTask` per gold scenario.
- `DbtDebuggerEnv` (`vf.SingleAgentEnv` subclass): pins the run defaults below.

The verifiers loader resolves both classes and their typed configs (`DbtDebuggerConfig`, `DbtDebuggerEnvConfig`) from `__all__`.

| Module                            | Owns                                                                                     |
| --------------------------------- | ---------------------------------------------------------------------------------------- |
| `taskset.py`                      | `DbtDebuggerData`, the task (stop, reward, metrics, gold check), the taskset, env defaults |
| `toolset.py`                      | `DbtDebuggerToolset` (the tools), `Workspace` (server-only context), `DbtDebuggerState`  |
| `workspace.py`, `paths.py`        | Materializing the dbt + DuckDB workspace; project-relative paths and manifest globs      |
| `scoring.py`                      | `score_diagnosis(submission, spec) -> Audit`                                             |
| `rubric.py`                       | `rubric_hints` as typed objects: `Rubric`, `DiagnosisVariant`, `ClaimPattern`            |
| `evidence.py`                     | `evidence_matches(ref, requirement, spec)` and the run-history / sample-row helpers      |
| `claim_text_matching.py`, `sample_rows.py` | Text normalization and stemming for claim matching; row selection for `sample_data` |
| `scenarios.py`                    | Loading gold JSON, the prompt builder, model names                                       |

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

Code-executing harnesses (for example `bash`) are refused because a shell on the evaluator host could read the answer keys bundled under `dbt_debugger/scenarios/gold/` instead of debugging the project. Tool calls in the final allowed reply still execute before the turn cap ends the rollout, so a diagnosis submitted there is stored and scored.

## Task data

Each JSON file becomes one task:

| Field             | Source                                   | Notes                                                   |
| ----------------- | ---------------------------------------- | ------------------------------------------------------- |
| `prompt`          | `symptom.message` + task instructions    | Does **not** embed `ground_truth`.                      |
| `id`              | `scenario_id`                            | Also the task `key`, so selection is order-independent. |
| `name`            | `title`                                  | Display only.                                           |
| `scenario_id`     | `scenario_id`                            | The tool server and scoring load the full spec by id.   |
| `difficulty_tier` | `difficulty_tier`                        | Reported as `difficulty_metric`.                        |

`TaskData` rides on every trace and is sent to the tool server, so the full spec (ground truth, rubric hints) is never stored on it; both sides load it from the bundled JSON.

## Tool server

One `DbtDebuggerToolset` server runs per rollout (`DbtDebuggerTask.toolsets`). `setup_task(task_data)` runs once in that process:

1. Load the scenario JSON keyed by `scenario_id`.
2. Materialize `dbt_project.files`, `debug_context/` (`sample_data.json`, `run_history.json`), a rollout-local `profiles.yml`, and the DuckDB source tables under a temporary directory inside the server runtime's workdir.
3. Keep the project root, profiles dir, manifest globs, valid model names, and the spec in `Workspace`, a server-local dataclass. None of them appear in tool schemas or reach the model.

Rollout state that the task needs lives in `DbtDebuggerState` (`collected_evidence`, `submitted_diagnosis`, `tool_trace`) and is synced with the host around every tool call, so the task's stop condition and scoring read it without another round trip.

## Tool surface

`TOOL_PREFIX = None`, so tools are advertised under the bare names the prompt uses. Tool docstrings are the MCP descriptions and `Annotated[..., Field(...)]` parameters are the schemas; parameters with defaults are optional.

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

## Evidence refs

The three `add_*_evidence` tools store small JSON refs in `DbtDebuggerState.collected_evidence`:

| Kind          | Ref fields                                                     |
| ------------- | -------------------------------------------------------------- |
| `file_span`   | `path`, `start_line`, `end_line`                               |
| `sample_rows` | `table`, `match_json` (normalized), `min_rows`                 |
| `run_history` | `record_type` plus the filters given: `model`/`name`, `status`, `contains` |

`rubric_hints.required_evidence` entries name the facts a diagnosis must cite in the same vocabulary. `evidence.evidence_matches(ref, requirement, spec)` is the one place that decides whether a ref satisfies a requirement: same artifact, the citation still selects the records the requirement names, and the requirement's `all_of` anchors appear in what it cites. The tool server uses the same helpers to reject an unfounded ref at store time, and the offline validator uses them to prove every requirement is satisfiable, so the three cannot disagree about what counts as a citation.

## Stop conditions

- `@vf.stop diagnosis_accepted` fires before the next model call once `submitted_diagnosis` is set.
- The agent's `max_turns` limit (default 20) applies otherwise.

## Scoring (deterministic)

`DbtDebuggerTask.finalize` copies the state into `trace.info` (`submitted_diagnosis`, `collected_evidence`, `tool_trace`) along with `verification_result`, the audit as a dict. The reward and metrics recompute the pure `score_diagnosis` audit from `trace.info`, so they never depend on execution order.

`score_diagnosis(submission, spec)` reads `rubric_hints` through `Rubric.from_spec` and returns an `Audit`:

1. `has_bug_match`: the submitted `has_bug` equals the scenario's.
2. Each `DiagnosisVariant` in `accepted_diagnoses` is evaluated against the submission: `buggy_models` must include every `required_models` entry and nothing outside `allowed_models` (which defaults to `required_models`); the root cause must match the `root_cause_all_of` `ClaimPattern` (one option from every synonym group); the fix must match at least one `fix_variants` pattern. `diagnosis_variant_ok` is true when any variant passes in full; `root_cause_coverage` and `fix_coverage` are the best fraction of groups matched.
3. `required_evidence_ok`: every `required_evidence` entry is satisfied by some stored ref under `evidence_matches`; `required_evidence_coverage` is the fraction satisfied.
4. `forbidden_ok`: no `forbidden_claims` pattern is stated in the root cause, fix, or model list. An option that the text explicitly negates ("the mart is not broken") does not count, and neither does an accepted negated phrase from the rubric itself ("no dbt bug"); the validator rejects rubrics where such a phrase could satisfy a forbidden claim.

`strict_pass` is 1.0 iff all four hold; it is the only reward (`diagnosis_reward`). `difficulty_metric` and the audit fields (`strict_pass`, `has_bug_match`, `buggy_models_match`, `diagnosis_variant_ok`, `root_cause_coverage`, `fix_coverage`, `required_evidence_coverage`, `forbidden_ok`, `no_bug_semantic_partial`) are metrics. `no_bug_semantic_partial` grades a no-bug rollout that got the label right and avoided forbidden claims by how much of the rubric it covered.

## Model-free validation

`DbtDebuggerTask.validate` is the `vf-validate` gold check: it materializes the workspace, stores the `required_evidence` through the real evidence tools, submits `ground_truth` through `submit_diagnosis`, and requires a strict pass. The noop check confirms an untouched rollout scores 0.

`validation/validate_scenarios.py` is the authoring gate: JSON Schema first, then the cross-section checks a schema cannot express, using the same `Rubric` and `evidence` code as scoring.

## Packaging and install

- Environment package name: `dbt-debugger` (module `dbt_debugger`).
- The wheel ships the `dbt_debugger` package, including `dbt_debugger/scenarios/gold/*.json`, so the taskset works after `prime env install dbt-debugger`.

## Performance hygiene

Avoid blocking the event loop in tool server setup, tools, and scoring: use `asyncio.to_thread` for heavy file IO and asyncio subprocesses for dbt.
