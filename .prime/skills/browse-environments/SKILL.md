---
name: browse-environments
description: Discovers and inspects Prime Hub environments for this verifiers 0.4 workspace. Use to find candidates, compare task and reward contracts, inspect source or metadata, and choose a compatible starting point.
---

# Browse environments

## Discover and inspect

Use the installed Prime CLI's help when flags differ. Start with metadata/source reads:

```bash
prime env list --search "math" --owner primeintellect --plain
prime env info owner/name --plain
prime env status owner/name --plain
prime env inspect owner/name --plain
```

Pull source only when deeper inspection is needed (`prime env pull --help` gives the
current destination flags). Review dependencies and code before installing third-party
packages or running their setup.

## Compare compatibility, not just version labels

For each candidate record task type/horizon, prompts/tools, rewards/metrics, data/license,
system dependencies, secrets, runtime/harness, and any CI/recency evidence available.
Distinguish the **environment package version** from its **verifiers API requirement**:
a package named/versioned `0.1.x` may still use a different API. Inspect imports, exports,
and config contracts for `verifiers.v1` compatibility with this repo's verifiers 0.4 stack.
Do not use an old minimum package-version threshold as an API compatibility test.

If a candidate is v0-only, report the migration work; don't recommend it as directly
usable here. Prefer good existing options, but do not hide compatibility or privacy costs.

## Validate a shortlist

After source review, install into an appropriate isolated project/venv with
`prime env install owner/name`. For model-free checks use `vf-validate` with an explicitly
chosen runtime; local packages here use `--runtime.type subprocess`. Confirm prerequisites
and `valid_rate`, not just process exit status.

Follow `evaluate-environments` for model checks. Hub metadata/installation does not prove
the package works with the pinned prime-rl runner: verify v1 discovery and run a small
eval before recommending it for larger jobs. The wrapper needs a local package path, not
just a Hub slug. Do not assume `configs/endpoints.toml` aliases resolve in that runner.

Return a ranked shortlist, compatibility evidence, exact tested install/eval commands,
and blockers (credentials, data access, runtime, API migration, or missing coverage).
