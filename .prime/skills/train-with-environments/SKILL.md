---
name: train-with-environments
description: Plans and validates RL training with this repo's verifiers 0.4 taskset/env packages. Use for trainer compatibility checks, run configuration, reward diagnostics, and train/eval experiment design.
---

# Train with environments

Read `environments/AGENTS.md`, the package README, and the chosen trainer's current
documentation/config schema. These packages use `verifiers.v1`; the generated
`configs/rl/*.toml` files are not validated training recipes for them.

## Compatibility before launch

1. Establish which trainer/service the user wants and its resource/budget constraints.
   Do not assume Hosted Training supports the package's API, harness, local resources,
   or data restrictions. Check the selected integration before promising compatibility.
2. Validate the package with its tests and local `vf-validate`, then establish a small
   baseline through `scripts/prime_rl_eval.sh` (see `evaluate-environments`). Inspect
   reward distributions and errored episodes, not only the aggregate mean.
3. The eval wrapper pins and installs prime-rl for **evaluation**; it does not provision
   GPUs or launch training. For self-managed training, inspect the trainer checkout's
   documented entrypoint, config examples, GPU requirements, and verifiers dependency.
   Do not rerun Lab setup or copy old CLI/config fields as a compatibility workaround.
4. Verify exported taskset/env discovery, harness restrictions, resource setup/cleanup,
   trace/scoring behavior, and packaged data on the actual training runtime.

## Experiment design

- Reserve held-out tasks/data and define success, budget, and stop conditions before
  training. Keep model, sampling, and eval selection stable across comparisons.
- Confirm the trainer's units for batch size, rollout groups, concurrency, and async lag
  before choosing values. Do not copy old filtering/oversampling field names or formulas
  without checking the current schema.
- For binary rewards, examine solved/unsolved task balance; for continuous rewards,
  inspect per-task distributions rather than assuming pass/fail filtering applies.
- For flat rewards, investigate difficulty, scoring, prompt/tool mismatch, and runtime
  errors before scaling. For instability, inspect optimizer settings, rollout grouping,
  off-policy lag, and resource pressure in the selected trainer.
- Treat `dbt-debugger`'s grounded evidence and `menu-taste`'s fixed question keys as part
  of the contract, not signals to weaken until training appears to improve.

## Privacy and delivery

Do not upload private corpora/traces or enable upload monitors implicitly. Training and
evaluation providers receive task content; confirm permission for real menu data.
Hub publication is not required for local work; a push or hosted run requires explicit
authorization, destination/visibility, and validation of the intended artifact/runtime.

Return the chosen trainer/version, verified compatibility, config changes and rationale,
observed metrics/failures, and remaining blockers. Label proposed settings as untested
until run; do not claim training support from an eval-only smoke.
