---
name: create-environments
description: Creates or migrates verifiers 0.4 taskset/env packages in this Lab workspace. Use when building a new environment, porting a benchmark, or adapting Hub source to the repo's v1 API.
---

# Create environments

Read `AGENTS.md`, `environments/AGENTS.md`, and the closest package README first.
Use **`import verifiers.v1 as vf`**, not the v0 dataset/rubric/factory API.

## Scaffold and implement

1. Use verifiers 0.4's `vf-init`. From the repo root, the existing menu-taste project
   provides the tool without relying on the root venv:
   ```bash
   uv run --project environments/menu_taste vf-init my-env --path environments
   ```
   Check `vf-init --help` for toolset (`-T`) or custom harness (`-H`) scaffolding.
   Do not rerun Lab setup over this workspace or overwrite existing packages.
2. Define the contract before coding: visible prompts, private answer keys, allowed
   actions, stop conditions, scoring, metrics, and data splits. For a port, map the
   source's prompts, tool I/O, termination, and scoring explicitly and preserve them.
3. Implement typed `TaskData`, `TaskConfig`/`TasksetConfig`, a `Task`, and `Taskset.load()`.
   Put rewards/metrics/stops on the task with v1 decorators and implement a meaningful
   `validate(runtime)` gold check. Use `Trace` for replies, state, and persisted info.
4. Export taskset/env classes through `__all__`. Pin intentional defaults in typed env
   and agent config; use `SingleAgentEnv` for standard loops or a custom env/harness for
   other protocols. Preserve answer-key isolation; don't grant a model host-shell access.
5. Put stateful tools in a `Toolset` with `@vf.tool`, per-task setup, typed shared state,
   and cleanup. Follow `dbt_debugger/toolset.py`, not hidden v0 tool-argument injection.
6. Declare `verifiers>=0.4.0` and other dependencies; package required data in wheel and
   sdist. Document system prerequisites and secrets at their resource boundary. Model-free
   loading/validation should not need inference credentials.

## Verify and hand off

From the new package directory:

```bash
uv sync --extra dev
uv run pytest tests/ -q
uv run vf-validate my-env --runtime.type subprocess
```

From the repo root, verify `prime env install my-env`, then run the package through
`scripts/prime_rl_eval.sh environments/my_env my-env -m <provider/model> -n 5 -r 1 -c 2`.
Inspect the validation summary and eval trace index, not just exit codes. Follow
`evaluate-environments` for flags, privacy, and result inspection.

Add lifecycle/artifact smoke coverage alongside the environment; pytest discovery alone
doesn't check discovery or shipped assets. Report exact checks and any unavailable eval
coverage. Do not promise training compatibility without checking the selected trainer.
Publish only with explicit authorization of destination and visibility after validation;
a Hub push is not a prerequisite for local evals. Never bundle private menu data for upload.
