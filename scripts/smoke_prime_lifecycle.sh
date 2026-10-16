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

OUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dbt_debugger_lifecycle_smoke.XXXXXX")"
trap 'rm -rf "$OUT_DIR"' EXIT

echo "==> prime env install dbt-debugger"
prime env install dbt-debugger

echo "==> vf-validate dbt-debugger (local subprocess runtime)"
vf-validate dbt-debugger --runtime.type subprocess \
  --output-dir "$OUT_DIR" --run.dir validate
# vf-validate exits 0 even when checks fail; require every task to validate.
python - "$OUT_DIR/validate/summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1]))
if summary["valid_rate"] != 1.0:
    sys.exit(f"vf-validate: not every task is valid: {summary['checks']}")
PY

if [[ -n "${PRIME_API_KEY:-}" ]]; then
  echo "==> prime-rl eval (minimal)"
  bash "$ROOT/scripts/prime_rl_eval.sh" "$ROOT/environments/dbt_debugger" dbt-debugger \
    -m deepseek/deepseek-v4-flash \
    -n 1 -r 1 -c 1 \
    --output-dir "$OUT_DIR" --run.name eval \
    --monitors.prime
  # The eval exits 0 even when a rollout errors; require every planned episode to
  # land in the file monitor's trace index without errors.
  python - "$OUT_DIR/eval/monitors/file" <<'PY'
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
  echo "==> skip prime-rl eval (set PRIME_API_KEY to include eval smoke)"
fi

echo "==> OK"
