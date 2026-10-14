from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path

import verifiers as vf
from datasets import Dataset

from .transport import ROOT, GameSession, PilotSession, is_pass_only_priority
from .verify import verify

SYSTEM = (
    "You pilot one seat in a Magic: The Gathering fixture game. "
    "Each user message contains your current player observation and an indexed action list. "
    'Return ONLY a JSON object of the form {"action": 0}, selecting an offered index. '
    "You see your own hand and public information. Your recent history contains only your seat's decisions. "
    "Your registered decklist is provided below; use it to plan your strategy and mulligans. "
    "Counts describe the starting deck, not its current library contents or draw order. "
    "You can select individual attackers and blockers, remove combat selections, or finish a selection. "
    "The engine may ask separately for targets, modes, and mana payment. "
    "Priority prompts with only a pass option are advanced automatically between your decisions. "
    "Choose actions to win the game."
)

DECK_CONTEXT_MARKER = "\nRegistered deck (your seat only):\n"


def completion_action(messages) -> int:
    text = messages[-1].content
    if isinstance(text, list):
        text = "".join(
            part.text if hasattr(part, "text") else part.get("text", "")
            for part in text
        )
    try:
        result = json.loads(text)
        if set(result) != {"action"} or type(result["action"]) is not int:
            raise ValueError("Expected a single integer action")
        return result["action"]
    except (TypeError, ValueError, KeyError) as exc:
        raise vf.InvalidModelResponseError(
            'Respond with exactly {"action": <offered index>}'
        ) from exc


def recording_validity(state) -> float:
    """POC score measures a completed, verified recording, not pilot strength."""
    return float(state.get("recording_audit", {}).get("privacy_passed", False))


def pilot_win(state) -> float:
    """A win counts only after a complete game passes the recording audit."""
    if not recording_validity(state):
        return 0.0
    outcome = next(
        (
            p
            for p in state.get("game_result", {}).get("players", [])
            if p["name"] == state.get("pilot_seat")
        ),
        None,
    )
    return float(bool(outcome and outcome["won"]))


class XMageEnvironment(vf.MultiTurnEnv):
    def __init__(
        self,
        *,
        output_dir: Path,
        java_bin: str,
        history_decisions: int,
        deck_a: Path | None,
        deck_b: Path | None,
        opponent: str,
        auto_pass_priority: bool,
        recording_mode: str,
        **kwargs,
    ):
        self.output_dir = output_dir
        self.java_bin = java_bin
        self.history_decisions = history_decisions
        self.deck_a = deck_a
        self.deck_b = deck_b
        self.opponent = opponent
        self.auto_pass_priority = auto_pass_priority
        self.recording_mode = recording_mode
        super().__init__(**kwargs)

    async def setup_state(self, state):
        path = self.output_dir / uuid.uuid4().hex
        state["pilot_seat"] = state["info"]["pilot_seat"]
        state["auto_passed_priority"] = 0
        try:
            session_class = PilotSession if self.opponent == "scripted" else GameSession
            extra = (
                {"pilot_seat": state["pilot_seat"]}
                if self.opponent == "scripted"
                else {}
            )
            session = await asyncio.to_thread(
                session_class,
                path,
                state["info"]["seed"],
                self.java_bin,
                self.deck_a,
                self.deck_b,
                recording_mode=self.recording_mode,
                **extra,
            )
            state["_session"] = session
            state["recording_path"] = str(path)
            await asyncio.to_thread(
                (path / "model-controller.json").write_text,
                json.dumps(
                    {
                        "opponent": self.opponent,
                        "pilot_seat": state["pilot_seat"],
                        "auto_pass_priority": self.auto_pass_priority,
                    },
                    indent=2,
                )
                + "\n",
            )
            state["_pending"] = await self.receive_for_model(state)
        except (OSError, RuntimeError, TimeoutError) as exc:
            raise vf.InfraError(str(exc)) from exc
        state["_seat_histories"] = {}
        state["_processed_turns"] = 0
        state["_prompted_decision"] = None
        return state

    async def receive_for_model(self, state):
        """Drain forced priority passes before spending a model turn."""
        session = state["_session"]

        def receive():
            while True:
                message = session.receive()
                if (
                    message["type"] == "result"
                    or not self.auto_pass_priority
                    or not is_pass_only_priority(message["observation"])
                ):
                    return message
                obs = message["observation"]
                # The Java bridge records this prompt and response as usual.
                action = obs["actions"][0]["index"]
                session.send(obs, action)
                state["auto_passed_priority"] += 1
                with (session.output / "automatic-priority.jsonl").open("a") as log:
                    log.write(
                        json.dumps(
                            {
                                "decision": obs["decision"],
                                "player": obs["player"],
                                "action": action,
                            }
                        )
                        + "\n"
                    )

        return await asyncio.to_thread(receive)

    async def env_response(self, messages, state, **kwargs):
        # MultiTurnEnv's normal concatenation would leak the other seat's hand.
        # get_prompt_messages owns this environment's seat-specific histories.
        return await self.get_prompt_messages(state)

    async def get_prompt_messages(self, state):
        session = state["_session"]
        if len(state["trajectory"]) > state["_processed_turns"]:
            obs = state["_pending"]["observation"]
            completion = state["trajectory"][-1]["completion"]
            action = completion_action(completion)
            try:
                session.send(obs, action)
            except ValueError as exc:
                raise vf.InvalidModelResponseError(str(exc)) from exc
            state["_seat_histories"][obs["player_id"]].extend(completion)
            try:
                state["_pending"] = await self.receive_for_model(state)
            except (OSError, RuntimeError, TimeoutError) as exc:
                raise vf.InfraError(str(exc)) from exc
            state["_processed_turns"] = len(state["trajectory"])
        pending = state["_pending"]
        if pending["type"] == "result":
            state["game_result"] = pending
            try:
                state["recording_audit"] = await asyncio.to_thread(
                    verify, session.output
                )
            except (AssertionError, OSError, ValueError) as exc:
                raise vf.InfraError(f"Recording failed audit: {exc}") from exc
            # Only the public outcome is rendered into the final completion.
            state["final_env_response"] = [
                vf.UserMessage(
                    content=json.dumps({"ended": True, "winner": pending["winner"]})
                )
            ]
            return state["final_env_response"]
        obs = pending["observation"]
        if obs["player_id"] not in state["_seat_histories"]:
            context = session.deck_contexts[obs["player"]]
            state["_seat_histories"][obs["player_id"]] = [
                vf.SystemMessage(
                    content=SYSTEM + DECK_CONTEXT_MARKER + json.dumps(context)
                )
            ]
        history = state["_seat_histories"][obs["player_id"]]
        if state["_prompted_decision"] != obs["decision"]:
            history.append(vf.UserMessage(content=json.dumps(obs)))
            state["_prompted_decision"] = obs["decision"]
        # Return a new list: Verifiers trajectories must not mutate as a seat plays.
        return [history[0], *history[1:][-(2 * self.history_decisions - 1) :]]

    @vf.cleanup
    async def close_game(self, state):
        session = state.pop("_session", None)
        if session is not None:
            await asyncio.to_thread(session.close)
        state.pop("_seat_histories", None)
        state.pop("_pending", None)


