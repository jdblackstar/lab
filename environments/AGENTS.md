# Environment development

## Contract: verifiers 0.4 / `verifiers.v1`

Use the package README and current implementation as the source of truth. This is not
the v0 dataset/rubric API; do not port the old `load_environment`, `SingleTurnEnv`,
`StatefulToolEnv`, or `Rubric` patterns into these packages.

- Import `verifiers.v1 as vf` and declare `verifiers>=0.4.0` in each package.
- Put task inputs/answer keys in a typed `vf.TaskData` subclass and rollout state in a
  typed `vf.State` subclass. Keep evaluator-only data out of model prompts and tools.
- Implement a `vf.Task`: scoring via `@vf.reward` and `@vf.metric`, stop conditions via
  `@vf.stop`, and model-free gold checks via `validate(runtime)`. Use `vf.Trace` (for
  example `trace.last_reply`, `trace.state`, `trace.info`) rather than v0 completion dicts.
- Implement `vf.Taskset.load()` to yield tasks; use typed `TaskConfig`/`TasksetConfig`
  subclasses for configuration. Export discoverable taskset/env classes in the package
  `__all__`, following `dbt_debugger/__init__.py` or `menu_taste/__init__.py`.
- For a standard single-agent loop, use `vf.SingleAgentEnv` and typed env/agent config to
  pin harness, runtime, and turn limits. Custom protocols can implement their own
  `vf.Env`/harness; do not force every environment into the single-agent pattern.
- Stateful tools are `vf.Toolset` servers with `@vf.tool` methods, returned by the
  task's `toolsets(config)`. Initialize task resources in `setup_task`, share typed state
  through `self.state`, and register cleanup on the toolset's exit stack. See
  `dbt_debugger/toolset.py`; paths and answer keys stay server-local, not in tool schemas.
- Avoid blocking the async rollout path; use async clients/subprocesses or offload
  blocking work with `asyncio.to_thread`. Make resource cleanup safe on errors/cancellation.

## Existing package behavior

- **dbt-debugger**: `DbtDebuggerTaskset` + `DbtDebuggerEnv`, tools-only `null` harness,
  subprocess runtime, 20 model turns. Tool calls in the last allowed reply still execute.
  The task stops on an accepted diagnosis, persists state in `finalize`, and scores
  grounded evidence deterministically. Run the scenario validator as well as tests.
- **menu-taste**: `MenuTasteTaskset` + `MenuTasteEnv`, `null` harness with no tools,
  subprocess runtime, one reply. Score the letter in `<answer>` tags. Use frozen question
  sets for comparisons; the bundled synthetic sample is for smoke tests only.
- Both envs refuse harnesses that execute code: host access would expose bundled answer
  keys or private corpora. Preserve those guards.
- When working on a branch containing **xmage-poc**, preserve its `XMageTaskset`, custom
  `XMageEnv` game loop, and `XMageHarness` contract rather than applying the two packages'
  single-agent/`null` defaults. Read its build and runtime prerequisites first.

## Install, test, validate

Use the environment's own project/venv, not the root venv. From its directory:

```bash
uv sync --extra dev
uv run pytest tests/ -q
uv run vf-validate <taskset-id> --runtime.type subprocess
```

`vf-validate` checks the **taskset**, not the env: it does not inherit the env's local
runtime and otherwise defaults to hosted Prime sandboxes. Always specify subprocess for
these local checks. Inspect `summary.json` and require `valid_rate == 1.0`; validation
can exit 0 even when checks fail. Document any package-specific validation prerequisites.

From the repo root, `prime env install dbt-debugger` (or `menu-taste`) installs locally.
`scripts/smoke_prime_lifecycle.sh` exercises install + validation and, when
`PRIME_API_KEY` is set, a minimal model eval. `scripts/smoke_prime_artifact.sh` builds and
validates installed wheels outside the checkout. Extend these or dedicated CI coverage
when adding packages; tests alone do not check packaged data/discovery.

## Evaluate with prime-rl

From the repo root:

```bash
scripts/prime_rl_eval.sh environments/dbt_debugger dbt-debugger \
  -m deepseek/deepseek-v4-flash -n 2 -r 1 -c 2 \
  --output-dir outputs/dbt-debugger --run.name smoke
```

The wrapper checks out pinned prime-rl and runs its `uv run eval` in a separate Python
3.12 venv. One cached checkout serves one run at a time; use separate `PRIME_RL_DIR`s for
concurrent runs. Use `--help` through the wrapper for the actual eval flags/config schema.

- `-n` limits tasks, `-r` sets rollouts per task, `-c` sets concurrency, and `-s` shuffles
  selection (it is **not** a save flag).
- Eval taskset settings use `--env.taskset.<name>`; validation uses `--taskset.<name>`.
  Spell CLI fields with dashes: `--env.taskset.difficulty-tier 2`,
  `--env.taskset.questions-path <path>`, or `--env.agent.max-turns 25`.
- Select named tasks with `--select.include.ids '["join_fanout_exec_revenue"]'`.
- Runs write configs, logs, metrics, and traces below `<output-dir>/<run.name>/`.
  Require all planned episodes to land without errors in
  `monitors/file/traces/stream.index.jsonl` (`ok: true`, `num_errors: 0`). A zero eval
  exit code alone is insufficient.
- Use canonical provider model IDs and the runner's client settings; do not assume the
  generated endpoint registry or old `[[eval]]` configs work with prime-rl.
- `--monitors.prime` uploads traces only when explicitly selected. For private menus,
  never set it, keep outputs in `environments/menu_taste/private/`, and confirm permission
  to send menu text to inference providers. Keep validation local too.

## Packaging and release

Use Hatchling and include all required source/data in wheels and sdists. Test installed
artifacts outside the checkout. Document system dependencies, resource lifecycle,
credentials, model-free validation, eval commands, and any privacy restrictions.
Validate credentials at the client/resource boundary without blocking model-free checks.
Do not add old `[tool.verifiers.eval]` defaults to configure the new runner.

Do not publish or upload private data implicitly. After validation, a Hub push requires
explicit approval of the destination and visibility; it is not required for local evals.
