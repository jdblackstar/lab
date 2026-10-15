#!/usr/bin/env bash
# Run prime-rl's `uv run eval` against a local verifiers v1 environment package.
#
# Usage (from anywhere):
#   scripts/prime_rl_eval.sh <env-path> [eval args...]
#
# Example:
#   scripts/prime_rl_eval.sh environments/dbt_debugger dbt-debugger \
#     -m deepseek/deepseek-v4-flash -n 1 -r 1 -c 1
#
# prime-rl is not on PyPI and `eval` is a script of its project, so this checks out
# prime-rl at a pinned commit into a cache dir, initializes the submodules `eval` needs
# over HTTPS, syncs its Python 3.12 venv, installs <env-path> into that venv as an
# editable package, and runs `uv run eval` with the remaining arguments from the
# caller's working directory (so relative `--output-dir` paths resolve there).
#
# Environment:
#   PRIME_RL_REF   prime-rl commit (or ref) to check out; defaults to the pin below.
#   PRIME_RL_REPO  clone URL (default: https://github.com/PrimeIntellect-ai/prime-rl.git).
#   PRIME_RL_DIR   checkout dir (default: ${XDG_CACHE_HOME:-~/.cache}/prime-rl/<ref>).
#
# One checkout serves one run at a time: each run re-syncs its venv and reinstalls the
# env package, so concurrent runs must use different PRIME_RL_DIRs.

set -euo pipefail

PRIME_RL_REF="${PRIME_RL_REF:-d61df5690af1ccc2019c844403f8d2f2c5ed3273}"
PRIME_RL_REPO="${PRIME_RL_REPO:-https://github.com/PrimeIntellect-ai/prime-rl.git}"
PRIME_RL_DIR="${PRIME_RL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/prime-rl/$PRIME_RL_REF}"
# Only the submodules `eval` needs; prime-kernels is GPU training only.
SUBMODULES=(deps/verifiers deps/renderers deps/prime-envs deps/pydantic-config)

if [[ $# -lt 1 || ! -f "$1/pyproject.toml" ]]; then
  echo "usage: $0 <env-path> [eval args...]  (<env-path> must contain pyproject.toml)" >&2
  exit 2
fi
ENV_PATH="$(cd "$1" && pwd)"
shift

# Use prime-rl's own project venv, never an inherited one.
unset UV_PROJECT_ENVIRONMENT VIRTUAL_ENV

if [[ "$(git -C "$PRIME_RL_DIR" rev-parse HEAD 2>/dev/null || true)" != "$PRIME_RL_REF" ]]; then
  echo "==> check out prime-rl $PRIME_RL_REF into $PRIME_RL_DIR"
  mkdir -p "$PRIME_RL_DIR"
  if [[ ! -d "$PRIME_RL_DIR/.git" ]]; then
    git -C "$PRIME_RL_DIR" init -q
    git -C "$PRIME_RL_DIR" remote add origin "$PRIME_RL_REPO"
  fi
  git -C "$PRIME_RL_DIR" fetch -q --depth 1 origin "$PRIME_RL_REF"
  git -C "$PRIME_RL_DIR" checkout -q --force FETCH_HEAD
fi

echo "==> init prime-rl submodules over HTTPS"
# .gitmodules uses git@ URLs; the repos are public, so rewrite them to HTTPS. Clone in
# full: the submodules derive their versions from git tags (hatch-vcs), and a shallow
# clone would version them 0.0.x and let installing <env-path> replace them from PyPI.
git -C "$PRIME_RL_DIR" -c url."https://github.com/".insteadOf="git@github.com:" \
  submodule update --init -- "${SUBMODULES[@]}"

echo "==> sync prime-rl venv"
uv sync --project "$PRIME_RL_DIR" --locked --no-dev

echo "==> install $ENV_PATH into the prime-rl venv"
uv pip install --python "$PRIME_RL_DIR/.venv/bin/python" -e "$ENV_PATH"

echo "==> uv run eval $*"
# --no-sync: a project sync would uninstall the env package installed above.
exec uv run --project "$PRIME_RL_DIR" --no-sync eval "$@"
