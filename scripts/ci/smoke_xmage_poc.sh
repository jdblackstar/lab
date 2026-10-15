#!/usr/bin/env bash
# Build and exercise the real engine, package contents, and local controller boundary.
set -euo pipefail
XMAGE_SMOKE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$XMAGE_SMOKE_ROOT"
export PATH="$XMAGE_SMOKE_ROOT/.venv/bin:$PATH"

python scripts/build_xmage_poc.py
prime env install xmage-poc --no-upgrade --plain
# Resolve the v1 plugin, then check Java and the bridge as an eval's startup does.
vf-validate xmage-poc --runtime.type subprocess -n 1 -o environments/xmage_poc/outputs/ci-validate
python -c "import asyncio; from xmage_poc.environment import XMageEnv, XMageEnvConfig; asyncio.run(XMageEnv(XMageEnvConfig(taskset={'id': 'xmage-poc'})).start())"
XMAGE_INTEGRATION=1 python -m pytest environments/xmage_poc/tests -q
python scripts/smoke_xmage_poc_eval.py --protocol-only --output "environments/xmage_poc/outputs/ci-protocol"
python scripts/smoke_xmage_poc_eval.py --protocol-only --observation-format json --inject-invalid-replies --output "environments/xmage_poc/outputs/ci-json-protocol"
python scripts/smoke_xmage_poc_eval.py --protocol-only --opponent scripted --pilot-seat player_b --recording-mode benchmark --inject-invalid-replies --output "environments/xmage_poc/outputs/ci-pilot-protocol"
for opponent in random xmage_mad; do
  python scripts/smoke_xmage_poc_eval.py --protocol-only --opponent "$opponent" --pilot-seat player_b --output "environments/xmage_poc/outputs/ci-$opponent-protocol"
done

uv build environments/xmage_poc --out-dir environments/xmage_poc/dist
# Check both distribution formats, then load the wheel outside the checkout.
python - <<'PY'
from pathlib import Path
import tarfile
import zipfile
dist = Path('environments/xmage_poc/dist')
with zipfile.ZipFile(next(dist.glob('*.whl'))) as archive:
    assert not any('/outputs/' in n or '/target/' in n for n in archive.namelist())
    assert archive.getinfo('xmage_poc/runtime/xmage-poc.jar').file_size > 1_000_000
    assert 'xmage_poc/decks/white.txt' in archive.namelist()
    from io import BytesIO
    import json
    with zipfile.ZipFile(BytesIO(archive.read('xmage_poc/runtime/xmage-poc.jar'))) as engine:
        assert 'mage/cards/l/LightningBolt.class' in engine.namelist()
        assert 'mage/cards/f/FireIce.class' in engine.namelist()
        assert 'mage/player/ai/ComputerPlayer7.class' in engine.namelist()
    assert json.loads(archive.read('xmage_poc/runtime/build.json'))['catalog_names'] > 30_000
with tarfile.open(next(dist.glob('*.tar.gz'))) as archive:
    assert any(n.endswith('/xmage_poc/runtime/xmage-poc.jar') for n in archive.getnames())
    assert not any('/outputs/' in n or '/target/' in n for n in archive.getnames())
PY
XMAGE_ARTIFACT_TMP="$(mktemp -d)"
trap 'rm -rf "$XMAGE_ARTIFACT_TMP"' EXIT
uv venv --python "$XMAGE_SMOKE_ROOT/.venv/bin/python" "$XMAGE_ARTIFACT_TMP/venv"
uv pip install --python "$XMAGE_ARTIFACT_TMP/venv/bin/python" environments/xmage_poc/dist/*.whl
(
  cd "$XMAGE_ARTIFACT_TMP"
  PYTHONPATH="" "$XMAGE_ARTIFACT_TMP/venv/bin/python" -c "import asyncio; from xmage_poc.environment import XMageEnv, XMageEnvConfig; asyncio.run(XMageEnv(XMageEnvConfig(taskset={'id': 'xmage-poc'})).start())"
  PYTHONPATH="" "$XMAGE_ARTIFACT_TMP/venv/bin/python" - <<'PY'
import json, os, shutil, subprocess
from xmage_poc.transport import ROOT
java = os.environ.get('XMAGE_JAVA_BIN') or shutil.which('java')
result = subprocess.check_output([java, '-Xmx1g', '-jar', str(ROOT / 'runtime/xmage-poc.jar'), 'cards', 'Lightning Bolt', 'Fire // Ice'], text=True)
assert json.loads(result)['catalog_names'] > 30_000
PY
)

# The eval path needs no credentials: prime-rl's `uv run eval` (via scripts/prime_rl_eval.sh,
# which needs uv, Python 3.12 and network) against a local scripted endpoint. The smoke
# reads prime-rl's file monitor, since `uv run eval` exits 0 even when episodes error.
python scripts/smoke_xmage_poc_eval.py --output "environments/xmage_poc/outputs/ci-prime-rl-eval"
