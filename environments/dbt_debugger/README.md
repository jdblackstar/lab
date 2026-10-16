# dbt-debugger

`dbt-debugger` is a Verifiers environment I use to evaluate models on **data-engineering debugging tasks**: triaging ambiguous stakeholder symptoms, investigating dbt models and sources, collecting grounded evidence, and producing correct diagnoses, including the discipline to recognize false alarms.

## Why I Use It

Most data-quality incidents are not syntax errors. They are ambiguous stakeholder reports: "revenue doubled", "bookings are missing", "finance and ops disagree", or "historical spend moved". A useful agent has to inspect the project, reason through dbt model lineage, ground claims in source rows and run history, and know when **not** to rewrite a healthy warehouse model.

`dbt-debugger` packages that workflow as a reproducible Verifiers environment:

- each rollout gets an isolated dbt project backed by DuckDB
- the model can inspect files, run bounded dbt commands, and read debug artifacts
- diagnoses are scored deterministically against scenario-specific rubrics
- evidence is collected interactively, so agents cite project files, sample rows, and run history before submitting a final answer

The goal is not to ask "can the model write SQL from a prompt?" It is to evaluate whether an agent can do the actual analytics-engineering loop: inspect the system, form hypotheses, ground claims, avoid overfitting to noisy symptoms, and submit a reviewable diagnosis.

## What It Measures

- **Investigation behavior**: whether the model explores the dbt project and supporting artifacts instead of guessing from the symptom.
- **Data-engineering diagnosis**: whether it identifies the actual model, join, macro, incremental predicate, source change, or business-definition issue.
- **False-positive control**: whether it can say "no dbt bug" when the warehouse is correct and the discrepancy comes from source restatement, BI filters, or metric semantics.
- **Grounded evidence use**: whether it cites file spans, sample rows, and run history facts that support the diagnosis.
- **Operational robustness**: whether the model can use tools, recover from validation errors, and submit a structured answer.

## Eval Design Principles

This environment is intentionally opinionated about what a good agentic eval should measure.

- **Grounded investigation over answer guessing**: scenarios expose symptoms, project files, sample rows, and run history, but not the answer key. Correctness requires cited evidence, not just plausible prose.
- **False positives are failures**: several scenarios have `has_bug: false`; an agent that always rewrites a dbt model should lose even if its explanation sounds confident.
- **Deterministic scoring first**: v1 avoids LLM judges. Rubrics use explicit accepted-diagnosis variants, model-set checks, evidence satisfiability, and forbidden-claim patterns.
- **Runtime feedback should teach the protocol**: evidence is collected with dedicated tools instead of a brittle string format, so invalid citations fail early and recoverably.
- **Authoring gates protect benchmark quality**: validation checks JSON Schema shape, resolvable evidence anchors, corpus balance, and alignment between human-readable ground truth and the scored rubric contract.

## Implementation Notes

`dbt-debugger` is a native verifiers v1 package (`verifiers>=0.4.0`). The important implementation pieces are:

- `dbt_debugger/taskset.py`: `DbtDebuggerTaskset` (one task per gold scenario), the task's stop condition, deterministic reward/metrics, the `vf-validate` gold check, and `DbtDebuggerEnv`, which pins the run defaults.
- `dbt_debugger/toolset.py`: `DbtDebuggerToolset`, the per-rollout MCP tool server that materializes the dbt workspace and exposes the tools, plus the shared `DbtDebuggerState`.
- `dbt_debugger/tools.py`: scoped filesystem/dbt tools plus interactive evidence collection.
- `dbt_debugger/scoring.py`: deterministic root-cause/fix/model/evidence scoring and no-bug guardrails.
- `validation/validate_scenarios.py`: schema validation plus custom checks that catch impossible evidence and gold/rubric drift.
- `dbt_debugger/scenarios/gold/*.json`: compact incident corpus spanning joins, incremental drift, source schema issues, macros/config, business-definition gaps, and no-bug cases.

See [`spec/runtime_mapping.md`](spec/runtime_mapping.md) for how the corpus maps onto the v1 taskset, tool server, and scoring.

## Status

