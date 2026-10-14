import asyncio
import json

import pytest
import verifiers as vf
from xmage_poc import load_environment
from xmage_poc.decklist import deck_context
from xmage_poc.environment import DECK_CONTEXT_MARKER


@pytest.mark.parametrize("opponent", ["self_play", "scripted"])
@pytest.mark.parametrize("auto_pass_priority", [True, False])
def test_priority_passes_bypass_model_but_keep_real_choices_and_history(
    tmp_path, monkeypatch, stub_bridge_runtime, opponent, auto_pass_priority
):
    def prompt(number, player, message, actions, query_type="SELECT", stack=None):
        return {
            "type": "decision",
            "observation": {
                "decision": number,
                "player": player,
                "player_id": player,
                "query_type": query_type,
                "message": message,
                "view": {"stack": stack or {}},
                "actions": [
                    {"index": i, "kind": kind, "label": kind}
                    for i, kind in enumerate(actions)
                ],
            },
        }

    messages = [prompt(1, "player_a", "Play spells and abilities", ["pass"])]
    if opponent == "self_play":
        messages.append(
            prompt(2, "player_b", "Play instants and activated abilities", ["pass"])
        )
    messages.extend(
        [
            # Stack is nonempty: an available response must still reach the model.
            prompt(
                3,
                "player_a",
                "Play instants and activated abilities",
                ["cast", "pass"],
                stack={"spell": {"name": "Shock"}},
            ),
            # One-option mana and combat prompts are not priority passes.
            prompt(4, "player_a", "Pay {W}", ["mana"], query_type="PLAY_MANA"),
            prompt(5, "player_a", "Select attackers", ["pass"]),
            prompt(
                6,
                "player_a",
                "Play instants and activated abilities",
                ["pass"],
                stack={"spell": {"name": "Shock"}},
            ),
            {"type": "result", "winner": "player_a", "ended": True},
        ]
    )

    class Session:
        output = tmp_path

        def __init__(self):
            self.deck_contexts = {
                "player_a": deck_context(
                    ["40 Plains", "20 Youthful Knight"], "player_a"
                ),
                "player_b": deck_context(
                    ["40 Mountain", "20 Goblin Piker"], "player_b"
                ),
            }
            self.pending = iter(messages)
            self.responses = []

        def receive(self):
            message = next(self.pending, None)
            assert message is not None, "Read past the game result"
            return message

        def send(self, observation, action):
            self.responses.append((observation["decision"], action))

    monkeypatch.setattr(
        "xmage_poc.environment.verify", lambda _: {"privacy_passed": True}
    )
    env = load_environment(
        opponent=opponent,
        auto_pass_priority=auto_pass_priority,
        java_bin="/bin/false",
        history_decisions=1,
    )
    session = Session()
    state = {
        "_session": session,
        "_seat_histories": {},
        "_processed_turns": 0,
        "_prompted_decision": None,
        "trajectory": [],
        "auto_passed_priority": 0,
        "model_action_attempts": 0,
    }

    async def exercise():
        state["_pending"] = await env.receive_for_model(state)
        model_decisions = []
        for _ in range(len(messages) + 1):
            history = await env.get_prompt_messages(state)
            if state.get("game_result"):
                break
            observation = json.loads(history[-1].content)
            context = json.loads(history[0].content.split(DECK_CONTEXT_MARKER, 1)[1])
            assert context == session.deck_contexts[observation["player"]]
            assert len([m for m in history if m.role == "user"]) == 1
            # The other seat and bypassed prompts must never enter model history.
            observed = [json.loads(m.content) for m in history if m.role == "user"]
            assert all(o["player"] == observation["player"] for o in observed)
            if auto_pass_priority:
                assert all(o["decision"] in {3, 4, 5} for o in observed)
            model_decisions.append(observation["decision"])
            state["trajectory"].append(
                {"completion": [vf.AssistantMessage(content='{"action": 0}')]}
            )
        else:
            pytest.fail("Game result did not stop model prompting")
        return model_decisions

    model_decisions = asyncio.run(exercise())
    original_decisions = [m["observation"]["decision"] for m in messages[:-1]]
    assert model_decisions == ([3, 4, 5] if auto_pass_priority else original_decisions)
    assert session.responses == [(n, 0) for n in original_decisions]
    skipped = (
        [n for n in original_decisions if n not in {3, 4, 5}]
        if auto_pass_priority
        else []
    )
    assert state["auto_passed_priority"] == len(skipped)
    log = tmp_path / "automatic-priority.jsonl"
    assert (
        [json.loads(line)["decision"] for line in log.read_text().splitlines()]
        if log.exists()
        else []
    ) == skipped
    assert state["recording_audit"]["privacy_passed"]


def test_environment_enables_automatic_priority_by_default(stub_bridge_runtime):
    assert load_environment(java_bin="/bin/false").auto_pass_priority
