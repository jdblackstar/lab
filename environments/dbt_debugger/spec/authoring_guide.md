# DBT Debugger — Scenario Authoring Guide

This guide turns a broad “generate realistic dbt bugs” prompt into repeatable, reviewable benchmark authoring. It complements [scenario_schema.md](scenario_schema.md).

## Goals

1. **Realism over cleverness** — Every scenario should mirror production pain (silent fanouts, incremental drift, source renames, bad macros, wrong vars).
2. **Symptom far from cause** — The stakeholder message must not name files, lines, or models.
3. **Multiple plausible theories** — Populate `hypothesis_space` with at least two plausible `true` hypotheses for medium+ tiers.
4. **False alarms** — At least some scenarios must have `has_bug: false`; penalize agents that always “find a bug.”
5. **Executable later** — Every scenario must be materializable as a dbt project tree from `dbt_project.files` without hand-editing.

## Difficulty tiers (bell curve)

| Tier | Count target | Symptom ↔ cause distance | Hypotheses | Time (human) |
|------|--------------|------------------------|------------|--------------|
| 1 | 2 | Same model or 1 hop | 1 clear | ~15 min |
| 2 | 3 | 1–2 hops | 2 plausible | ~30 min |
| 3 | 3 | 2–3 hops or interactions | 3+ plausible | 1–2 h |
| 4 | 2 | Subtle interaction or no bug | Deep elimination | Senior+ |

When batch-authoring with an LLM, **generate one scenario per call** against the JSON schema to reduce inconsistency.

## Symptom writing

- Use **Slack / ticket** voice: urgency, missing context, wrong dashboard slice.
- Avoid: SQL snippets, dbt errors pasted verbatim, “check line 47.”
- Do include: **when** it started, **which metric** looks wrong, **business impact** cue.
- Keep `title`, `run_history.summary`, and `sample_data.description` neutral; they should not restate the answer key.

## DAG and SQL

- **4–8 models** in `dag.notation`; label red herrings that share sources but are innocent.
- SQL must use idiomatic dbt: `{{ ref() }}`, `{{ source() }}`, CTEs, realistic naming.
- For incremental models, include `{% if is_incremental() %}` when the bug category needs it.
- For macros, put Jinja in `macros/` files and reference from models.
- Keep SQL **complete enough** that the bug is discoverable by reading—**not** obvious from naming alone.

## Sample data

- **5–10 rows** per key table; types must match `columns`.
- If the symptom is **double-counting**, show duplicate keys or fanout in data.
- If **no bug**, data must be **internally consistent** with correct SQL—only the stakeholder interpretation is wrong.

## Run history and tests

- Include tests that **passed but are weak** (e.g. `not_null` only) when realistic.
- Warnings: schema migration, deprecation, adapter quirks.
- Align `model_results` with the actual failure mode (fail upstream of symptom).

## Ground truth discipline

- `root_cause`: **one primary cause**; mention interactions only when tier ≥ 3.
- `affected_models`: minimal set that must change for a **real** bug (`[]` for false alarms). This is the **evaluator gold list** only; agents submit the same semantics under the tool field name `buggy_models` (must be empty when `has_bug` is false).
- `fix`: concrete—model name + change class (join key, incremental predicate, macro, var).
- `common_misdiagnoses`: **specific** wrong theories an eager LLM would jump to.

## Rubric hints

- `pass_criteria`: human-readable notes about what a correct diagnosis should cover.
- `accepted_diagnoses`: make the runtime contract explicit with `required_models`, `root_cause_all_of`, and alternative `fix_variants`. `allowed_models` may be omitted when it is exactly the same as `required_models`.
- `required_evidence`: tie each requirement to a resolvable artifact (`file_span`, `sample_rows`, or `run_history`) rather than free-text keywords.
- For `no_bug`: add structured `forbidden_claims` patterns like “rewrite the mart” or “the warehouse is corrupting data.”
- Before finalizing a scenario, make sure the prose `ground_truth` answer itself satisfies at least one `accepted_diagnoses` variant so reviewer docs and runtime scoring stay aligned.

## Category coverage checklist

Each gold corpus should include at least one scenario tagged with:

- [ ] `join`
- [ ] `incremental`
- [ ] `source_schema`
- [ ] `logic`
- [ ] `macro` or `config` (at least one; both is OK)
- [ ] `no_bug`

## Review checklist (human)

- [ ] JSON validates against `validation/scenario.schema.json`.
- [ ] Filename matches `scenario_id`.
- [ ] No fenced Markdown inside JSON strings.
- [ ] `ground_truth` consistent with SQL + `sample_data`.
- [ ] `artifact_manifest.immutable_paths` covers seeds/tests if tamper-evidence is needed later.

## Anti-patterns

- **Puzzle SQL** — tricks that do not happen in real warehouses.
- **Omniscient stakeholder** — messages that encode the fix.
- **Singleton hypotheses** — tier ≥ 2 with only one theory.
- **Orphan files** — paths in DAG not present in `dbt_project.files`.
