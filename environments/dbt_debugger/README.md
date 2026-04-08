# dbt-debugger

Verifiers environment for **dbt pipeline debugging**: triaging ambiguous stakeholder symptoms, investigating models and sources, and producing correct diagnoses (and recognizing false alarms).

## Status

- **Scenario corpus**: Gold JSON scenarios under `scenarios/gold/` with schema in `spec/scenario_schema.md`.
- **Runtime**: `load_environment()` returns a **`vf.StatefulToolEnv`** (`DbtDebuggerEnv`) that materializes a **temporary dbt + DuckDB workspace** per rollout, exposes filesystem + bounded `dbt` tools, accepts **`submit_diagnosis`**, and scores deterministically against explicit `rubric_hints.accepted_diagnoses` plus grounded evidence requirements (no LLM judge in v1).

Local execution uses **`dbt-duckdb`** and bundled `sample_data` loaded into DuckDB to match `sources.yml` — no external warehouse.

## Layout

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata, dependencies (verifiers, dbt, duckdb, pyyaml), Hatch `include`, `[tool.verifiers.eval]` defaults |
| `spec/scenario_schema.md` | Canonical JSON field definitions |
| `spec/authoring_guide.md` | How to write new scenarios |
| `spec/runtime_mapping.md` | Corpus → `StatefulToolEnv` mapping |
| `scenarios/gold/*.json` | Reviewed scenarios |
| `validation/` | JSON Schema + `validate_scenarios.py` |
| `runtime/` | Packaged runtime helpers: workspace materialization, tools, scoring, `DbtDebuggerEnv` |
| `dbt_debugger.py` | `load_environment()` entrypoint |
| `tests/` | Pytest smoke for workspace, dbt compile, scoring |
| `outputs/` | Local `prime eval run` artifacts (ignored by git from repo root `.gitignore`) |

## Validate scenarios

```bash
cd environments/dbt_debugger
python validation/validate_scenarios.py
```

## Unit tests

```bash
cd environments/dbt_debugger
uv sync --extra dev
uv run --extra dev pytest tests/ -v
```

## Install and eval (smoke)

```bash
prime env install dbt-debugger
prime eval run dbt-debugger -m openai/gpt-4.1-mini -n 2 -r 1
```

Filter one scenario:

```bash
prime eval run dbt-debugger -a '{"scenario_id":"join_fanout_exec_revenue"}' -n 1 -r 1
```

Raise the tool turn budget (passed into `load_environment`):

```bash
prime eval run dbt-debugger -a '{"scenario_id":"join_fanout_exec_revenue","max_turns":25}' -n 1 -r 1
```

## `load_environment` arguments

| Argument | Description |
|----------|-------------|
| `scenario_id` | Optional stem of one JSON file under `scenarios/gold/` |
| `difficulty_tier` | Optional filter `1`–`4` |
| `scenario_set` | Must be `"gold"` (only bundled set) |
| `max_scenarios` | Cap rows after filters; `-1` = all |
| `max_turns` | Max model/tool turns per rollout (default `20`) |

## Tools (model-visible)

- `list_files`, `read_file`, `search_project` — scoped to the temp project and `artifact_manifest.tool_visible_globs` (plus `debug_context/**`, `target/**`, `logs/**` for reads).
- `run_dbt_command` — structured subcommand interface (`parse`, `compile`, `ls`, `run`, `test`, `build`) with explicit selector/resource filters; prompt-controlled flags like `--vars` are rejected. Uses rollout-local `DBT_PROFILES_DIR`. If the `dbt` binary is not on `PATH`, the tool falls back to `python -m dbt` using the same interpreter.
- `read_artifact` — same read rules as `read_file` for logs / `target/`.
- `submit_diagnosis` — structured fields plus grounded evidence refs (`file_span`, `sample_rows`, `run_history`); ends the rollout when accepted.

Hidden paths (`profiles.yml`, DuckDB file) are injected via `args_to_skip` + `update_tool_args` and never appear in tool schemas.

## Required environment variables

None for the default environment. If you add a `JudgeRubric` later, validate keys with `vf.ensure_keys(...)` in `load_environment()`.

### Local API keys (`.env`)

`load_environment()` calls `python-dotenv` so variables from `.env` are available in-process. Files are merged with **first definition wins** (and never overriding variables already exported in the shell): `.env` in the current working directory, then `environments/dbt_debugger/.env`, then the repo root `.env` (parent of `environments/`). Put shared keys in the repo root file; override locally in cwd when needed.

For `prime eval run`, the Prime CLI still needs the same keys in the environment it uses to call inference unless you export them or use your shell’s dotenv integration; loading here helps Python entrypoints (and any code that runs after `load_environment()` inside the same process).
