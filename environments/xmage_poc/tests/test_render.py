import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from xmage_poc import load_environment
from xmage_poc.render import glossary_text, public_card_rules, render_observation
from xmage_poc.verify import audit_model_prompts

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"
C = "12345678-1000-0000-0000-000000000001"
D = "12345678-2000-0000-0000-000000000002"
E = "eeeeeeee-0000-0000-0000-000000000003"
F = "ffffffff-0000-0000-0000-000000000004"
G = "99999999-0000-0000-0000-000000000005"
H = "88888888-0000-0000-0000-000000000006"


def observation():
    def card(oid, power, rules):
        return {
            "id": oid,
            "name": "Twin",
            "power": power,
            "toughness": "3",
            "cardTypes": ["CREATURE"],
            "rules": rules,
            "tapped": oid == C,
            "damage": 2 if oid == C else 0,
            "nameController": "player_a",
        }

    one = card(C, "4", ["<i>Flying</i>"])
    two = card(D, "1", ["Vigilance"])
    one.update(
        counters=[{"name": "+1/+1", "count": 2}],
        attachments=[D],
        summoningSickness=True,
    )
    two.update(attachedTo=C)
    players = [
        {
            "playerId": oid,
            "name": name,
            "life": life,
            "handCount": hand,
            "libraryCount": library,
            "manaPool": {"red": 2} if oid == B else {"white": 1},
            "battlefield": {C: one, D: two} if oid == A else {},
            "graveyard": {G: {"id": G, "name": "Dead card"}} if oid == B else {},
            "exile": {F: {"id": F, "name": "Exiled"}} if oid == A else {},
        }
        for oid, name, life, hand, library in [
            (A, "player_a", 12, 3, 47),
            (B, "player_b", 8, 5, 42),
        ]
    ]
    return {
        "decision": 9,
        "player": "player_a",
        "player_id": A,
        "query_type": "SELECT",
        "message": "Select attackers",
        "view": {
            "turn": 6,
            "phase": "COMBAT",
            "step": "DECLARE_ATTACKERS",
            "activePlayerName": "player_b",
            "priorityPlayerName": "player_a",
            "players": players,
            "myHand": {E: {"id": E, "name": "Own secret", "rules": ["Lifelink"]}},
            "exiles": [{F: {"id": F, "name": "Exiled"}}],
            "stack": {
                H: {
                    "id": H,
                    "name": "Bolt",
                    "targets": [D, B],
                    "rules": ["Deal 3 damage."],
                }
            },
            "combat": [
                {
                    "attackers": {C: one},
                    "blockers": {D: two},
                    "defenderId": B,
                    "isBlocked": True,
                }
            ],
        },
        "actions": [
            {
                "index": i,
                "kind": "attack",
                "label": "Attack with Twin",
                "response_type": "uuid",
                "value": oid,
            }
            for i, oid in enumerate([C, D])
        ],
    }


def test_render_preserves_asymmetric_game_state_and_distinct_same_name_objects():
    obs = observation()
    original = copy.deepcopy(obs)
    rendered = render_observation(obs, pilot_play_order="draw", starting_player=B)
    for expected in (
        "COMBAT / DECLARE_ATTACKERS",
        "Active: player_b | Priority: player_a",
        "Starting player: player_b",
        "Play/draw: draw",
        "player_a: life=12 hand=3 library=47 mana=[W:1 U:0 B:0 R:0 G:0 C:0]",
        "player_b: life=8 hand=5 library=42 mana=[W:0 U:0 B:0 R:2 G:0 C:0]",
        "Twin #12345678-1; CREATURE; 4/3; tapped; damage=2; summoningSickness",
        "Twin #12345678-2; CREATURE; 1/3; untapped; damage=0",
        "counters=+1/+1:2",
        "attachments=Twin #12345678-2",
        "attachedTo=Twin #12345678-1",
        "targets=Twin #12345678-2, player_b",
        "attackers=Twin #12345678-1 -> player_b blockers=Twin #12345678-2 blocked=True",
        "0: attack | Attack with Twin [Twin #12345678-1]",
        "1: attack | Attack with Twin [Twin #12345678-2]",
        "Own secret #eeeeeeee",
        "Exiled #ffffffff",
        "Exile group 1: Exiled #ffffffff",
        "Dead card #99999999",
    ):
        assert expected in rendered
    assert "Flying" not in rendered
    glossary = glossary_text(public_card_rules(obs))
    assert "Twin: Flying" in glossary and "Twin: Vigilance" in glossary
    assert "Deal 3 damage." in glossary
    assert obs == original
    assert rendered == render_observation(
        copy.deepcopy(obs), pilot_play_order="draw", starting_player=B
    )
    assert "Play/draw: unknown" in render_observation(obs)
    assert "Play/draw: play" in render_observation(obs, starting_player=A)


