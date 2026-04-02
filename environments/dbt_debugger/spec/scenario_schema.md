# DBT Debugger — Scenario JSON Schema (Authoritative Spec)

This document defines the canonical structure for each gold scenario file under `scenarios/gold/`. All fields are designed to map later onto a `vf.StatefulToolEnv` rollout: materialized dbt workspace, hidden tool state, structured `submit_diagnosis`, and deterministic rubric checks.

## File conventions

- One scenario per file: `scenarios/gold/<scenario_id>.json`.
- `scenario_id` MUST match the filename stem (without `.json`).
- UTF-8, valid JSON. No Markdown code fences inside string values—use plain multiline strings for SQL.
- Version the schema with `schema_version` (currently `1`).

## Top-level object

| Field | Type | Required | Visibility | Description |
|-------|------|----------|------------|-------------|
| `schema_version` | `integer` | yes | evaluator | Must be `1`. |
| `scenario_id` | `string` | yes | tool + evaluator | Stable slug, `[a-z0-9_]+`. |
| `title` | `string` | yes | evaluator | Short maintainer title; keep it neutral because it should not appear in prompts. |
| `difficulty_tier` | `integer` | yes | tool | `1`–`4` per benchmark difficulty curve. |
| `failure_categories` | `string[]` | yes | evaluator | One or more of: `join`, `incremental`, `source_schema`, `logic`, `macro`, `config`, `no_bug`. |
| `has_bug` | `boolean` | yes | evaluator | `false` for false-alarm scenarios. |
| `metadata` | `object` | yes | mixed | See [Metadata](#metadata). |
| `symptom` | `object` | yes | tool | Stakeholder report shown to the model. |
| `dag` | `object` | yes | evaluator | DAG description and model list used by the evaluator/runtime, not the prompt. |
| `dbt_project` | `object` | yes | tool | Files that materialize into the rollout workspace. |
| `sample_data` | `object` | yes | tool | Tabular samples keyed by logical table/source name. |
| `run_history` | `object` | yes | tool | Synthetic dbt run / test summary. |
| `ground_truth` | `object` | yes | evaluator | Immutable answer key for scoring (not shown to model). |
| `rubric_hints` | `object` | yes | evaluator | Pass criteria and evidence expectations for deterministic checks. |
| `hypothesis_space` | `object[]` | yes | evaluator | Plausible explanations (used for authoring + optional judge prompts). |
| `red_herrings` | `object[]` | no | evaluator | Tempting wrong paths. |
| `artifact_manifest` | `object` | yes | evaluator | Lists paths the runtime may expose vs hide. |

### Visibility legend

- **tool**: May appear in prompts, tool-visible file trees, or structured tool results (subject to `artifact_manifest`).
- **evaluator**: Loaded into rollout state for `update_tool_args` / rubric only; MUST NOT be leaked in user-facing prompts.

---

## Metadata

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `author` | `string` | no | Maintainer or `benchmark`. |
| `created` | `string` | no | ISO date. |
| `tags` | `string[]` | no | Free-form tags (e.g. `revenue`, `stripe`). |
| `estimated_minutes` | `number` | no | Rough human solve time for calibration. |

---

## Symptom (`symptom`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | `string` | yes | e.g. `slack`, `jira`, `email`. |
| `from_role` | `string` | yes | e.g. `analytics`, `exec_assistant`. |
| `message` | `string` | yes | Realistic, underspecified stakeholder text. No file/line hints. |

---

## DAG (`dag`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `notation` | `string` | yes | Human-readable DAG lines using `source('...') → ref('...')` style. |
| `models` | `object[]` | yes | Each: `name`, `path` (relative to project root), `role` (`staging`, `intermediate`, `mart`, `seed`, `other`). |

---

## DBT project (`dbt_project`)

Materialization rules:

- `files` is an array of `{ "path": "models/...", "content": "..." }` using forward slashes.
- MUST include at minimum: `dbt_project.yml`, `packages.yml` (can be empty deps), and every model referenced in `dag.models`.
- SQL is **plain text** inside JSON strings (no ``` fences).

Optional nested objects (if used):

| Field | Type | Description |
|-------|------|-------------|
| `macros` | `object[]` | `{ "path": "macros/...", "content": "..." }` |
| `seeds` | `object[]` | `{ "path": "seeds/...", "content": "csv..." }` |

---

## Sample data (`sample_data`)

Keyed by logical name (e.g. `source_stripe__payments`). Each value:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | `string` | no | What this table represents. |
| `columns` | `object[]` | yes | `{ "name", "type" }` — types are logical (`string`, `integer`, `numeric`, `timestamp`, `boolean`). |
| `rows` | `object[]` | yes | 5–10 objects; keys match `columns`. Values MUST be consistent with `ground_truth` and SQL. |

---

## Run history (`run_history`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `summary` | `string` | yes | Short narrative of what ran. |
| `commands` | `object[]` | no | `{ "command", "exit_code", "duration_s" }`. |
| `model_results` | `object[]` | yes | `{ "model", "status" }` where `status` in `success`, `failed`, `skipped`. |
| `tests` | `object[]` | yes | `{ "name", "status", "message" }` — include misleading passes where realistic. |
| `warnings` | `string[]` | no | dbt warnings, adapter notes, deprecation hints. |

---

## Ground truth (`ground_truth`) — evaluator only

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `root_cause` | `string` | yes | Precise technical cause, or `No bug — ...`. |
| `affected_models` | `string[]` | yes | Model names from `dag.models`. |
| `fix` | `string` | yes | Correct fix or `No fix needed — ...`. |
| `common_misdiagnoses` | `string[]` | yes | 2–3 plausible wrong conclusions. |
| `investigation_path` | `string[]` | yes | Ordered expert steps (for rubric alignment). |

---

## Rubric hints (`rubric_hints`) — evaluator only

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pass_criteria` | `string[]` | yes | Human-readable reviewer notes about what a correct diagnosis should cover. |
| `accepted_diagnoses` | `object[]` | yes | Deterministic scoring contract. Each item declares `required_models`, `allowed_models`, `root_cause_all_of`, and `fix_variants`. `root_cause_all_of` is a list of synonym groups where at least one phrase in each group must appear. `fix_variants` is a list of alternative claim patterns, each using the same synonym-group format. |
| `required_evidence` | `object[]` | yes | Grounded artifact requirements. Use one of: `file_span` (`path`, `all_of`), `sample_rows` (`table`, `match`, optional `min_rows`, `all_of`), or `run_history` (`record_type`, plus fields such as `contains`, `model`, `name`, `status`). |
| `forbidden_claims` | `claim_pattern[]` | no | Negative claim patterns for `no_bug` scenarios. Each pattern is a list of synonym groups; if all groups match, scoring fails. |

---

## Hypothesis space (`hypothesis_space`)

Array of objects:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Short id. |
| `hypothesis` | `string` | yes | Plain-language theory. |
| `plausible` | `boolean` | yes | `true` if expert would consider before ruling out. |

---

## Red herrings (`red_herrings`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Short id. |
| `description` | `string` | yes | Why this path is tempting. |
| `why_wrong` | `string` | yes | Brief refutation. |

---

## Artifact manifest (`artifact_manifest`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tool_visible_globs` | `string[]` | yes | Glob patterns relative to project root the model may read via tools. |
| `evaluator_only_paths` | `string[]` | yes | Paths never exposed to tools (e.g. precomputed hashes, answer keys). |
| `immutable_paths` | `string[]` | yes | Files that MUST NOT be mutated by the agent (for integrity checks). |

---

## Mapping to Verifiers (preview)

- **Dataset row**: `question` or `prompt` built from `symptom` + generic instructions only; do not expose `title`, `dag`, or exact debug-context filenames.
- **`setup_state`**: Copy `dbt_project.files` (+ seeds/macros) into `workspace_root`; attach `ground_truth` / `rubric_hints` to state for scoring only.
- **Tools**: See [runtime_mapping.md](runtime_mapping.md).
- **Rubric**: Compare structured `submit_diagnosis` payload to `rubric_hints.accepted_diagnoses` and grounded evidence requirements deterministically first.

---

## Invariants (validators MUST enforce)

1. `scenario_id` matches filename stem.
2. `schema_version == 1`.
3. Every `dag.models[].path` has a matching `dbt_project.files[].path`.
4. `failure_categories` non-empty; if `has_bug == false`, `no_bug` MUST be present and `root_cause` MUST start with `No bug`.
5. `sample_data` row keys ⊆ declared columns.
6. `ground_truth.affected_models` ⊆ `dag.models[].name`.
7. `artifact_manifest.immutable_paths` ⊆ paths that exist in `dbt_project.files`.