- **Scenario corpus**: Gold JSON scenarios under `dbt_debugger/scenarios/gold/` with schema in `spec/scenario_schema.md`.
- **Runtime**: each rollout gets a per-rollout tool server that materializes a **temporary dbt + DuckDB workspace**, exposes filesystem + bounded `dbt` tools, and accepts **`submit_diagnosis`**. The diagnosis is scored deterministically against explicit `rubric_hints.accepted_diagnoses` plus grounded evidence requirements (no LLM judge).
- **Run defaults** (`DbtDebuggerEnv`): the tools-only `null` harness on the local `subprocess` runtime, capped at 20 model turns. The tool calls in the 20th (final allowed) reply still execute before the cap ends the rollout, so a diagnosis submitted there is stored and scored (stop condition `max_turns`). Under v0 (verifiers 0.1.x) the cap was checked before tools ran, so tool calls in reply 20 never executed and a diagnosis submitted there scored 0. Harnesses that execute code (such as `bash`) are refused, because a shell on the evaluator host could read the bundled answer keys.

Local execution uses **`dbt-duckdb`** and bundled `sample_data` loaded into DuckDB to match `sources.yml`. No external warehouse is needed.

## Layout


| Path                                  | Purpose                                                                    |
| ------------------------------------- | -------------------------------------------------------------------------- |
| `pyproject.toml`                      | Package metadata and dependencies (verifiers, dbt, duckdb, pyyaml)         |
| `dbt_debugger/__init__.py`            | Exports `DbtDebuggerTaskset` and `DbtDebuggerEnv` via `__all__`            |
| `dbt_debugger/taskset.py`             | Task data, task (stop, scoring, gold check), taskset, env defaults         |
| `dbt_debugger/toolset.py`             | Per-rollout MCP tool server and shared rollout state                       |
| `dbt_debugger/tools.py`, `workspace.py`, `scoring.py` | Tool implementations, workspace materialization, scoring   |
| `dbt_debugger/scenarios/gold/*.json`  | Reviewed scenarios (shipped in the wheel)                                  |
| `spec/scenario_schema.md`             | Canonical JSON field definitions                                           |
| `spec/authoring_guide.md`             | How to write new scenarios                                                 |
| `spec/runtime_mapping.md`             | Corpus → verifiers v1 mapping                                              |
| `validation/`                         | JSON Schema + `validate_scenarios.py`                                      |
| `tests/`                              | Pytest smoke for workspace, dbt compile, tools, scoring, v1 wiring         |
| `outputs/`                            | Local eval / `vf-validate` runs (ignored by git from repo root `.gitignore`) |


## Validate scenarios

```bash
cd environments/dbt_debugger
uv run python validation/validate_scenarios.py
```

## Unit tests

```bash
cd environments/dbt_debugger
uv sync --extra dev
uv run --extra dev pytest tests/ -v
```

Tests run `dbt compile` per scenario; the tools find the `dbt` script installed next to the running interpreter, so run them through `uv run`.

## Model-free validation

`vf-validate` runs a gold check per task (collect the required evidence and submit the documented ground truth through the real tools; it must strictly pass) and a noop check (an untouched rollout must score 0):

```bash
cd environments/dbt_debugger
uv run vf-validate dbt-debugger --runtime.type subprocess
```

## Eval

Evals run through prime-rl's `uv run eval` (verifiers 0.4's `vf-eval` is deprecated in its favor). prime-rl is not on PyPI, so [`scripts/prime_rl_eval.sh`](../../scripts/prime_rl_eval.sh) checks out a pinned prime-rl commit into `~/.cache/prime-rl/`, syncs its Python 3.12 venv, installs this package into it, and forwards the remaining arguments to `uv run eval`. From the repo root:

```bash
scripts/prime_rl_eval.sh environments/dbt_debugger dbt-debugger \
  -m deepseek/deepseek-v4-flash -n 2 -r 1 -c 2
```

