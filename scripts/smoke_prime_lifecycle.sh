#!/usr/bin/env bash
# End-to-end smoke for the documented Prime + Verifiers path:
#   prime env install <env>  →  prime eval run <env> ...
#
# Usage (from repo root):
#   ./scripts/smoke_prime_lifecycle.sh
#
# Optional: set PRIME_API_KEY to also run a minimal ``prime eval run`` (one example,
# one rollout). Without it, only install + ``load_environment()`` are exercised.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Prefer the repo virtualenv when present so ``python`` matches ``prime env install`` (uv
# installs the environment into the active project venv).
if [[ -d "$ROOT/.venv/bin" ]]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi

echo "==> prime env install dbt-debugger"
prime env install dbt-debugger

echo "==> import + load_environment(max_scenarios=1)"
python -c "import dbt_debugger; dbt_debugger.load_environment(max_scenarios=1)"

if [[ -n "${PRIME_API_KEY:-}" ]]; then
  echo "==> prime eval run (minimal)"
  prime eval run dbt-debugger \
    -e configs/endpoints.toml \
    -m openai/gpt-4.1-nano \
    -n 1 -r 1 \
    -a '{"max_scenarios":1}' \
    -A
else
  echo "==> skip prime eval run (set PRIME_API_KEY to include eval smoke)"
fi

echo "==> OK"
