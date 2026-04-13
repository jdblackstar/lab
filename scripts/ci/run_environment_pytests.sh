#!/usr/bin/env bash
# Run pytest in every lab environment that defines pyproject.toml and a tests/ tree.
# Add new environments under environments/<name>/ with tests/; no workflow edit required.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

shopt -s nullglob
any=0
for env_dir in environments/*/; do
  [[ -f "${env_dir}pyproject.toml" ]] || continue
  [[ -d "${env_dir}tests" ]] || continue
  any=1
  name="$(basename "$env_dir")"
  echo "==> pytest environments/${name}"
  (cd "$env_dir" && uv -q sync --extra dev && uv run pytest tests/ -q)
done
shopt -u nullglob

if [[ "$any" -eq 0 ]]; then
  echo "No environments with pyproject.toml + tests/ found; nothing to run."
fi
