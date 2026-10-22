---
name: evaluate-environments
description: Runs and analyzes verifiers 0.4 environment evaluations using the repo's pinned prime-rl runner. Use for smoke tests, model comparisons, benchmark sweeps, resuming runs, and sample-level failure analysis.
---

# Evaluate environments

Read `environments/AGENTS.md` and the package README. These packages use verifiers v1;
the old Prime eval command/config examples are not their eval path.

## Validate before spending model calls

Use the environment's own project/venv. From its directory:

```bash
uv sync --extra dev
uv run vf-validate <taskset-id> --runtime.type subprocess
```

Require `valid_rate == 1.0` in the saved `summary.json`. Validation checks tasksets, not
env defaults, so the explicit local runtime matters. Run package-specific tests/validators
when changing behavior. Never interpret menu-taste's bundled synthetic smoke data as a
real benchmark; use a frozen question set for real model comparisons.

## Run with pinned prime-rl

From the repo root:

```bash
scripts/prime_rl_eval.sh environments/dbt_debugger dbt-debugger \
  -m deepseek/deepseek-v4-flash -n 2 -r 1 -c 2 \
  --output-dir outputs/dbt-debugger --run.name smoke
```

The wrapper checks out pinned prime-rl, syncs its Python 3.12 venv, installs the environment
there, and runs `uv run eval`. It works independently of the root environment's verifiers
version. `vf-eval` is deprecated in favor of this runner.

- Start small, inspect samples/errors, then scale within the authorized budget.
- `-n` limits tasks, `-r` sets rollouts per task, `-c` bounds concurrency, and `-s`
  shuffles task selection under `--select.seed`. `-s` does not enable saving.
- Pass typed flags: `--env.taskset.difficulty-tier 2`,
  `--env.taskset.questions-path <absolute-path>`, `--env.taskset.rotation 2`, or
  `--env.agent.max-turns 25`. Validation uses `--taskset.*` instead.
- Filter named tasks with `--select.include.ids '["join_fanout_exec_revenue"]'`.
- Use canonical provider model IDs. The wrapper does not read `configs/endpoints.toml`;
  don't assume an `endpoint_id` alias is a model ID. Check the pinned runner's `--help`
  for client/endpoint configuration before using another provider.
- For config files and sweeps, use the pinned runner's schema and `@ file.toml` syntax,
  not the generated v0 `[[eval]]`/`[[ablation]]` examples. Dry-run configs before model calls.
- Resume with the same output directory, run identity, and config using `--resume`.
- Concurrent wrapper invocations need distinct `PRIME_RL_DIR`s: each invocation syncs
  and reinstalls its package into that checkout's venv.

## Save, inspect, and protect results

Prime-rl's file monitor saves locally under `<output-dir>/<run.name>/`. Inspect:

- `configs/` for resolved settings and `logs/latest/eval.log` for errors;
- `monitors/file/plan.json` for the planned episodes and
  `monitors/file/traces/stream.index.jsonl` for landed episodes: require every planned
  episode, `ok: true`, and `num_errors: 0`;
- the compressed trace stream under `monitors/file/traces/stream/` for actual replies,
  tool calls, and scoring. A zero process exit status does not guarantee clean rollouts.

Uploading is opt-in with `--monitors.prime`; do not promise automatic uploads or that
prime-rl files appear in the old eval TUI. Never upload private menu traces. Keep private
corpora, validation outputs, and eval outputs in `environments/menu_taste/private/`, and
confirm permission to send their contents to the inference provider. Follow the package
README's export/scoring commands for frozen question sets and rotations.

Report the exact command/config, model, data selection, sampling, error rate, metrics,
and representative failures. Keep these fixed across comparisons; use pass@k only for
binary rewards and don't overinterpret tiny samples. Publication is not required for
local runs and needs separate approval.
