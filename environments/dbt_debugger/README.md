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

The important implementation pieces are:

- `runtime/env.py`: `vf.StatefulToolEnv` wiring, hidden rollout state injection, stop condition, and rubric metrics.
- `runtime/tools.py`: scoped filesystem/dbt tools plus interactive evidence collection.
- `runtime/scoring.py`: deterministic root-cause/fix/model/evidence scoring and no-bug guardrails.
- `validation/validate_scenarios.py`: schema validation plus custom checks that catch impossible evidence and gold/rubric drift.
- `scenarios/gold/*.json`: compact incident corpus spanning joins, incremental drift, source schema issues, macros/config, business-definition gaps, and no-bug cases.

## Status

- **Scenario corpus**: Gold JSON scenarios under `scenarios/gold/` with schema in `spec/scenario_schema.md`.
- **Runtime**: `load_environment()` returns a `**vf.StatefulToolEnv`** (`DbtDebuggerEnv`) that materializes a **temporary dbt + DuckDB workspace** per rollout, exposes filesystem + bounded `dbt` tools, accepts `**submit_diagnosis`**, and scores deterministically against explicit `rubric_hints.accepted_diagnoses` plus grounded evidence requirements (no LLM judge in v1).

Local execution uses `**dbt-duckdb**` and bundled `sample_data` loaded into DuckDB to match `sources.yml` — no external warehouse.

## Layout


| Path                      | Purpose                                                                                                            |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `pyproject.toml`          | Package metadata, dependencies (verifiers, dbt, duckdb, pyyaml), Hatch `include`, `[tool.verifiers.eval]` defaults |
| `spec/scenario_schema.md` | Canonical JSON field definitions                                                                                   |
| `spec/authoring_guide.md` | How to write new scenarios                                                                                         |
| `spec/runtime_mapping.md` | Corpus → `StatefulToolEnv` mapping                                                                                 |
| `scenarios/gold/*.json`   | Reviewed scenarios                                                                                                 |
| `validation/`             | JSON Schema + `validate_scenarios.py`                                                                              |
| `runtime/`                | Packaged runtime helpers: workspace materialization, tools, scoring, `DbtDebuggerEnv`                              |
| `dbt_debugger.py`         | `load_environment()` entrypoint                                                                                    |
| `tests/`                  | Pytest smoke for workspace, dbt compile, scoring                                                                   |
| `outputs/`                | Local `prime eval run` artifacts (ignored by git from repo root `.gitignore`)                                      |


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

## Install and eval (smoke)

```bash
prime env install dbt-debugger -p /path/to/environments
uv run --env-file .env prime eval run dbt-debugger \
  -e /path/to/configs/endpoints.toml \
  -m openai/gpt-4.1-mini \
  -n 2 -r 1
```

Filter one scenario:

```bash
uv run --env-file .env prime eval run dbt-debugger \
  -e /path/to/configs/endpoints.toml \
  -m openai/gpt-4.1-mini \
  -a '{"scenario_id":"join_fanout_exec_revenue"}' \
  -n 1 -r 1 -A
```

Raise the tool turn budget (passed into `load_environment`):

```bash
prime eval run dbt-debugger -a '{"scenario_id":"join_fanout_exec_revenue","max_turns":25}' -n 1 -r 1
```

## Current Verification Snapshot

Local gates currently pass:

```bash
uv run python validation/validate_scenarios.py
uv run --extra dev pytest tests/ -v
```

Expected result: 10 scenario files validate; the focused runtime/validation suite passes.

Recent one-scenario smoke (`join_fanout_exec_revenue`, `openai/gpt-4.1-mini`) completed end-to-end with the interactive evidence flow:

- environment installed and loaded locally
- model used `add_file_evidence`, `add_sample_rows_evidence`, and `add_run_history_evidence`
- `submit_diagnosis` was accepted and rollout stopped on `_diagnosis_accepted`
- evidence coverage and model-list match were correct
- strict pass remained `0.0` because the answer missed one root-cause rubric phrase group

That is the intended debugging signal: transport, tools, evidence collection, and scoring work; remaining failures are semantic/rubric fit rather than submission-format friction.

## `load_environment` arguments


| Argument          | Description                                            |
| ----------------- | ------------------------------------------------------ |
| `scenario_id`     | Optional stem of one JSON file under `scenarios/gold/` |
| `difficulty_tier` | Optional filter `1`–`4`                                |
| `scenario_set`    | Must be `"gold"` (only bundled set)                    |
| `max_scenarios`   | Cap rows after filters; `-1` = all                     |
| `max_turns`       | Max model/tool turns per rollout (default `20`)        |


## Tools (model-visible)

- `list_files`, `read_file`, `search_project` — scoped to the temp project and `artifact_manifest.tool_visible_globs` (plus `debug_context/**`, `target/**`, `logs/**` for reads).
- `run_dbt_command` — structured subcommand interface (`parse`, `compile`, `ls`, `run`, `test`, `build`) with explicit selector/resource filters; prompt-controlled flags like `--vars` are rejected. Uses rollout-local `DBT_PROFILES_DIR`. If the `dbt` binary is not on `PATH`, the tool falls back to `python -m dbt` using the same interpreter.
- `read_artifact` — same read rules as `read_file` for logs / `target/`.
- `add_file_evidence` — store one `file_span` citation from a project file. Rejects `debug_context/`, `target/`, and `logs/` paths with guidance toward the correct evidence tool.
- `add_sample_rows_evidence` — store one `sample_rows` citation from `debug_context/sample_data.json`.
- `add_run_history_evidence` — store one `run_history` citation from `debug_context/run_history.json`.
- `list_collected_evidence` — inspect the evidence currently stored for the rollout.
- `submit_diagnosis` — `has_bug`, `root_cause`, `buggy_models` (models that must change for a real bug; **must be `[]` when `has_bug` is false**), and `fix`; uses the evidence already collected with the evidence tools and ends the rollout when accepted. If validation fails, the model can correct the payload and retry. Eval summaries also report rubric metrics (e.g. model-list match, evidence coverage, forbidden-claim status) in addition to the primary `strict_pass` reward.

Hidden paths (`profiles.yml`, DuckDB file) are injected via `args_to_skip` + `update_tool_args` and never appear in tool schemas.

## Required environment variables

None for the default environment. If you add a `JudgeRubric` later, validate keys with `vf.ensure_keys(...)` in `load_environment()`.

### Local API keys (`.env`)

`load_environment()` calls `python-dotenv` so variables from `.env` are available in-process. Files are merged with **first definition wins** (and never overriding variables already exported in the shell): `.env` in the current working directory, then `environments/dbt_debugger/.env`, then the repo root `.env` (parent of `environments/`). Put shared keys in the repo root file; override locally in cwd when needed.

For `prime eval run`, the Prime CLI still needs the same keys in the environment it uses to call inference unless you export them or use your shell’s dotenv integration; loading here helps Python entrypoints (and any code that runs after `load_environment()` inside the same process).