---
name: review-environments
description: Reviews verifiers 0.4 taskset/env packages for correctness, robustness, privacy, and compatibility. Use for code review, migration validation, quality audits, or release readiness checks.
---

# Review environments

Read `AGENTS.md`, `environments/AGENTS.md`, and the package README. Review the v1 contract,
not whether the code follows the old factory/dataset/rubric API.

## Review workflow

1. Identify exported taskset/env/harness classes (`__all__`), typed configs, task loading,
   model-visible data, and private evaluator state. Check dependency requirements against
   `verifiers>=0.4.0` and the actual installed runtime.
2. Trace the task's `@vf.reward`, `@vf.metric`, `@vf.stop`, `validate(runtime)`, and
   `finalize` behavior. Check scoring from persisted traces, not only in-memory state.
   For ports, compare prompts, tools, termination boundaries, and scoring to the source.
3. Check per-task resources in `Toolset.setup_task`, typed shared state, async execution,
   and cleanup on failure/cancellation. Check custom env/harness protocols on their own
   terms rather than forcing single-agent defaults.
4. Check answer-key isolation: code-running harnesses must not expose host-side keys or
   private corpora. Preserve dbt-debugger/menu-taste's explicit harness restrictions.
5. Check packaged source/data outside the checkout, required system dependencies, and
   clear credential failures at the resource boundary. Inference keys should not be
   required for model-free validation.
6. Run the package's tests/validators and
   `uv run vf-validate <taskset-id> --runtime.type subprocess` from its directory.
   Verify `valid_rate == 1.0`, not just exit code. Use `prime env install` and artifact
   smoke where packaging/discovery is in scope.
7. Use `evaluate-environments` for a small model eval through `scripts/prime_rl_eval.sh`
   when needed and authorized; inspect planned vs. landed episodes and trace errors.
   Report missing runtime/model coverage rather than substituting old eval commands.

## Critical criteria

- Rewards must reflect the task contract; flag false positives, answer leakage, shortcuts,
  and metrics confused with the primary objective.
- Real menu evals need frozen questions and private output paths. Neither validation nor
  evaluation may silently upload private material; never add `--monitors.prime` for it.
- New packages need lifecycle/artifact coverage, not only unit tests. A passing CLI exit
  alone does not establish successful validation or error-free rollouts.
- Don't assume old generated eval/GEPA/training configs or hosted integrations support v1.
  Check the selected tool/version before claiming compatibility.

Return actionable findings first, ordered by severity, with file/line references, impact,
and fix direction. If none are found, say so and identify residual risk and untested areas.
