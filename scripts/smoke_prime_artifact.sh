#!/usr/bin/env bash
# Build the packaged environment artifact, install it into a fresh isolated venv, and
# verify the installed package validates against its bundled scenario data with the
# model-free ``vf-validate``. Bootstrap the same Prime-managed base stack first so
# dependency resolution matches normal usage.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/environments/dbt_debugger"
DIST_DIR="$ENV_DIR/dist"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dbt_debugger_artifact_smoke.XXXXXX")"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  SMOKE_PYTHON_BIN="$ROOT/.venv/bin/python"
else
  SMOKE_PYTHON_BIN="${SMOKE_PYTHON_BIN:-python}"
fi

cleanup() {
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

echo "==> clean previous build artifacts"
rm -rf "$DIST_DIR"

echo "==> build wheel + sdist"
(
  cd "$ENV_DIR"
  uv build
)

WHEEL="$(printf '%s\n' "$DIST_DIR"/dbt_debugger-*.whl | head -n 1)"
if [[ ! -f "$WHEEL" ]]; then
  echo "wheel not found under $DIST_DIR" >&2
  exit 1
fi

VENV_DIR="$TMP_ROOT/venv"
WORK_DIR="$TMP_ROOT/workdir"
mkdir -p "$WORK_DIR"

echo "==> create isolated venv"
uv venv --python "$SMOKE_PYTHON_BIN" "$VENV_DIR"

echo "==> install Prime CLI into isolated venv"
uv pip install --python "$VENV_DIR/bin/python" prime

echo "==> install built wheel into isolated venv"
uv pip install --python "$VENV_DIR/bin/python" "$WHEEL"

echo "==> vf-validate on one task outside repo checkout"
(
  cd "$WORK_DIR"
  PYTHONPATH="" "$VENV_DIR/bin/vf-validate" dbt-debugger --runtime.type subprocess \
    -n 1 --output-dir "$WORK_DIR/outputs" --run.dir validate
  # vf-validate exits 0 even when checks fail; require the task to validate.
  PYTHONPATH="" "$VENV_DIR/bin/python" - "$WORK_DIR/outputs/validate/summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1]))
if summary["valid_rate"] != 1.0:
    sys.exit(f"vf-validate: task is not valid: {summary['checks']}")
PY
)

echo "==> OK"
