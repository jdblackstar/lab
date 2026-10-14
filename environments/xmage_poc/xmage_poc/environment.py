from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from itertools import product
from pathlib import Path

import verifiers as vf
from datasets import Dataset

from .render import (
    TEXT_INSTRUCTIONS,
    glossary_text,
    public_card_rules,
    render_observation,
)
from .transport import ROOT, GameSession, PilotSession, is_pass_only_priority
from .verify import verify

SYSTEM = (
    "You pilot one seat in a Magic: The Gathering fixture game. "
    "Each user message contains your current player observation and an indexed action list. "
    "You may reason before committing to an action. End your reply with exactly one "
    '<answer>{"action": 0}</answer> block, selecting an offered integer index. '
    "Put any visible reasoning before the answer block and nothing after it. "
    "The answer must contain only that JSON object, optionally in a JSON code fence. "
    "If you omit reasoning, a bare JSON object or a single JSON code fence is also valid. "
    "You see your own hand and public information. Your recent history contains only your seat's decisions. "
    "Your registered decklist is provided below; use it to plan your strategy and mulligans. "
    "Counts describe the starting deck, not its current library contents or draw order. "
    "You can select individual attackers and blockers, remove combat selections, or finish a selection. "
    "The engine may ask separately for targets, modes, and mana payment. "
    "Priority prompts with only a pass option are advanced automatically between your decisions. "
    "Choose actions to win the game."
)

DECK_CONTEXT_MARKER = "\nRegistered deck (your seat only):\n"
ANSWER_PARSER = vf.XMLParser(fields=["answer"])


