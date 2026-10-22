# AGENTS.md

This is a Prime Lab workspace for verifiers v1 environments, not the verifiers repository. The bundled skills in `.prime/skills/` (linked from `.cursor/skills/`) are verbatim copies of `brainstorm`, `create-environments`, and `evaluate-environments` from `skills/` in [verifiers v0.4.0](https://github.com/PrimeIntellect-ai/verifiers/tree/v0.4.0); its `release` skill publishes verifiers itself and is omitted. They are written from inside the verifiers checkout, so where a skill's commands or paths disagree with this file, follow this file.

## Writing code

From the verifiers v0.4.0 `AGENTS.md`, unchanged:

- **Code is the source of truth**: before writing anything, read the v1 code for existing helpers, harnesses, and interfaces instead of reinventing them. Prefer verifiers-native task, trace, server, harness, and runtime interfaces over repeated path/import/discovery plumbing in user packages.
- **Minimal config surface**: expose as few knobs as possible, but as many as needed.
- **Keep tasksets small**: a basic taskset fits in a few dozen idiomatic lines — typed data/task/config classes, `load()`, and decorated scoring on the task. Don't override `Taskset.__init__` (implement `load()`); don't override `Harness.__init__` (use `setup()`).

Each environment lives in its own project under `environments/<name>/` with its own `pyproject.toml`, `uv.lock`, README, and `tests/`. Read that README before changing or running the environment; it documents the package's supported commands.

## Running code

- **Use each environment's project, not the root**: the root project pins legacy `verifiers` 0.1.x, so the root `vf-*` entrypoints are the old CLIs. Run every `vf-*` command through an environment project on `verifiers>=0.4.0`, preferably from its directory (`cd environments/<name> && uv run ...`). `uv run --project environments/<name> ...` also works from the root, but writes `outputs/` into the root unless you pass `-o`.
- **Scaffold environments** from the root with `uv run --project environments/dbt_debugger vf-init <name> -p environments` (`-T`/`-H` add a toolset or harness). The scaffold writes an unpinned `verifiers`, so pin `verifiers>=0.4.0` in the new `pyproject.toml`, add a `dev` extra with `pytest` and a `tests/` directory, run `uv lock` in the new directory, and add the environment to `.agents/setup`, `scripts/smoke_prime_lifecycle.sh`, and `scripts/smoke_prime_artifact.sh`. `scripts/ci/run_environment_pytests.sh` picks up any environment with `pyproject.toml` and `tests/`.
- **Evaluate with the pinned prime-rl runner**, not `vf-eval`: `scripts/prime_rl_eval.sh environments/<name> <env-id> -m <model> -n <N> -r <R> -c <C>`. It needs `PRIME_API_KEY`. Check the eval's own output for rollout errors, because it exits 0 when rollouts fail; each environment README says where to look and which flags are safe for its data.
- **Validate without a model first**: `uv run vf-validate <id> --runtime.type subprocess` from the environment directory runs the gold and noop checks locally. It exits 0 even when checks fail, so check `valid_rate` in the run's `summary.json`.
- **Keep private data private**: eval traces and `vf-validate` output over private data such as `environments/menu_taste/private/` contain that data. Keep them under `private/` and never pass `--monitors.prime` or upload them.

## Optimization and training

No bundled skill covers these yet; verifiers v0.4.0 does not ship one. When `brainstorm` hands off to optimization or training, use these commands:

- **Prompt optimization**: `uv run vf-gepa <taskset-id> -m <model> ...` from the environment directory (`uv run vf-gepa -h` lists options). The `configs/gepa/` examples use a legacy schema (`[gepa]`, `[execution]`, `[env] env_id`, `endpoints_path`) that the current `vf-gepa` rejects; translate them with `-h` (for example `max_calls` → `max_total_rollouts`, `minibatch_size` → `reflection_minibatch_size`) and check the result with `--dry-run` before running it.
- **Hosted RL training**: `prime train <config.toml>`. The `configs/rl/` examples reference Hub environment IDs, so push the environment with `prime env push --path environments/<name>` first, after the user chooses its visibility. No environment in this workspace has been trained yet.

## Testing

- **Run the workspace checks**: `scripts/ci/run_environment_pytests.sh` runs each environment's tests in its own project, which is what CI runs. For a single environment, `cd environments/<name> && uv sync --extra dev && uv run pytest tests/`. Lint with `uv run ruff check .` from the root.
- **Model-free lifecycle smoke**: `scripts/smoke_prime_lifecycle.sh` installs each environment with `prime env install` and runs `vf-validate`; it runs a model eval only when `PRIME_API_KEY` is set.
