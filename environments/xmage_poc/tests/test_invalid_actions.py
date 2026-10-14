import asyncio
import json

import pytest
import verifiers as vf
from xmage_poc import load_environment
from xmage_poc.decklist import deck_context
from xmage_poc.environment import DECK_CONTEXT_MARKER


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
    tmp_path, monkeypatch, history_decisions, opponent, fallback_kinds, fallback_index
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
                        "players": [{"name": "player_a", "won": True}],
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

    monkeypatch.setattr("xmage_poc.environment.GameSession", Session)
    monkeypatch.setattr("xmage_poc.environment.PilotSession", Session)
    monkeypatch.setattr(
        "xmage_poc.environment.verify", lambda _: {"privacy_passed": True}
    )
    env = load_environment(
        java_bin="/bin/false",
        output_dir=str(tmp_path),
        opponent=opponent,
        pilot_seat="player_a",
        history_decisions=history_decisions,
        observation_format="json",
    )

    async def exercise():
        state = await env.init_state(env.dataset[0], vf.ClientConfig(), "unused")
        await env.setup_state(state)
        seen = {}
        saved_prompts = []
        replies = [
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
        for number, reply in replies:
            prompt = await env.get_prompt_messages(state)
            # Repeated prompt assembly must not resend actions or count twice.
            assert await env.env_response([], state) == prompt
            obs = observations[number - 1]
            seen.setdefault(obs["player"], {})[number] = obs
            users = [json.loads(m.content) for m in prompt if m.role == "user"]
            delivered = [m for m in users if "actions" in m]
            assert delivered == list(seen[obs["player"]].values())[-history_decisions:]
            assert all(
                m["decision"] in {o["decision"] for o in delivered} for m in users
            )
            context = json.loads(prompt[0].content.split(DECK_CONTEXT_MARKER)[1])
            assert context["player"] == obs["player"]
            if opponent == "self_play" and obs["player"] == "player_a":
                assert "bad-seat-2" not in str(prompt)
            if "error" in users[-1]:
                assert users[-1]["attempts_remaining"] in {1, 2}
                assert users[-1]["decision"] == number
            saved_prompts.append((prompt, [(m.role, m.content) for m in prompt]))
            state["trajectory"].append(
                {"completion": [vf.AssistantMessage(content=reply)]}
            )
        await env.get_prompt_messages(state)
        assert state["final_env_response"]
        assert state["invalid_action_count"] == 9
        assert state["unparseable_reply_count"] == 3
        assert state["model_action_attempts"] == 11
        assert state["fallback_action_count"] == 2
        assert submitted == [(1, 1), (2, 1), (3, fallback_index), (4, 1)]
        assert all(
            [(m.role, m.content) for m in prompt] == saved
            for prompt, saved in saved_prompts
        )
        await env.rubric.score_rollout(state)
        assert state["reward"] == 1.0  # Metrics must not change either scoring mode.
        assert state["metrics"]["invalid_action_rate"] == pytest.approx(9 / 11)
        assert state["metrics"]["invalid_action_count"] == 9
        assert state["metrics"]["unparseable_reply_count"] == 3
        assert state["metrics"]["fallback_action_count"] == 2
        await env.close_game(state)

    asyncio.run(exercise())


@pytest.mark.parametrize("bound", [0, -1, True, 1.5])
def test_action_attempt_bound_must_be_a_positive_integer(bound):
    with pytest.raises(ValueError, match="max_action_attempts"):
        load_environment(max_action_attempts=bound)
