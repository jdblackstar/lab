import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from xmage_poc.transport import ROOT, advance_action, run
from xmage_poc.verify import read_lines, verify


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
@pytest.mark.parametrize(
    "opponent,seat",
    [
        ("self_play", None),
        ("random", "player_b"),
        ("scripted_v1", "player_a"),
        ("xmage_mad", "player_a"),
        ("xmage_mad", "player_b"),
    ],
)
def test_real_game_private_views_and_engine_roundtrip(tmp_path, opponent, seat):
    java = os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
    assert java and (ROOT / "runtime/xmage-poc.jar").is_file(), (
        "Integration prerequisites missing"
    )
    existing = (
        os.environ.get("XMAGE_POC_RECORDING") if opponent == "self_play" else None
    )
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
        result = run(
            output,
            seed=7,
            java_bin=java,
            deck_a=deck_a,
            deck_b=deck_b,
            pilot_seat=seat,
            opponent=opponent if seat else "scripted_v1",
        )
        assert result["ended"] and result["errors"] == 0
        if opponent == "xmage_mad":
            assert result["opponent_decisions"] == 0
            other = "player_b" if seat == "player_a" else "player_a"
            assert (output / "players" / f"{other}.jsonl").read_text() == ""
    audit = verify(output)
    expected_seats = 1 if opponent == "xmage_mad" else 2
    assert audit["players"] == expected_seats and audit["decisions"] > 20
    if opponent == "random":
        assert any(
            d["selected"]["index"] != advance_action(d["observation"])
            for d in read_lines(output / "internal/decisions.jsonl")
            if d["observation"]["player"] != seat
        ), "Random opponent must not silently fall back to scripted_v1"
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
        # Native AI checkpoints include its simulation graph, not just two humans.
        timeout=300,
    )
    result = json.loads(restored.stdout)
    assert result["checkpoints_restored"] == audit["snapshots"]
    assert result["counterfactual_seats"] == expected_seats
    if not existing:
        first_state = read_lines(output / "internal/states.jsonl")[0]
        names = {
            card["name"]
            for player in first_state["players"]
            for card in player["library"]
        }
        assert {"Elite Vanguard", "Lightning Bolt"} <= names
