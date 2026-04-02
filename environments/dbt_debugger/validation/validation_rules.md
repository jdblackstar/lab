# Scenario validation rules

This document lists checks beyond JSON Schema structure. Implementations should apply **both** `scenario.schema.json` and these rules.

## Structural

1. **Filename ↔ `scenario_id`**: The stem of `*.json` must equal `scenario_id`.
2. **`schema_version`**: Must be `1`.
3. **`failure_categories`**: Each value must be one of: `join`, `incremental`, `source_schema`, `logic`, `macro`, `config`, `no_bug`.
4. **`has_bug` consistency**: If `has_bug` is `false`, `failure_categories` must include `no_bug` and `ground_truth.root_cause` must begin with `No bug`.

## DAG vs files

5. **Model paths exist**: Every `dag.models[].path` must appear exactly once as `dbt_project.files[].path`.
6. **Sources file**: If any model uses `{{ source(...) }}`, `models/sources.yml` (or declared sources path) should exist in `dbt_project.files`.

## Sample data

7. **Row keys**: Every key in each `sample_data.*.rows[]` object must appear in that table's `columns[].name`.
8. **Column types**: Optional soft check — types are informational; rows should be JSON-serializable scalars.

## Ground truth

9. **Affected models subset**: Every `ground_truth.affected_models[]` must be in `dag.models[].name`.
10. **Empty when no bug**: If `has_bug` is `false`, `ground_truth.affected_models` should be `[]`.

## Artifact manifest

11. **Immutable paths exist**: Every `artifact_manifest.immutable_paths[]` must match a `dbt_project.files[].path`.
12. **Globs**: `tool_visible_globs` entries are glob patterns; validator may skip strict existence checks.

## Corpus coverage (gold set)

When validating the whole `scenarios/gold/` directory:

13. **Category coverage**: At least one scenario must tag each of: `join`, `incremental`, `source_schema`, `logic`, `macro` or `config`, `no_bug`.
14. **Tier spread**: Recommend at least one tier ≥ 3 and one `no_bug` scenario.

## SQL hygiene (optional linter)

15. No Markdown triple-backtick fences inside JSON string fields.
16. Prefer `\n` newlines inside SQL strings; avoid unescaped raw newlines if they break JSON (files must remain valid JSON).

Run checks:

```bash
cd environments/dbt_debugger
uv run python validation/validate_scenarios.py
```
