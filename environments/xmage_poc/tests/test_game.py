import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from xmage_poc.transport import ROOT, GameSession, run
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


@pytest.mark.skipif(
    os.environ.get("XMAGE_INTEGRATION") != "1",
    reason="Set XMAGE_INTEGRATION=1 after building the Java bridge",
)
def test_benchmark_audits_every_decision_and_replays_seeded_game(tmp_path):
    original = tmp_path / "original"
    result = run(original, seed=7, recording_mode="benchmark")
    audit = verify(original)
    assert audit["recording_mode"] == "benchmark" and audit["privacy_passed"]
    assert audit["snapshots"] == audit["decisions"] + 2
    assert audit["checkpoint_hashes_checked"] == 0
    assert not audit["checkpoint_restoration_checked"]
    assert not (original / "internal/checkpoints").exists()
    decisions = read_lines(original / "internal/decisions.jsonl")

    replay = GameSession(tmp_path / "replay", seed=7, recording_mode="benchmark")
    try:
        for expected in decisions:
            message = replay.receive()
            assert message["type"] == "decision"
            replay.send(message["observation"], expected["response"]["action"])
        repeated = replay.receive()
        assert repeated["type"] == "result" and repeated["winner"] == result["winner"]
    finally:
        replay.close()
    assert verify(replay.output)["privacy_passed"]

    def gameplay(output):
        states = read_lines(output / "internal/states.jsonl")
        # Compare actual card identities by deck-registration position, not just
        # names: identical copies must also follow the same shuffle and actions.
        ids = {states[0]["game_id"]: "game"}
        for player in states[0]["players"]:
            ids[player["id"]] = player["name"]
            ids.update(
                (c["id"], f"{player['name']}:{i}")
                for i, c in enumerate(player["library"])
            )
        value = {
            "states": states,
            "decisions": read_lines(output / "internal/decisions.jsonl"),
        }
        # Spell/ability IDs remain random upstream; do not claim raw trace identity.
        encoded = re.sub(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
            lambda m: ids.get(m[0], "generated-id"),
            json.dumps(value),
        )
        # GameLog appends the first three UUID digits to HTML card log names.
        encoded = re.sub(r"(</font>) \[[0-9a-f]{3}\]", r"\1 [short-id]", encoded)
        return json.loads(encoded)

    assert gameplay(original) == gameplay(replay.output)

    # Omitting checkpoints must not weaken the existing delivered-input audit.
    hidden = read_lines(original / "internal/states.jsonl")[1]["players"][0]["library"][
        0
    ]["id"]
    decisions[0]["observation"]["message"] = f"Leaked card {hidden}"
    (original / "internal/decisions.jsonl").write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n"
    )
    with pytest.raises(AssertionError, match="Hidden card identifiers"):
        verify(original)
