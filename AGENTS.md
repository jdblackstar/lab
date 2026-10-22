# AGENTS.md

## Workspace and API

This is an existing Prime Lab workspace. Keep environment packages self-contained under
`environments/<env_name>/`, with their own `pyproject.toml`, implementation, data, and
README. Read `environments/AGENTS.md` and the package README before changing an environment.

- The environments use **verifiers 0.4, API `verifiers.v1`**. Follow the taskset/task/env
  contracts in the current packages, not the old dataset/rubric environment API.
- `dbt_debugger` and `menu_taste` export taskset and env classes through `__all__`.
  Do not require a `load_environment()` factory or introduce v0 environment base classes.
- Use each environment's own virtualenv (`uv sync --extra dev`, then `uv run ...` from
  its directory). The root project's dependency/lockfile is not the environment runtime.
- `.prime/skills/` contains repo-specific create, browse, review, eval, GEPA, training,
  and brainstorming guidance. Do not regenerate it from older Lab templates.

## Development and validation

- Scaffold new packages with verifiers 0.4's `vf-init`, using an environment virtualenv
  that has it installed. Check the generated template against the local package patterns.
- `prime env install <env-id>` remains supported for local installation from the repo
  root; it is not the evaluation runner.
- Run model-free validation with `uv run vf-validate <env-id> --runtime.type subprocess`
  from the environment directory, plus its tests and any corpus-specific validators.
  Check the validation summary's `valid_rate`, not just the exit status.
- Run model evaluations through `scripts/prime_rl_eval.sh <env-path> <taskset-id> ...`.
  It uses a pinned prime-rl checkout, a separate Python 3.12 venv, and `uv run eval`.
  `vf-eval` is deprecated; do not use the old `prime eval run` examples for these packages.
- Read the runner's help and the package README for typed flags/configs. The generated
  `configs/eval`, `configs/gepa`, and `configs/rl` examples are not automatically compatible
  with the current runners. `configs/endpoints.toml` is not automatically consumed by
  prime-rl; do not assume its aliases resolve as model IDs.
- Inspect rollout errors and saved traces, not just rewards or a zero exit code.
- When adding an environment, extend lifecycle coverage in
  `scripts/smoke_prime_lifecycle.sh`, `scripts/smoke_prime_artifact.sh`, or a dedicated CI
  smoke as appropriate: installation, v1 discovery, model-free validation, packaged data,
  and a minimal eval when supported. Pytest discovery is already automatic for packages
  with `pyproject.toml`, a `tests/` directory, and a `dev` extra.

## Secrets, privacy, and publishing

- Document and check required credentials where the relevant client/resource is created;
  do not require inference credentials for model-free taskset loading or validation.
- Prime-rl saves local file-monitor results. `--monitors.prime` opts into uploading traces;
  do not claim every eval is automatically uploaded or visible in `prime eval tui`.
- Menu corpora and traces can contain private material. Keep them under the package's
  ignored `private/` directory, use the local subprocess runtime for validation, and never
  add `--monitors.prime` for private menu evaluations. Provider calls also send menu text
  off-machine; check permission before using real menus.
- Preserve package-specific harness/runtime restrictions and answer-key isolation.
- Publish only when explicitly authorized and after validation. Confirm the destination
  and `PUBLIC`/`PRIVATE` visibility; do not make a Hub push a prerequisite for local work.