def load_environment(
    num_games: int = 1,
    seed: int = 7,
    output_dir: str | None = None,
    java_bin: str | None = None,
    max_turns: int = 4000,
    history_decisions: int = 4,
    deck_a: str | None = None,
    deck_b: str | None = None,
    opponent: str = "self_play",
    pilot_seat: str = "alternate",
    auto_pass_priority: bool = True,
    recording_mode: str = "full_audit",
) -> vf.Environment:
    """Use scripted for pilot wins; benchmark keeps privacy projections, not checkpoints."""
    if num_games < 1 or max_turns < 1 or history_decisions < 1:
        raise ValueError("num_games, max_turns and history_decisions must be positive")
    if recording_mode not in {"full_audit", "benchmark"}:
        raise ValueError("recording_mode must be full_audit or benchmark")
    if opponent not in {"self_play", "scripted"}:
        raise ValueError("opponent must be self_play or scripted")
    if type(auto_pass_priority) is not bool:
        raise ValueError("auto_pass_priority must be a boolean")
    if pilot_seat not in {"alternate", "player_a", "player_b"}:
        raise ValueError("pilot_seat must be alternate, player_a, or player_b")
    java = java_bin or os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
    if not java or not (ROOT / "runtime/xmage-poc.jar").is_file():
        raise RuntimeError(
            "Build scripts/build_xmage_poc.py first and provide Java 21 (XMAGE_JAVA_BIN or PATH)"
        )
    for path in (deck_a, deck_b):
        if path is not None and not Path(path).is_file():
            raise ValueError(f"Decklist does not exist: {path}")
    dataset = Dataset.from_list(
        [
            {
                "question": "Play the next offered action in your seat's MTG game.",
                "info": {
                    "seed": seed + i,
                    "pilot_seat": ("player_a" if i % 2 == 0 else "player_b")
                    if pilot_seat == "alternate"
                    else pilot_seat,
                },
            }
            for i in range(num_games)
        ]
    )
    return XMageEnvironment(
        dataset=dataset,
        output_dir=Path(output_dir or "environments/xmage_poc/outputs/games").resolve(),
        java_bin=java,
        history_decisions=history_decisions,
        deck_a=Path(deck_a).resolve() if deck_a else None,
        deck_b=Path(deck_b).resolve() if deck_b else None,
        opponent=opponent,
        auto_pass_priority=auto_pass_priority,
        recording_mode=recording_mode,
        max_turns=max_turns,
        rubric=(
            vf.Rubric(funcs=[pilot_win, recording_validity], weights=[1.0, 0.0])
            if opponent == "scripted"
            else vf.Rubric(funcs=[recording_validity])
        ),
    )
