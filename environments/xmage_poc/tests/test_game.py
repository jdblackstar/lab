import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from xmage_poc.transport import ROOT, run
from xmage_poc.verify import verify


@pytest.mark.skipif(
    os.environ.get("XMAGE_INTEGRATION") != "1",
    reason="Set XMAGE_INTEGRATION=1 after building the Java bridge",
)
def test_full_card_module_and_native_name_lookup():
    java = os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
    assert java
    names = [
        "Lightning Bolt",
        "Ajani, Strength of the Pride",
        "Fire // Ice",
        "Elite Vanguard",
        "Plains",
    ]
    command = [java, "-Xmx1g", "-jar", str(ROOT / "runtime/xmage-poc.jar"), "cards"]
    result = subprocess.run(
        command + names, check=True, capture_output=True, text=True, timeout=120
    )
    catalog = json.loads(result.stdout)
    assert catalog["catalog_names"] > 30_000
    assert [card["name"] for card in catalog["cards"]] == names
    assert [card["class"] for card in catalog["cards"]][:3] == [
        "mage.cards.l.LightningBolt",
        "mage.cards.a.AjaniStrengthOfThePride",
        "mage.cards.f.FireIce",
    ]
    assert all(card["set"] != "POC" for card in catalog["cards"])
    unknown = subprocess.run(
        command + ["Not a real XMage card"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert (
        unknown.returncode != 0
        and "Unknown card in pinned XMage catalog" in unknown.stderr
    )


@pytest.mark.skipif(
    os.environ.get("XMAGE_INTEGRATION") != "1",
    reason="Set XMAGE_INTEGRATION=1 after building the Java bridge",
)
def test_real_game_private_views_and_engine_roundtrip(tmp_path):
    java = os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
    assert java and (ROOT / "runtime/xmage-poc.jar").is_file(), (
        "Integration prerequisites missing"
    )
    existing = os.environ.get("XMAGE_POC_RECORDING")
    output = Path(existing) if existing else tmp_path / "game"
    if not existing:
        # Exercise cards outside the former ten-card build, including a targeted
        # spell that follows the existing target/mana query protocol.
        deck_a = tmp_path / "white.txt"
        deck_b = tmp_path / "red.txt"
        deck_a.write_text(
            (ROOT / "decks/white.txt")
            .read_text()
            .replace("Savannah Lions", "Elite Vanguard")
        )
        deck_b.write_text(
            (ROOT / "decks/red.txt").read_text().replace("Shock", "Lightning Bolt")
        )
        result = run(output, seed=7, java_bin=java, deck_a=deck_a, deck_b=deck_b)
        assert result["ended"] and result["errors"] == 0
    audit = verify(output)
    assert audit["players"] == 2 and audit["decisions"] > 20
    restored = subprocess.run(
        [
            java,
            "-Xmx512m",
            "-jar",
            str(ROOT / "runtime/xmage-poc.jar"),
            "verify",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    result = json.loads(restored.stdout)
    assert result["checkpoints_restored"] == audit["snapshots"]
    assert result["counterfactual_seats"] == 2
    if not existing:
        from xmage_poc.verify import read_lines

        first_state = read_lines(output / "internal/states.jsonl")[0]
        names = {
            card["name"]
            for player in first_state["players"]
            for card in player["library"]
        }
        assert {"Elite Vanguard", "Lightning Bolt"} <= names
