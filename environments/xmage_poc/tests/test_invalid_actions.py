import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from xmage_poc.decklist import deck_context
from xmage_poc.environment import DECK_CONTEXT_MARKER, XMageEnvConfig


@pytest.mark.parametrize("history_decisions", [1, 2])
@pytest.mark.parametrize("opponent", ["self_play", "scripted"])
@pytest.mark.parametrize(
    ("fallback_kinds", "fallback_index"),
    [
        (["target", "mana"], 0),
        (["yes", "no"], 1),
        (["target", "cancel"], 1),
        (["cancel", "no"], 1),
        (["no", "cancel", "pass"], 2),
    ],
)
def test_invalid_replies_retry_same_decision_then_fall_back_without_mixing_seats(
    play, history_decisions, opponent, fallback_kinds, fallback_index
):
    observations = [
        {
            "decision": n,
            "player": seat,
            "player_id": seat,
            "query_type": "SELECT",
            "message": "Choose an action",
            "actions": [{"index": i, "kind": kind} for i, kind in enumerate(kinds)],
        }
        for n, seat, kinds in (
            (1, "player_a", ["cast", "mana"]),
            (
                2,
                "player_b" if opponent == "self_play" else "player_a",
                ["cast", "pass"],
            ),
            (3, "player_a", fallback_kinds),
            (4, "player_a", ["cast", "pass"]),
        )
    ]
    submitted = []

    class Session:
        def __init__(self, output, *args, **kwargs):
            self.output = output
            output.mkdir(parents=True)
            self.deck_contexts = {
                seat: deck_context([f"60 {land}"], seat)
                for seat, land in (("player_a", "Plains"), ("player_b", "Mountain"))
            }
            self.messages = iter(
                [{"type": "decision", "observation": obs} for obs in observations]
                + [
                    {
                        "type": "result",
                        "winner": "player_a",
                        "players": [
                            {"name": "player_a", "won": True},
                            {"name": "player_b", "won": False},
                        ],
                    }
                ]
            )

        def receive(self):
            return next(self.messages)

        def send(self, obs, action):
            if not 0 <= action < len(obs["actions"]):
                raise ValueError("Not offered")
            submitted.append((obs["decision"], action))

        def close(self):
            pass

    replies = iter(
        [
            (1, "bad-player_a"),
            (1, '{"action": 2}'),
            (1, '{"action": 1}'),
            (2, "bad-seat-2"),
            (2, '{"action": -1}'),
            (2, '{"action": 20}'),
            (3, '{"action": 20}'),
            (3, '{"action": -1}'),
            (3, '{"action": 7}'),
            (4, "bad-player_a"),
            (4, '{"action": 1}'),
        ]
    )
    seen = {}
    prompts = []

    def reply(prompt):
        number, content = next(replies)
        obs = observations[number - 1]
        seen.setdefault(obs["player"], {})[number] = obs
        users = [json.loads(m["content"]) for m in prompt if m["role"] == "user"]
        delivered = [m for m in users if "actions" in m]
        assert delivered == list(seen[obs["player"]].values())[-history_decisions:]
        assert all(m["decision"] in {o["decision"] for o in delivered} for m in users)
        context = json.loads(prompt[0]["content"].split(DECK_CONTEXT_MARKER)[1])
        assert context["player"] == obs["player"]
        if opponent == "self_play" and obs["player"] == "player_a":
            assert "bad-seat-2" not in str(prompt)
        if "error" in users[-1]:
            assert users[-1]["attempts_remaining"] in {1, 2}
            assert users[-1]["decision"] == number
        prompts.append(prompt)
        return content

    episode, requests = play(
        Session,
        reply,
        taskset={"pilot_seat": "player_a"},
        opponent=opponent,
        history_decisions=history_decisions,
        observation_format="json",
    )
    assert episode.ok, episode.errors
    assert next(replies, None) is None
    assert submitted == [(1, 1), (2, 1), (3, fallback_index), (4, 1)]
    # The endpoint received exactly the prompts that were recorded for audit.
    recording = Path(episode.traces[0].info["recording_path"])
    recorded = [
        json.loads(line)["messages"]
        for line in (recording / "model-prompts.jsonl").read_text().splitlines()
    ]
    assert requests == prompts == recorded
    traces = {trace.info["seat"]: trace for trace in episode.traces}
    expected = {
        # Seat-local counters; self-play splits the rejected replies across seats.
        "player_a": (8, 6, 2, 1) if opponent == "self_play" else (11, 9, 3, 2),
        "player_b": (3, 3, 1, 1),
    }
    assert set(traces) == (
        {"player_a", "player_b"} if opponent == "self_play" else {"player_a"}
    )
    for seat, trace in traces.items():
        attempts, invalid, unparseable, fallbacks = expected[seat]
        assert trace.reward == 1.0  # Metrics must not change either scoring mode.
        assert trace.metrics == pytest.approx(
            {
                "model_action_attempts": attempts,
                "invalid_action_count": invalid,
                "unparseable_reply_count": unparseable,
                "invalid_action_rate": invalid / attempts,
                "fallback_action_count": fallbacks,
            }
        )


@pytest.mark.parametrize("bound", [0, -1, True, 1.5])
def test_action_attempt_bound_must_be_a_positive_integer(bound):
    with pytest.raises(ValidationError, match="max_action_attempts"):
        XMageEnvConfig(max_action_attempts=bound)
