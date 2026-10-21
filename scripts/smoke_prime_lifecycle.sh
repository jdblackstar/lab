#!/usr/bin/env bash
# End-to-end smoke for the documented Prime + verifiers v1 path:
#   prime env install <env>  ->  vf-validate <env>  ->  prime-rl `uv run eval` <env> ...
#
# Usage (from repo root):
#   ./scripts/smoke_prime_lifecycle.sh
#
# Optional: set PRIME_API_KEY to also run a minimal prime-rl eval (one task, one rollout,
# uploaded to the Prime platform) through scripts/prime_rl_eval.sh, which needs Python
# 3.12. Without it, only install + model-free ``vf-validate`` (setup, gold, noop) run.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Prefer the repo virtualenv when present so ``vf-*`` match the interpreter
# ``prime env install`` targets (uv installs the environment into the active project venv).
if [[ -d "$ROOT/.venv/bin" ]]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi

OUT_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/env_lifecycle_smoke.XXXXXX")"
trap 'rm -rf "$OUT_ROOT"' EXIT

# smoke_env <env id> <env dir under environments/> [vf-validate args...]
# Set SMOKE_PRIME_MONITOR=0 to keep eval traces off the Prime platform.
smoke_env() {
  local env_id="$1" env_dir="$ROOT/environments/$2"
  shift 2
  local out_dir="$OUT_ROOT/$env_id"
  mkdir -p "$out_dir"

  echo "==> prime env install $env_id"
  prime env install "$env_id"

  echo "==> vf-validate $env_id (local subprocess runtime)"
  vf-validate "$env_id" "$@" --output-dir "$out_dir" --run.dir validate
  # vf-validate exits 0 even when checks fail; require every task to validate.
  python - "$out_dir/validate/summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1]))
if summary["valid_rate"] != 1.0:
    sys.exit(f"vf-validate: not every task is valid: {summary['checks']}")
PY

  if [[ -n "${PRIME_API_KEY:-}" ]]; then
    local monitor=(--monitors.prime)
    [[ "${SMOKE_PRIME_MONITOR:-1}" == 1 ]] || monitor=()
    echo "==> prime-rl eval $env_id (minimal)"
    bash "$ROOT/scripts/prime_rl_eval.sh" "$env_dir" "$env_id" \
      -m deepseek/deepseek-v4-flash \
      -n 1 -r 1 -c 1 \
      --output-dir "$out_dir" --run.name eval \
      "${monitor[@]}"
    # The eval exits 0 even when a rollout errors; require every planned episode to
    # land in the file monitor's trace index without errors.
    python - "$out_dir/eval/monitors/file" <<'PY'
import json
import sys
from pathlib import Path

monitor = Path(sys.argv[1])
plan = json.loads((monitor / "plan.json").read_text())
planned = sum(n for groups in plan.values() for n in groups.values())
index = monitor / "traces" / "stream.index.jsonl"
episodes = [json.loads(line) for line in index.read_text().splitlines() if line]
bad = [e for e in episodes if not e["ok"] or e["num_errors"]]
if len(episodes) != planned or bad:
    sys.exit(f"prime-rl eval: {len(episodes)}/{planned} episodes landed; errored: {bad}")
print(f"prime-rl eval: {len(episodes)}/{planned} episodes landed without errors")
PY
  else
    echo "==> skip prime-rl eval for $env_id (set PRIME_API_KEY to include eval smoke)"
  fi
}

smoke_env dbt-debugger dbt_debugger --runtime.type subprocess
# Traces hold whole menus: run the bundled synthetic sample even if these point at a
# private corpus, and don't upload anything.
(
  unset MENU_TASTE_QUESTIONS MENU_TASTE_MENUS
  SMOKE_PRIME_MONITOR=0 smoke_env menu-taste menu_taste --runtime.type subprocess
)

echo "==> OK"
