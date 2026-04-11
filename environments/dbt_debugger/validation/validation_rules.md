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

## Rubric contract

11. **Accepted diagnoses**: Every scenario must define `rubric_hints.accepted_diagnoses[]` with explicit `required_models`, `allowed_models`, `root_cause_all_of`, and `fix_variants`.
12. **Grounded evidence**: `required_evidence` must point to resolvable artifacts (`file_span`, `sample_rows`, or `run_history`), not free-text hints.
13. **No-bug guardrails**: `has_bug: false` scenarios should include structured `forbidden_claims`.

## Artifact manifest

14. **Immutable paths exist**: Every `artifact_manifest.immutable_paths[]` must match a `dbt_project.files[].path`.
15. **Globs**: `tool_visible_globs` entries are glob patterns; validator may skip strict existence checks.

## Corpus coverage (gold set)

When validating the whole `scenarios/gold/` directory:

16. **Category coverage**: At least one scenario must tag each of: `join`, `incremental`, `source_schema`, `logic`, `macro`, `config`, `no_bug`.
17. **Tier targets**: The gold set should meet the `2/3/3/2` target for tiers `1/2/3/4`.
18. **Bug balance**: The gold set should include at least 4 `no_bug` scenarios.
19. **Pure category checks**: Include at least one pure `logic` scenario and one pure `config` scenario.

## SQL hygiene (optional linter)

20. No Markdown triple-backtick fences inside JSON string fields.
21. Prefer `\n` newlines inside SQL strings; avoid unescaped raw newlines if they break JSON (files must remain valid JSON).

Run checks:

```bash
cd environments/dbt_debugger
uv run python validation/validate_scenarios.py
```
