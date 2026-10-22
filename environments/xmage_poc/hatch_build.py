"""Fetch the pinned, CI-built XMage runtime into the package while it is installed.

`xmage_poc/runtime/release.json` names a GitHub Release and the SHA-256 of each asset.
Every wheel or editable build (including `prime env install`) downloads any asset that
is missing or stale, verifies it, and only then moves it into place, so installing needs
neither Maven nor the XMage source build. Set XMAGE_POC_SKIP_DOWNLOAD=1 to keep the
runtime that is already there, such as one built by scripts/build_xmage_poc.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class RuntimeDownloadHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if os.environ.get("XMAGE_POC_SKIP_DOWNLOAD") == "1":
            return
        runtime = Path(self.root) / "xmage_poc/runtime"
        release = json.loads((runtime / "release.json").read_text())
        for name, expected in release["sha256"].items():
            target = runtime / name
            if target.is_file() and sha256(target) == expected:
                continue
            url = f"{release['url']}/{name}"
            print(f"xmage-poc: downloading {url}")
            # Stage the download so a failed or tampered fetch never replaces the runtime,
            # and a running JVM keeps its open JAR when a new one lands.
            pending = runtime / f".{name}.pending"
            try:
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    pending.open("wb") as file,
                ):
                    while block := response.read(1 << 20):
                        file.write(block)
                actual = sha256(pending)
                if actual != expected:
                    raise RuntimeError(
                        f"{url} has SHA-256 {actual}, but release.json pins {expected}"
                    )
                pending.replace(target)
            finally:
                pending.unlink(missing_ok=True)
