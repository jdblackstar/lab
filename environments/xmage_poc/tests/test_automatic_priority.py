import json
from pathlib import Path

import pytest
from xmage_poc.decklist import deck_context
from xmage_poc.environment import DECK_CONTEXT_MARKER, XMageEnvConfig


@pytest.mark.parametrize("opponent", ["self_play", "scripted"])
@pytest.mark.parametrize("auto_pass_priority", [True, False])
@pytest.mark.parametrize("auto_forced", [True, False])
def test_automatic_answers_bypass_model_but_keep_real_choices_and_history(
    play, opponent, auto_pass_priority, auto_forced
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
            # One-option mana and combat prompts are forced, not priority passes.
            prompt(4, "player_a", "Pay {W}", ["mana"], query_type="PLAY_MANA"),
            prompt(5, "player_a", "Select attackers", ["pass"]),
            # Two options: a real choice whatever the settings.
            prompt(6, "player_a", "Pay {1}", ["mana", "mana"], query_type="PLAY_MANA"),
            prompt(
                7,
                "player_a",
                "Play instants and activated abilities",
                ["pass"],
                stack={"spell": {"name": "Shock"}},
            ),
            {"type": "result", "winner": "player_a", "ended": True},
        ]
    )

    responses = []

    class Session:
        def __init__(self, output, *args, **kwargs):
            self.output = output
            output.mkdir(parents=True)
            self.deck_contexts = {
                "player_a": deck_context(
                    ["40 Plains", "20 Youthful Knight"], "player_a"
                ),
                "player_b": deck_context(
                    ["40 Mountain", "20 Goblin Piker"], "player_b"
                ),
            }
            self.pending = iter(messages)

        def receive(self):
            message = next(self.pending, None)
            assert message is not None, "Read past the game result"
            return message

        def send(self, observation, action):
            responses.append((observation["decision"], action))

        def close(self):
            pass

    model_decisions = []

    def reply(history):
        observation = json.loads(history[-1]["content"])
        context = json.loads(history[0]["content"].split(DECK_CONTEXT_MARKER, 1)[1])
        assert context == deck_context(
            ["40 Plains", "20 Youthful Knight"]
            if observation["player"] == "player_a"
            else ["40 Mountain", "20 Goblin Piker"],
            observation["player"],
        )
        assert len([m for m in history if m["role"] == "user"]) == 1
        # The other seat and bypassed prompts must never enter model history.
        observed = [json.loads(m["content"]) for m in history if m["role"] == "user"]
        assert all(o["player"] == observation["player"] for o in observed)
        assert all(o["decision"] in expected for o in observed)
        model_decisions.append(observation["decision"])
        return '{"action": 0}'

    priority = {1, 2, 7} if auto_pass_priority else set()
    forced = {4, 5} if auto_forced else set()
    original_decisions = [m["observation"]["decision"] for m in messages[:-1]]
    expected = [n for n in original_decisions if n not in priority | forced]

    episode, _ = play(
        Session,
        reply,
        taskset={"pilot_seat": "player_a", "pilot_play_order": "play"},
        opponent=opponent,
        auto_pass_priority=auto_pass_priority,
        auto_forced=auto_forced,
        history_decisions=1,
        observation_format="json",
    )
    assert episode.ok, episode.errors
    assert model_decisions == expected
    assert responses == [(n, 0) for n in original_decisions]
    for trace in episode.traces:
        assert trace.info["auto_passed_priority"] == len(
            priority & set(original_decisions)
        )
        assert trace.info["auto_forced_decisions"] == len(forced)
        assert trace.info["recording_audit"]["privacy_passed"]
    recording = Path(episode.traces[0].info["recording_path"])
    for reason, numbers in (("priority", priority), ("forced", forced)):
        log = recording / f"automatic-{reason}.jsonl"
        assert (
            [json.loads(line)["decision"] for line in log.read_text().splitlines()]
            if log.exists()
            else []
        ) == [n for n in original_decisions if n in numbers]


def test_environment_automates_one_option_prompts_by_default():
    assert XMageEnvConfig().auto_pass_priority
    assert XMageEnvConfig().auto_forced
