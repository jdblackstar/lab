#!/usr/bin/env bash
# Exercise real setup with uv present but its tool bin missing from PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/orb_setup_smoke.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

mkdir -p "$TMP_ROOT/home" "$TMP_ROOT/bootstrap"
ln -s "$(command -v uv)" "$TMP_ROOT/bootstrap/uv"
clean_env=(env -i
  "HOME=$TMP_ROOT/home"
  "PATH=$TMP_ROOT/bootstrap:/usr/local/bin:/usr/bin:/bin"
  "UV_CACHE_DIR=$(uv cache dir)"
  "UV_PYTHON_INSTALL_DIR=$(uv python dir)"
  "UV_TOOL_DIR=$TMP_ROOT/tools"
  "UV_TOOL_BIN_DIR=$TMP_ROOT/tool bin"
)

for profile in .profile .bash_login .bash_profile; do
  echo "==> Test setup with $profile"
  rm -f "$TMP_ROOT/home/.profile" "$TMP_ROOT/home/.bash_login" "$TMP_ROOT/home/.bash_profile"
  printf 'export ORB_PROFILE_PRESERVED=yes\n' > "$TMP_ROOT/home/$profile"

  "${clean_env[@]}" /bin/bash -c '! command -v prime'
  for run in 1 2; do
    echo "==> Setup run $run"
    time "${clean_env[@]}" "$ROOT/.agents/setup"
    # This is a separate later session, not a profile sourced into setup.
    "${clean_env[@]}" /bin/bash -lc '
      set -euo pipefail
      [[ "$ORB_PROFILE_PRESERVED" == yes ]]
      [[ "$(command -v prime)" == "$UV_TOOL_BIN_DIR/prime" ]]
      prime --version
    '
  done
  [[ "$(grep -c '^# uv tool executables' "$TMP_ROOT/home/$profile")" == 1 ]]
done

echo "==> Orb setup smoke OK"
