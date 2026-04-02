# dbt-debugger

Verifiers environment for **dbt pipeline debugging**: triaging ambiguous stakeholder symptoms, investigating models and sources, and producing correct diagnoses (and recognizing false alarms).

## Status

- **Scenario corpus**: Gold JSON scenarios under `scenarios/gold/` with schema in `spec/scenario_schema.md`.
- **Runtime**: `load_environment()` returns a `SingleTurnEnv` with a **zero-weight placeholder rubric** so you can smoke-test installs and prompts. **Stateful dbt tools and deterministic diagnosis scoring** are planned — see `spec/runtime_mapping.md`.

## Layout

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata, dependencies, Hatch `include` (ships JSON/spec), `[tool.verifiers.eval]` defaults |
| `spec/scenario_schema.md` | Canonical JSON field definitions |
| `spec/authoring_guide.md` | How to write new scenarios |
| `spec/runtime_mapping.md` | Corpus → `StatefulToolEnv` mapping |
| `scenarios/gold/*.json` | Reviewed scenarios |
| `validation/` | JSON Schema + `validate_scenarios.py` |
| `runtime/` | Stubs for future tool/workspace/scoring modules |
| `dbt_debugger.py` | `load_environment()` entrypoint |
| `outputs/` | Local `prime eval run` artifacts (ignored by git from repo root `.gitignore`) |

## Validate scenarios

```bash
cd environments/dbt_debugger
python validation/validate_scenarios.py
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

## `load_environment` arguments

| Argument | Description |
|----------|-------------|
| `scenario_id` | Optional stem of one JSON file under `scenarios/gold/` |
| `difficulty_tier` | Optional filter `1`–`4` |
| `scenario_set` | Must be `"gold"` (only bundled set) |
| `max_scenarios` | Cap rows after filters; `-1` = all |

## Required environment variables

None for the placeholder environment. If you add a `JudgeRubric` later, validate keys with `vf.ensure_keys(...)` in `load_environment()`.