def completion_action(messages) -> int:
    text = messages[-1].content
    if isinstance(text, list):
        text = "".join(
            part.text if hasattr(part, "text") else part.get("text", "")
            for part in text
        )
    try:
        text = (text or "").strip()
        if "<answer>" in text or "</answer>" in text:
            # XMLParser extracts an answer but does not reject multiple answers.
            if (
                text.count("<answer>") != 1
                or text.count("</answer>") != 1
                or not text.endswith("</answer>")
            ):
                raise ValueError("Expected one final answer block")
            text = ANSWER_PARSER.parse_answer(text)
        if not text:
            raise ValueError("Expected an answer")
        if text.startswith("```"):
            lines = text.splitlines()
            if (
                len(lines) < 3
                or lines[0] not in {"```", "```json"}
                or lines[-1] != "```"
            ):
                raise ValueError("Expected one complete JSON code fence")
            text = "\n".join(lines[1:-1])
        # Preserve object pairs so duplicate action keys cannot silently win.
        result = json.loads(text, object_pairs_hook=tuple)
        if (
            type(result) is not tuple
            or len(result) != 1
            or result[0][0] != "action"
            or type(result[0][1]) is not int
        ):
            raise ValueError("Expected a single integer action")
        return result[0][1]
    except (TypeError, ValueError, KeyError) as exc:
        raise vf.InvalidModelResponseError(
            'End with one <answer>{"action": <offered index>}</answer> block'
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


def invalid_action_count(state) -> float:
    """All rejected model replies, including unparseable replies."""
    return float(state.get("invalid_action_count", 0))


def unparseable_reply_count(state) -> float:
    return float(state.get("unparseable_reply_count", 0))


def invalid_action_rate(state) -> float:
    """Rejected replies / model attempts, including corrective attempts."""
    attempts = state.get("model_action_attempts", 0)
    return invalid_action_count(state) / attempts if attempts else 0.0


def fallback_action_count(state) -> float:
    return float(state.get("fallback_action_count", 0))


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
        observation_format: str,
        recording_mode: str,
        max_action_attempts: int,
        **kwargs,
    ):
        self.output_dir = output_dir
        self.java_bin = java_bin
        self.history_decisions = history_decisions
        self.deck_a = deck_a
        self.deck_b = deck_b
        self.opponent = opponent
        self.auto_pass_priority = auto_pass_priority
        self.observation_format = observation_format
        self.recording_mode = recording_mode
        self.max_action_attempts = max_action_attempts
        super().__init__(**kwargs)

    def decks_for(self, info):
        """Matchup deck identities stay fixed even when their seats change."""
        decks = {
            "deck_a": self.deck_a or ROOT / "decks/white.txt",
            "deck_b": self.deck_b or ROOT / "decks/red.txt",
        }
        pair = (decks[info["pilot_deck"]], decks[info["opponent_deck"]])
        return pair if info["pilot_seat"] == "player_a" else pair[::-1]

    async def setup_state(self, state):
        path = self.output_dir / uuid.uuid4().hex
        state.update(state["info"])
        state["auto_passed_priority"] = 0
        state["model_action_attempts"] = 0
        state["invalid_action_count"] = 0
        state["unparseable_reply_count"] = 0
        state["fallback_action_count"] = 0
        state["_invalid_attempts"] = 0
        try:
            session_class = (
                GameSession if self.opponent == "self_play" else PilotSession
            )
            extra = (
                {"pilot_seat": state["pilot_seat"], "opponent": self.opponent}
                if self.opponent != "self_play"
                else {}
            )
            session = await asyncio.to_thread(
                session_class,
                path,
                state["info"]["seed"],
                self.java_bin,
                *self.decks_for(state["info"]),
                starting_player=state["starting_player"],
                recording_mode=self.recording_mode,
                **extra,
            )
            state["_session"] = session
            state["recording_path"] = str(path)
            await asyncio.to_thread(
                (path / "model-controller.json").write_text,
                json.dumps(
                    {
                        **state["info"],
                        "opponent": self.opponent,
                        "auto_pass_priority": self.auto_pass_priority,
                        "observation_format": self.observation_format,
                        "history_decisions": self.history_decisions,
                        "max_action_attempts": self.max_action_attempts,
                        "invalid_action_fallback": "pass_no_cancel_else_first",
                    },
                    indent=2,
                )
                + "\n",
            )
            state["_pending"] = await self.receive_for_model(state)
        except (OSError, RuntimeError, TimeoutError) as exc:
            raise vf.InfraError(str(exc)) from exc
        state["_seat_histories"] = {}
        state["_card_glossaries"] = {}
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
            history = state["_seat_histories"][obs["player_id"]]
            history[-1].extend(completion)
            state["model_action_attempts"] += 1
            state["_processed_turns"] = len(state["trajectory"])
            error = None
            exhausted = False
            try:
                action = completion_action(completion)
            except vf.InvalidModelResponseError:
                state["unparseable_reply_count"] += 1
                error = "Your reply could not be parsed. Follow the response format in the system message."
            else:
                try:
                    session.send(obs, action)
                except ValueError:
                    error = "The selected action is not offered for this decision."
            if error is not None:
                state["invalid_action_count"] += 1
                state["_invalid_attempts"] += 1
                exhausted = state["_invalid_attempts"] >= self.max_action_attempts
                correction = {
                    "error": error,
                    "decision": obs["decision"],
                    "attempts_remaining": self.max_action_attempts
                    - state["_invalid_attempts"],
                    "instruction": "Choose an offered index from the unchanged observation above.",
                }
                if exhausted:
                    # Avoid a fresh shuffle or strategic help from advance_action.
                    # Some decisions (targets, mana, etc.) have no pass option.
                    action = next(
                        (
                            a["index"]
                            for kind in ("pass", "no", "cancel")
                            for a in obs["actions"]
                            if a["kind"] == kind
                        ),
                        obs["actions"][0]["index"],
                    )
                    correction["fallback_action"] = action
                    correction["instruction"] = (
                        "Attempt limit reached; the fallback action was submitted."
                    )
                    session.send(obs, action)
                    state["fallback_action_count"] += 1
                history[-1].append(vf.UserMessage(content=json.dumps(correction)))
            if error is None or exhausted:
                state["_invalid_attempts"] = 0
                try:
                    state["_pending"] = await self.receive_for_model(state)
                except (OSError, RuntimeError, TimeoutError) as exc:
                    raise vf.InfraError(str(exc)) from exc
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
            # Presentation only: neither the action protocol nor seat history changes.
            # Play/draw is public and fixed by the bridge for both seats.
            starter = state["starting_player"]
            factors = {
                "pilot_play_order": (
                    "play" if starter in {obs["player"], obs["player_id"]} else "draw"
                ),
                "starting_player": starter,
            }
            if self.observation_format == "text":
                glossary = state["_card_glossaries"].setdefault(obs["player_id"], {})
                glossary.update(public_card_rules(obs))
                context = session.deck_contexts[obs["player"]]
                history[0] = vf.SystemMessage(
                    content=SYSTEM
                    + TEXT_INSTRUCTIONS
                    + glossary_text(glossary)
                    + DECK_CONTEXT_MARKER
                    + json.dumps(context)
                )
                rendered = render_observation(obs, **factors)
            else:
                rendered = json.dumps(obs)
            history.append([vf.UserMessage(content=rendered)])
            state["_prompted_decision"] = obs["decision"]
            state["_prompt_factors"] = factors
        # Trim whole decisions, not messages: corrections must never evict the
        # current observation, even with history_decisions=1. Blocks stay private
        # to their seat, including rejected replies and fallback notifications.
        prompt = [
            history[0],
            *(
                message
                for block in history[1:][-self.history_decisions :]
                for message in block
            ),
        ]
        # Audit exactly the messages returned for inference, including retries,
        # the persistent glossary and trimmed history, not just the raw view.
        key = [obs["decision"], len(history[-1])]
        if state.get("_recorded_prompt") != key:
            state["_recorded_prompt"] = key
            record = {
                "decision": obs["decision"],
                "player": obs["player"],
                **state["_prompt_factors"],
                "messages": [{"role": m.role, "content": m.content} for m in prompt],
            }

            def record_prompt():
                with (session.output / "model-prompts.jsonl").open("a") as log:
                    log.write(json.dumps(record) + "\n")

            await asyncio.to_thread(record_prompt)
        # Return a new list: Verifiers trajectories must not mutate as a seat plays.
        return prompt

    @vf.cleanup
    async def close_game(self, state):
        session = state.pop("_session", None)
        if session is not None:
            await asyncio.to_thread(session.close)
        state.pop("_seat_histories", None)
        state.pop("_card_glossaries", None)
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
    observation_format: str = "text",
    pilot_deck: str = "balanced",
    pilot_play_order: str = "balanced",
    recording_mode: str = "full_audit",
    max_action_attempts: int = 3,
) -> vf.Environment:
    """Cross seat × matchup deck × play/draw within each seed block.

    num_games is the total row count, not the seed count. With all factors varying,
    use multiples of eight for balance (short prefixes are only behavior smokes).
    Fix any factor independently for ablations. deck_a/deck_b name matchup lists
    (default White/Red), not permanent seat assignments. self_play controls both
    seats; every other opponent measures the designated pilot's wins.
    benchmark recording keeps privacy projections, not restorable checkpoints.
    Text observations remove engine/UI serialization overhead; json is the raw
    ablation.

    Opponents: random, scripted_v1 (alias scripted), or native xmage_mad.
    MAD uses ComputerPlayer7 at fixed skill 4 (depth 4). It is omniscient:
    simulations copy the full game, including the pilot's real hand and exact
    library order. Its 12s wall-clock search budget uses a shared 5-thread pool;
    strength depends on hardware/load and search is not deterministic.
    Pilot observations remain private.
    """
    if num_games < 1 or max_turns < 1 or history_decisions < 1:
        raise ValueError("num_games, max_turns and history_decisions must be positive")
    if observation_format not in {"json", "text"}:
        raise ValueError("observation_format must be json or text")
    if recording_mode not in {"full_audit", "benchmark"}:
        raise ValueError("recording_mode must be full_audit or benchmark")
    if opponent == "scripted":
        opponent = "scripted_v1"
    if opponent not in {"self_play", "random", "scripted_v1", "xmage_mad"}:
        raise ValueError(
            "opponent must be self_play, random, scripted_v1, or xmage_mad"
        )
    if type(auto_pass_priority) is not bool:
        raise ValueError("auto_pass_priority must be a boolean")
    if type(max_action_attempts) is not int or max_action_attempts < 1:
        raise ValueError("max_action_attempts must be a positive integer")
    if pilot_seat not in {"alternate", "player_a", "player_b"}:
        raise ValueError("pilot_seat must be alternate, player_a, or player_b")
    if pilot_deck not in {"balanced", "deck_a", "deck_b"}:
        raise ValueError("pilot_deck must be balanced, deck_a, or deck_b")
    if pilot_play_order not in {"balanced", "play", "draw"}:
        raise ValueError("pilot_play_order must be balanced, play, or draw")
    java = java_bin or os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
    if not java or not (ROOT / "runtime/xmage-poc.jar").is_file():
        raise RuntimeError(
            "Build scripts/build_xmage_poc.py first and provide Java 21 (XMAGE_JAVA_BIN or PATH)"
        )
    for path in (deck_a, deck_b):
        if path is not None and not Path(path).is_file():
            raise ValueError(f"Decklist does not exist: {path}")
    conditions = list(
        product(
            ("deck_a", "deck_b") if pilot_deck == "balanced" else (pilot_deck,),
            ("play", "draw") if pilot_play_order == "balanced" else (pilot_play_order,),
            ("player_a", "player_b") if pilot_seat == "alternate" else (pilot_seat,),
        )
    )
    rows = []
    for i in range(num_games):
        deck, order, seat = conditions[i % len(conditions)]
        other_seat = "player_b" if seat == "player_a" else "player_a"
        rows.append(
            {
                "question": "Play the next offered action in your seat's MTG game.",
                "info": {
                    "seed": seed + i // len(conditions),
                    "pilot_seat": seat,
                    "pilot_deck": deck,
                    "opponent_deck": "deck_b" if deck == "deck_a" else "deck_a",
                    "pilot_play_order": order,
                    "starting_player": seat if order == "play" else other_seat,
                },
            }
        )
    dataset = Dataset.from_list(rows)
    rubric = (
        vf.Rubric(funcs=[pilot_win, recording_validity], weights=[1.0, 0.0])
        if opponent != "self_play"
        else vf.Rubric(funcs=[recording_validity])
    )
    for metric in (
        invalid_action_count,
        unparseable_reply_count,
        invalid_action_rate,
        fallback_action_count,
    ):
        rubric.add_metric(metric)
    return XMageEnvironment(
        dataset=dataset,
        output_dir=Path(output_dir or "environments/xmage_poc/outputs/games").resolve(),
        java_bin=java,
        history_decisions=history_decisions,
        deck_a=Path(deck_a).resolve() if deck_a else None,
        deck_b=Path(deck_b).resolve() if deck_b else None,
        opponent=opponent,
        auto_pass_priority=auto_pass_priority,
        observation_format=observation_format,
        recording_mode=recording_mode,
        max_action_attempts=max_action_attempts,
        max_turns=max_turns,
        rubric=rubric,
    )
