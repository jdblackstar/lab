"""Build pinned XMage, its full card module, and the headless adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "environments/xmage_poc"
REVISION = "afab346e06c4960882cf148acc57754c1c50a007"


def bridge_source_sha256() -> str:
    """Identify the bridge sources a runtime was built from, to catch stale releases."""
    digest = hashlib.sha256()
    bridge = ENV / "bridge"
    files = [bridge / "pom.xml", *sorted((bridge / "src").rglob("*"))]
    for path in files:
        if path.is_file():
            digest.update(path.relative_to(bridge).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def run(command: list[str], **kwargs) -> None:
    subprocess.run(command, check=True, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "external/xmage")
    parser.add_argument("--maven", default="mvn")
    parser.add_argument("--maven-repo", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "init", str(source)])
        run(
            [
                "git",
                "-C",
                str(source),
                "remote",
                "add",
                "origin",
                "https://github.com/magefree/mage.git",
            ]
        )
        run(["git", "-C", str(source), "fetch", "--depth=1", "origin", REVISION])
        run(["git", "-C", str(source), "checkout", "--detach", REVISION])
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise SystemExit(
            f"XMage checkout must be pinned to {REVISION}; found {revision}"
        )
    if subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    ).strip():
        raise SystemExit(
            "XMage checkout has tracked modifications; use unmodified upstream sources"
        )
    if not os.environ.get("JAVA_HOME") and not shutil.which("java"):
        raise SystemExit("Build requires JDK 21 and Maven 3.9+; set JAVA_HOME and PATH")
    maven = [args.maven, "-B", "-q", "-DskipTests"]
    build_env = dict(os.environ)
    build_env.setdefault("MAVEN_OPTS", "-Xmx4g")
    if args.maven_repo:
        maven.append(f"-Dmaven.repo.local={args.maven_repo.resolve()}")
    run(
        maven
        + [
            "-pl",
            "Mage.Sets,Mage.Common,Mage.Server.Plugins/Mage.Player.Human,Mage.Server.Plugins/Mage.Game.TwoPlayerDuel,Mage.Server.Plugins/Mage.Player.AI.MAD",
            "-am",
            "install",
        ],
        cwd=source,
        env=build_env,
    )
    # A clean bridge build prevents stale classes from entering the package.
    run(
        maven + ["-f", str(ENV / "bridge/pom.xml"), "clean", "package"],
        cwd=ROOT,
        env=build_env,
    )
    # Exercise our Java protocol checks, while leaving upstream tests skipped.
    run(
        [argument for argument in maven if argument != "-DskipTests"]
        + ["-f", str(ENV / "bridge/pom.xml"), "test"],
        cwd=ROOT,
        env=build_env,
    )
    runtime = ENV / "xmage_poc/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    # Keep active JVMs' open JAR files intact while publishing a rebuilt runtime.
    staged_jar = runtime / ".xmage-poc.jar.pending"
    shutil.copyfile(ENV / "bridge/target/xmage-poc-0.1.0.jar", staged_jar)
    staged_jar.replace(runtime / "xmage-poc.jar")
    shutil.copyfile(source / "LICENSE.txt", runtime / "XMAGE-LICENSE.txt")
    card_module = source / "Mage.Sets/target/mage-sets-1.4.62.jar"
    with zipfile.ZipFile(card_module) as archive:
        card_classes = sum(
            name.startswith("mage/cards/")
            and name.endswith(".class")
            and "$" not in name
            for name in archive.namelist()
        )
    java = (
        str(Path(os.environ["JAVA_HOME"]) / "bin/java")
        if os.environ.get("JAVA_HOME")
        else shutil.which("java")
    )
    # Validate that set discovery works from the shaded runnable JAR itself.
    catalog = json.loads(
        subprocess.check_output(
            [java, "-Xmx1g", "-jar", str(runtime / "xmage-poc.jar"), "cards"],
            text=True,
            timeout=120,
        )
    )
    (runtime / "build.json").write_text(
        json.dumps(
            {
                "xmage_revision": REVISION,
                "bridge_source_sha256": bridge_source_sha256(),
                "card_module": "org.mage:mage-sets:1.4.62",
                "card_module_sha256": hashlib.sha256(
                    card_module.read_bytes()
                ).hexdigest(),
                "card_module_classes": card_classes,
                "catalog_names": catalog["catalog_names"],
                "jar_sha256": hashlib.sha256(
                    (runtime / "xmage-poc.jar").read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Built {runtime / 'xmage-poc.jar'}")


if __name__ == "__main__":
    main()
