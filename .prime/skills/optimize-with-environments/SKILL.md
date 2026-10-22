---
name: optimize-with-environments
description: Optimizes verifiers 0.4 task system prompts with vf-gepa. Use to plan GEPA runs, compare baseline and optimized prompts, or inspect optimization results without gradient training.
---

# Optimize with environments

Read `environments/AGENTS.md` and validate scoring before optimization. This workflow uses
verifiers 0.4's **`vf-gepa`**, not the old Prime GEPA command or generated config schema.

## Workflow

1. Establish a baseline with the pinned prime-rl runner (`evaluate-environments`). Fix
   reward bugs/leakage before optimizing. Separate training, validation, and final holdout
   tasks and keep model/sampling/selection consistent across comparisons.
2. From the environment's own project, inspect `uv run vf-gepa <taskset-id> --help`.
   Use typed `--env.taskset.*`, `--env.agent.*`, `--client.*`, and `--reflection-client.*`
   settings. Check optional optimizer dependencies before spending model calls.
3. Dry-run a bounded config first. For example, from `environments/dbt_debugger`:
   ```bash
   uv run vf-gepa dbt-debugger -m deepseek/deepseek-v4-flash \
     --num-train 5 --num-val 5 --max-total-rollouts 20 -c 2 --dry-run
   ```
   Remove `--dry-run` only for an authorized optimization run. Choose split sizes that
   fit the available tasks; do not blindly use the defaults on small tasksets.
4. Use `--reflection-model` for the teacher, `--reflection-minibatch-size` for reflection
   batches, and `--reflection-columns` for selected trace/task context. Ensure those
   fields are safe to send to the teacher. Do not reuse the v0 short flags or
   `configs/gepa/*.toml` without converting and validating them against this CLI.
5. Inspect the run's resolved config, saved traces, and candidate/run logs under its output
   directory. Use the emitted best system prompt for a held-out prime-rl eval with
   `--env.taskset.system-prompt <path>`. Never substitute validation improvements for
   held-out evidence.

Private menus and answer keys must not leak via reflection, saved outputs, or monitoring.
Keep private outputs in `private/`, avoid upload monitors, and get permission before
sending private content to rollout or reflection providers. A dry-run validates config,
not the optimizer's actual behavior; report that distinction.

Return baseline vs. held-out metrics, prompt changes, budget used, limitations, and a
recommendation to adopt, iterate, or stop. Don't claim a run was executed from a dry-run.
