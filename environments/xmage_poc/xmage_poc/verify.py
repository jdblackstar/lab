"""Audit the actual controller inputs against the paired omniscient records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .decklist import deck_context
from .render import (
    TEXT_INSTRUCTIONS,
    glossary_text,
    public_card_rules,
    render_observation,
)


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


def audit_model_prompts(output: Path, decisions: list[dict], controller: dict) -> int:
    """Reconstruct full inference inputs from audited seat observations.

    Public play/draw metadata is the only extra input; restrict it to the player
    roster and play/draw enum. No free-form state strings may enter the prompt.
    """
    from .environment import DECK_CONTEXT_MARKER, SYSTEM
    from .transport import is_pass_only_priority

    expected = [
        d
        for d in decisions
        if (
            controller["opponent"] != "scripted"
            or d["observation"]["player"] == controller["pilot_seat"]
        )
        and not (
            controller["auto_pass_priority"] and is_pass_only_priority(d["observation"])
        )
    ]
    prompts = read_lines(output / "model-prompts.jsonl")
    require(
        [p["decision"] for p in prompts] == [d["decision"] for d in expected],
        "Model prompt coverage differs from model decisions",
    )
    histories = {}
    glossaries = {}
    for prompt, decision in zip(prompts, expected, strict=True):
        obs = decision["observation"]
        order, starter = prompt["pilot_play_order"], prompt["starting_player"]
        roster = {p["playerId"]: p["name"] for p in obs["view"]["players"]}
        require(order in {None, "play", "draw"}, "Invalid public play/draw factor")
        require(
            starter is None or starter in {*roster, *roster.values()},
            "Invalid public starting player",
        )
        if starter is not None and order is not None:
            own = starter in {obs["player"], obs["player_id"]}
            require(
                order == ("play" if own else "draw"), "Inconsistent play/draw factors"
            )
        history = histories.setdefault(obs["player_id"], [])
        system = SYSTEM
        if controller["observation_format"] == "text":
            glossary = glossaries.setdefault(obs["player_id"], {})
            glossary.update(public_card_rules(obs))
            system += TEXT_INSTRUCTIONS + glossary_text(glossary)
            rendered = render_observation(
                obs, pilot_play_order=order, starting_player=starter
            )
        else:
            require(
                controller["observation_format"] == "json", "Unknown observation format"
            )
            rendered = json.dumps(obs)
        context = json.loads(
            (output / "players" / f"{obs['player']}.context.json").read_text()
        )
        system += DECK_CONTEXT_MARKER + json.dumps(context)
        history.append({"role": "user", "content": rendered})
        actual = prompt["messages"]
        normalized = []
        for message in actual:
            if message["role"] == "assistant":
                answer = json.loads(message["content"])
                require(
                    set(answer) == {"action"} and type(answer["action"]) is int,
                    "Invalid model history answer",
                )
                normalized.append({"role": "assistant", "content": json.dumps(answer)})
            else:
                normalized.append(message)
        require(
            normalized
            == [
                {"role": "system", "content": system},
                *history[-(2 * controller["history_decisions"] - 1) :],
            ],
            "Rendered model prompt differs from audited observation/history",
        )
        history.append(
            {
                "role": "assistant",
                "content": json.dumps({"action": decision["response"]["action"]}),
            }
        )
    return len(prompts)


def verify(output: Path, *, require_finished: bool = True) -> dict:
    states = read_lines(output / "internal/states.jsonl")
    decisions = read_lines(output / "internal/decisions.jsonl")
    require(states and decisions, "No recorded gameplay")
    manifest = json.loads((output / "internal/manifest.json").read_text())
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
    require(
        [s["sequence"] for s in states] == list(range(1, len(states) + 1)),
        "Recording invariant failed",
    )
    for state in states:
        checkpoint = output / "internal" / state["checkpoint"]
        require(
            hashlib.sha256(checkpoint.read_bytes()).hexdigest() == state["sha256"],
            "Checkpoint corrupt",
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
    require(len(observed_players) == 2, "Both controllers must receive decisions")
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
        require(
            any(s["event"].get("type") == "LAND_PLAYED" for s in states),
            "No land play recorded",
        )
        require(
            any("DAMAGE" in s["event"].get("type", "") for s in states),
            "No damage recorded",
        )
    audit = {
        "privacy_passed": True,
        "decisions": len(decisions),
        "snapshots": len(states),
        "players": len(observed_players),
    }
    controller_path = output / "model-controller.json"
    if controller_path.exists():
        controller = json.loads(controller_path.read_text())
        # Preserve historical raw recordings that predate renderer logging.
        if "observation_format" in controller:
            audit["model_prompts"] = audit_model_prompts(output, decisions, controller)
            audit["model_prompt_privacy_passed"] = True
    return audit


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), indent=2))
