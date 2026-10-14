"""Audit the actual controller inputs against the paired omniscient records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .decklist import deck_context


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def audit_observation(obs: dict, state: dict) -> None:
    actor = obs["player_id"]
    players = {p["id"]: p for p in state["players"]}
    own = players[actor]
    view = obs["view"]
    require(
        {p["playerId"] for p in view["players"]} == set(players),
        "Public player roster differs",
    )
    require(
        set(view["myHand"]) == {c["id"] for c in own["hand"]},
        "Own hand does not match engine",
    )
    for public_player in view["players"]:
        internal = players[public_player["playerId"]]
        require(
            public_player["handCount"] == len(internal["hand"]),
            "Public hand count differs",
        )
        require(
            public_player["libraryCount"] == len(internal["library"]),
            "Public library count differs",
        )
        require(public_player["life"] == internal["life"], "Public life total differs")
        require(not public_player["sideboard"], "Unexpected deck/sideboard disclosure")
        require(
            public_player.get("topCard") is None,
            "These fixtures never reveal library tops",
        )
    forbidden = {c["id"] for p in players.values() for c in p["library"]}
    forbidden |= {
        c["id"] for p in players.values() if p["id"] != actor for c in p["hand"]
    }
    payload = json.dumps(obs)
    require(
        not any(card_id in payload for card_id in forbidden),
        "Hidden card identifiers leaked into controller input",
    )
    require(
        not {"library", "deck_a", "deck_b", "checkpoint", "sha256"} & set(strings(obs)),
        "Internal recording leaked",
    )
    require(
        not view["opponentHands"] and (not view["watchedHands"]),
        "Recording invariant failed",
    )


def verify(output: Path, *, require_finished: bool = True) -> dict:
    states = read_lines(output / "internal/states.jsonl")
    decisions = read_lines(output / "internal/decisions.jsonl")
    require(states and decisions, "No recorded gameplay")
    manifest = json.loads((output / "internal/manifest.json").read_text())
    mode = manifest.get("recording_mode", "full_audit")
    require(mode in {"full_audit", "benchmark"}, "Unknown recording mode")
    # Older recordings predate static deck contexts. Audit the added files when
    # present, while retaining support for those historical native transcripts.
    for seat, key in (("player_a", "deck_a"), ("player_b", "deck_b")):
        context_path = output / "players" / f"{seat}.context.json"
        if context_path.exists():
            require(
                json.loads(context_path.read_text())
                == deck_context(manifest[key], seat),
                "Deck context differs from its seat's registered deck",
            )
    by_sequence = {s["sequence"]: s for s in states}
    require(len(by_sequence) == len(states), "Duplicate state sequence")
    if "starting_player" in manifest:
        # Benchmark recordings omit event snapshots such as BEGIN_TURN; every
        # snapshot in turn 1 with an active player names the starting player.
        first_turn = next(
            (s for s in states if s["turn"] == 1 and s["active_player"]), None
        )
        require(first_turn is not None or not require_finished, "No turn began")
        if first_turn is not None:
            actual = next(
                p["name"]
                for p in first_turn["players"]
                if p["id"] == first_turn["active_player"]
            )
            require(actual == manifest["starting_player"], "Starting player differs")
    require(
        [s["sequence"] for s in states] == list(range(1, len(states) + 1)),
        "Recording invariant failed",
    )
    for state in states:
        if mode == "full_audit":
            checkpoint = output / "internal" / state["checkpoint"]
            require(
                hashlib.sha256(checkpoint.read_bytes()).hexdigest() == state["sha256"],
                "Checkpoint corrupt",
            )
        else:
            require(
                "checkpoint" not in state and "sha256" not in state,
                "Benchmark projections must not claim engine checkpoints",
            )
            require(
                state["reason"] in {"start", "decision", "end"},
                "Unexpected benchmark projection",
            )
        require(len(state["players"]) == 2, "Recording invariant failed")
        ids = [
            c["id"]
            for p in state["players"]
            for zone in ("hand", "library", "graveyard", "sideboard")
            for c in p[zone]
        ]
        ids += [c["id"] for c in state["battlefield"]]
        # Spell stack IDs differ from the underlying card IDs. Complete card
        # conservation is checked at decision boundaries with an empty stack.
        require(len(ids) == len(set(ids)), "A card occurs in multiple zones")
    observed_players = set()
    actual_by_player = {}
    require(
        [d["decision"] for d in decisions] == list(range(1, len(decisions) + 1)),
        "Decision sequence has gaps",
    )
    for decision in decisions:
        obs = decision["observation"]
        actor = decision["actor"]
        state = by_sequence[decision["state_sequence"]]
        players = {p["id"]: p for p in state["players"]}
        own = players[actor]
        require(obs["player_id"] == actor, "Recording invariant failed")
        require(
            state["reason"] == "decision" and state["event"]["actor"] == actor,
            "Decision checkpoint actor differs",
        )
        require(
            obs["decision"]
            == decision["decision"]
            == decision["response"]["decision"]
            == state["event"]["decision"],
            "Decision identifiers differ",
        )
        observed_players.add(actor)
        actual_by_player.setdefault(own["name"], []).append(obs)
        audit_observation(obs, state)
        index = decision["response"]["action"]
        require(
            type(index) is int and 0 <= index < len(obs["actions"]),
            "Invalid recorded action index",
        )
        require(
            decision["selected"] == obs["actions"][index], "Recording invariant failed"
        )
        if not state["stack"]:
            total = sum(
                len(p[z])
                for p in players.values()
                for z in ("hand", "library", "graveyard")
            ) + len(state["battlefield"])
            require(total == 120, f"Card conservation failed: {total}")
    # Native AI acts inside XMage, without the pipe's prompts or responses. Older
    # manifests imply two bridge seats; never drop the pilot's audit coverage.
    bridge_players = set(manifest.get("bridge_players", manifest["players"]))
    require(
        bridge_players
        and bridge_players <= set(manifest["players"])
        and observed_players == bridge_players,
        "Every controller seat must receive decisions",
    )
    for name, expected in actual_by_player.items():
        require(
            read_lines(output / "players" / f"{name}.jsonl") == expected,
            "Player transcript differs from delivered input",
        )
    result_path = output / "internal/result.json"
    if require_finished:
        result = json.loads(result_path.read_text())
        require(
            result["ended"]
            and (not result["errors"])
            and (result["technical_failure"] is None),
            "Recording invariant failed",
        )
        require(result["decisions"] == len(decisions), "Recording invariant failed")
        require(result["snapshots"] == len(states), "Recording invariant failed")
        require(states[-1]["reason"] == "end", "Recording invariant failed")
        require(any(s["turn"] > 1 for s in states), "No turns were played")
        events = (
            read_lines(output / "internal/events.jsonl")
            if mode == "benchmark"
            else [s["event"] for s in states]
        )
        require(
            any(e.get("type") == "LAND_PLAYED" for e in events),
            "No land play recorded",
        )
        require(
            any("DAMAGE" in e.get("type", "") for e in events),
            "No damage recorded",
        )
    return {
        "privacy_passed": True,
        "recording_mode": mode,
        "privacy_scope": "all delivered observations/actions vs paired decision projections; fixture-limited",
        "checkpoint_hashes_checked": len(states) if mode == "full_audit" else 0,
        # Python verifies projections/hashes; the separate Java verify command
        # performs restoration and hidden-state counterfactual checks.
        "checkpoint_restoration_checked": False,
        "decisions": len(decisions),
        "snapshots": len(states),
        "players": len(observed_players),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), indent=2))