The model is served by Prime Inference with `PRIME_API_KEY`. `-c N` pins the concurrency (an API exposes no load metrics to adapt to). Each run writes `outputs/<run.name>/` (`configs/`, `logs/`, and the file monitor's metrics and trace stream under `monitors/file/`). Add `--monitors.prime` to upload the run as a Prime evaluation, and `--output-dir` / `--run.name` to place it. The eval exits 0 even when rollouts error; check `monitors/file/traces/stream.index.jsonl` (`ok`, `num_errors`) or the `Error` share in the `Evaluated dbt-debugger ...` line of `logs/latest/eval.log`.

Filter one scenario:

```bash
scripts/prime_rl_eval.sh environments/dbt_debugger dbt-debugger \
  -m deepseek/deepseek-v4-flash -n 1 -r 1 -c 1 \
  --select.include.ids '["join_fanout_exec_revenue"]'
```

Raise the turn budget:

```bash
scripts/prime_rl_eval.sh environments/dbt_debugger dbt-debugger \
  -m deepseek/deepseek-v4-flash -n 1 -r 1 -c 1 \
  --select.include.ids '["join_fanout_exec_revenue"]' --env.agent.max-turns 25
```

To install the package for other tooling (for example `vf-validate`), `prime env install dbt-debugger -p /path/to/environments` still works.

## Current Verification Snapshot

Local gates currently pass:

```bash
uv run python validation/validate_scenarios.py
uv run --extra dev pytest tests/ -v
uv run vf-validate dbt-debugger --runtime.type subprocess
```

Expected result: 10 scenario files validate, the test suite passes, and `vf-validate` reports 10/10 valid gold and noop checks.

The v0 → v1 comparison snapshot below was run with verifiers 0.4.0's `vf-eval`, before evals switched to prime-rl's `uv run eval` (`scripts/prime_rl_eval.sh`). That three-scenario smoke (`deepseek/deepseek-v4-flash`, first three scenarios) completed with no rollout errors and the same shape as the v0 baseline on that model: two rollouts hit the 20-turn cap and one stopped on `diagnosis_accepted` after its diagnosis was stored. All three scored a strict pass of `0.0`.

## Configuration


| Knob                               | Description                                                       |
| ---------------------------------- | ----------------------------------------------------------------- |
| `--select.include.ids <id>`        | Keep only the named scenario(s) (stems under `scenarios/gold/`)   |
| `--env.taskset.difficulty-tier N`  | Keep scenarios of difficulty tier `1`–`4`                         |
| `-n N`                             | Cap the number of tasks                                           |
| `--env.agent.max-turns N`          | Max model turns per rollout (default `20`); tools in the last reply run |


## Tools (model-visible)

- `list_files`, `read_file`, `search_project`: scoped to the temp project and `artifact_manifest.tool_visible_globs` (plus `debug_context/**`, `target/**`, `logs/**` for reads).
- `run_dbt_command`: structured subcommand interface (`parse`, `compile`, `ls`, `run`, `test`, `build`) with explicit selector/resource filters; prompt-controlled flags like `--vars` are rejected. Uses rollout-local `DBT_PROFILES_DIR` and the `dbt` installed with the tool server's interpreter.
- `read_artifact`: same read rules as `read_file` for logs / `target/`.
- `add_file_evidence`: store one `file_span` citation from a project file. Rejects `debug_context/`, `target/`, and `logs/` paths with guidance toward the correct evidence tool.
- `add_sample_rows_evidence`: store one `sample_rows` citation from `debug_context/sample_data.json`.
- `add_run_history_evidence`: store one `run_history` citation from `debug_context/run_history.json`.
- `list_collected_evidence`: inspect the evidence currently stored for the rollout.
- `submit_diagnosis`: `has_bug`, `root_cause`, `buggy_models` (models that must change for a real bug; **must be `[]` when `has_bug` is false**), and `fix`. It uses the evidence already collected with the evidence tools and ends the rollout when accepted. If validation fails, the model can correct the payload and retry. Eval summaries also report audit metrics (e.g. model-list match, evidence coverage, forbidden-claim status) in addition to the primary `diagnosis_reward` (`strict_pass`).

Tools are advertised under these bare names (`TOOL_PREFIX = None`). Workspace paths (`profiles.yml`, the DuckDB file, the project root) live only in the tool server process and never appear in tool schemas.

## Required environment variables

None for the taskset itself. The eval needs the inference key for its client (`PRIME_API_KEY` for the default Prime Inference endpoint).