def test_system_glossary_survives_history_trimming_and_actual_prompt_audit(tmp_path):
    env = load_environment(
        java_bin="/bin/false", history_decisions=1, auto_pass_priority=False
    )
    contexts = {
        name: {"player": name, "deck_size": 60, "decklist": []}
        for name in ("player_a", "player_b")
    }
    (tmp_path / "players").mkdir()
    for name, context in contexts.items():
        (tmp_path / "players" / f"{name}.context.json").write_text(json.dumps(context))
    state = {
        "_session": SimpleNamespace(output=tmp_path, deck_contexts=contexts),
        "_seat_histories": {},
        "_card_glossaries": {},
        "trajectory": [],
        "_processed_turns": 0,
        "_prompted_decision": None,
        "pilot_seat": "player_a",
        "pilot_play_order": "play",
        "starting_player": A,
    }
    first = observation()
    other = copy.deepcopy(first)
    other.update(decision=10, player="player_b", player_id=B)
    other["view"]["myHand"] = {
        E: {"id": E, "name": "Other seat secret", "rules": ["Deathtouch"]}
    }
    last = copy.deepcopy(first)
    last["decision"] = 11
    last["view"]["myHand"] = {}
    decisions = []

    async def exercise():
        for obs in (first, other, last):
            state["_pending"] = {"type": "decision", "observation": obs}
            prompt = await env.get_prompt_messages(state)
            assert len(prompt) == 2
            assert "Starting player: player_a" in prompt[-1].content
            assert ("Play/draw: draw" if obs is other else "Play/draw: play") in prompt[
                -1
            ].content
            if obs is last:
                assert "Own secret: Lifelink" in prompt[0].content
                assert "Other seat secret" not in prompt[0].content
                assert "Own secret" not in prompt[-1].content
            decisions.append(
                {
                    "decision": obs["decision"],
                    "observation": obs,
                    "response": {"action": 0},
                }
            )

    asyncio.run(exercise())
    controller = {
        "opponent": "self_play",
        "auto_pass_priority": False,
        "history_decisions": 1,
        "observation_format": "text",
    }
    assert audit_model_prompts(tmp_path, decisions, controller) == 3
    path = tmp_path / "model-prompts.jsonl"
    saved = path.read_text()
    rows = [json.loads(line) for line in saved.splitlines()]
    for index in (0, 1):  # A glossary leak and a user-message leak both fail.
        changed = copy.deepcopy(rows)
        changed[-1]["messages"][index]["content"] += " opponent-hidden-card"
        path.write_text("\n".join(json.dumps(row) for row in changed))
        with pytest.raises(AssertionError, match="Rendered (system|model) prompt differs"):
            audit_model_prompts(tmp_path, decisions, controller)
    path.write_text("\n".join(json.dumps(row) for row in rows[:-1]))
    with pytest.raises(AssertionError, match="coverage"):
        audit_model_prompts(tmp_path, decisions, controller)


def test_format_contract():
    assert load_environment(java_bin="/bin/false").observation_format == "text"
    assert (
        load_environment(
            java_bin="/bin/false", observation_format="json"
        ).observation_format
        == "json"
    )
    with pytest.raises(ValueError, match="observation_format"):
        load_environment(observation_format="yaml")
