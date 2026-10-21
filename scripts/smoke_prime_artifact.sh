#!/usr/bin/env bash
# Build each packaged environment artifact, install it into a fresh isolated venv, and
# verify the installed package validates against its bundled data with the model-free
# ``vf-validate``. Bootstrap the same Prime-managed base stack first so dependency
# resolution matches normal usage.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/env_artifact_smoke.XXXXXX")"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  SMOKE_PYTHON_BIN="$ROOT/.venv/bin/python"
else
  SMOKE_PYTHON_BIN="${SMOKE_PYTHON_BIN:-python}"
fi

cleanup() {
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

# smoke_artifact <env dir under environments/> <wheel name> <env id> [vf-validate args...]
smoke_artifact() {
  local env_dir="$ROOT/environments/$1" module="$2" env_id="$3"
  shift 3
  local dist_dir="$env_dir/dist"
  local venv_dir="$TMP_ROOT/$module/venv"
  local work_dir="$TMP_ROOT/$module/workdir"
  mkdir -p "$work_dir"

  echo "==> [$env_id] clean previous build artifacts"
  rm -rf "$dist_dir"

  echo "==> [$env_id] build wheel + sdist"
  (
    cd "$env_dir"
    uv build
  )

  local wheel
  wheel="$(printf '%s\n' "$dist_dir"/"$module"-*.whl | head -n 1)"
  if [[ ! -f "$wheel" ]]; then
    echo "wheel not found under $dist_dir" >&2
    exit 1
  fi

  echo "==> [$env_id] create isolated venv"
  uv venv --python "$SMOKE_PYTHON_BIN" "$venv_dir"

  echo "==> [$env_id] install Prime CLI into isolated venv"
  uv pip install --python "$venv_dir/bin/python" prime

  echo "==> [$env_id] install built wheel into isolated venv"
  uv pip install --python "$venv_dir/bin/python" "$wheel"

  echo "==> [$env_id] vf-validate outside repo checkout"
  (
    cd "$work_dir"
    PYTHONPATH="" "$venv_dir/bin/vf-validate" "$env_id" "$@" \
      --output-dir "$work_dir/outputs" --run.dir validate
    # vf-validate exits 0 even when checks fail; require the tasks to validate.
    PYTHONPATH="" "$venv_dir/bin/python" - "$work_dir/outputs/validate/summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1]))
if summary["valid_rate"] != 1.0:
    sys.exit(f"vf-validate: not every task is valid: {summary['checks']}")
PY
  )
}

smoke_artifact dbt_debugger dbt_debugger dbt-debugger --runtime.type subprocess -n 1
# The bundled synthetic sample, even if these point at a private corpus.
(
  unset MENU_TASTE_QUESTIONS MENU_TASTE_MENUS
  smoke_artifact menu_taste menu_taste menu-taste --runtime.type subprocess -n 5
)

echo "==> OK"
