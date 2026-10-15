#!/usr/bin/env bash
# End-to-end smoke for the documented Prime + verifiers v1 path:
#   prime env install <env>  ->  vf-validate <env>  ->  vf-eval <env> ...
#
# Usage (from repo root):
#   ./scripts/smoke_prime_lifecycle.sh
#
# Optional: set PRIME_API_KEY to also run a minimal ``vf-eval`` (one task, one rollout).
# Without it, only install + model-free ``vf-validate`` (setup, gold, noop checks) run.

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
  echo "==> vf-eval (minimal)"
  vf-eval dbt-debugger \
    -m deepseek/deepseek-v4-flash \
    -n 1 -r 1 \
    --output-dir "$OUT_DIR" --run.dir eval
  # vf-eval exits 0 even when a rollout errors; require a clean trace.
  python - "$OUT_DIR/eval/traces.jsonl" <<'PY'
import json
import sys

traces = [t for line in open(sys.argv[1]) for t in json.loads(line)["traces"]]
errors = [e for t in traces for e in t["errors"]]
if not traces or errors:
    sys.exit(f"vf-eval: rollout errors: {errors or 'no traces'}")
PY
else
  echo "==> skip vf-eval (set PRIME_API_KEY to include eval smoke)"
fi

echo "==> OK"
