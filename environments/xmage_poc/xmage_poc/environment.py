from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from contextlib import AsyncExitStack
from itertools import product
from pathlib import Path
from typing import Literal

import verifiers.v1 as vf
from pydantic import Field, field_validator

from .harness import XMageHarness
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
SEATS = ("player_a", "player_b")


class InvalidAnswerError(ValueError):
    """A reply that does not commit to exactly one integer action."""


def completion_action(messages) -> int:
    text = messages[-1].content
    try:
        text = (text or "").strip()
        if "<answer>" in text or "</answer>" in text:
            if (
                text.count("<answer>") != 1
                or text.count("</answer>") != 1
                or not text.endswith("</answer>")
            ):
                raise ValueError("Expected one final answer block")
            text = text[text.index("<answer>") + len("<answer>") : -len("</answer>")]
            text = text.strip()
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
        raise InvalidAnswerError(
            'End with one <answer>{"action": <offered index>}</answer> block'
        ) from exc


def recording_validity(info) -> float:
    """POC score measures a completed, verified recording, not pilot strength."""
    return float(info.get("recording_audit", {}).get("privacy_passed", False))


def pilot_win(info) -> float:
    """A win counts only after a complete game passes the recording audit."""
    if not recording_validity(info):
        return 0.0
    outcome = next(
        (
            p
            for p in info.get("game_result", {}).get("players", [])
            if p["name"] == info.get("pilot_seat")
        ),
        None,
    )
    return float(bool(outcome and outcome["won"]))


def resolve_java(java_bin: str | None = None) -> str:
    java = java_bin or os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
    if not java or not (ROOT / "runtime/xmage-poc.jar").is_file():
        raise RuntimeError(
            "XMage runtime missing: reinstall with `prime env install xmage-poc` to download "
            "the pinned JAR (or build it with scripts/build_xmage_poc.py), and provide "
            "Java 21 (XMAGE_JAVA_BIN or PATH)"
        )
    return java


class XMageData(vf.TaskData):
    """One game: the seed block plus the pilot's seat, matchup deck, and play/draw."""

    seed: int
    pilot_seat: Literal["player_a", "player_b"]
    pilot_deck: Literal["deck_a", "deck_b"]
    opponent_deck: Literal["deck_a", "deck_b"]
    pilot_play_order: Literal["play", "draw"]
    starting_player: Literal["player_a", "player_b"]


class XMageTask(vf.Task[XMageData]):
    pass


class XMageConfig(vf.TasksetConfig):
    """Cross seat × matchup deck × play/draw within each seed block.

    num_games is the total row count, not the seed count. With all factors varying,
    use multiples of eight for balance (short prefixes are only behavior smokes).
    Fix any factor independently for ablations. deck_a/deck_b name matchup lists
    (default White/Red), not permanent seat assignments.
    """

    num_games: int = Field(1, ge=1)
    """Total games (rows); seeds advance once per block of crossed factors."""
    seed: int = 7
    """First seed block's engine seed."""
    deck_a: Path | None = None
    """Matchup decklist A (default: bundled White)."""
    deck_b: Path | None = None
    """Matchup decklist B (default: bundled Red)."""
    pilot_seat: Literal["alternate", "player_a", "player_b"] = "alternate"
    pilot_deck: Literal["balanced", "deck_a", "deck_b"] = "balanced"
    pilot_play_order: Literal["balanced", "play", "draw"] = "balanced"

    @field_validator("deck_a", "deck_b")
    @classmethod
    def _decklist_exists(cls, path: Path | None) -> Path | None:
        if path is not None and not path.is_file():
            raise ValueError(f"Decklist does not exist: {path}")
        return path.resolve() if path is not None else None


class XMageTaskset(vf.Taskset[XMageTask, XMageConfig]):
    def load(self):
        config = self.config
        conditions = list(
            product(
                ("deck_a", "deck_b")
                if config.pilot_deck == "balanced"
                else (config.pilot_deck,),
                ("play", "draw")
                if config.pilot_play_order == "balanced"
                else (config.pilot_play_order,),
                SEATS if config.pilot_seat == "alternate" else (config.pilot_seat,),
            )
        )
        for i in range(config.num_games):
            deck, order, seat = conditions[i % len(conditions)]
            other_seat = "player_b" if seat == "player_a" else "player_a"
            seed = config.seed + i // len(conditions)
            yield XMageTask(
                XMageData(
                    name=f"seed{seed}-{seat}-{deck}-{order}",
                    seed=seed,
                    pilot_seat=seat,
                    pilot_deck=deck,
                    opponent_deck="deck_b" if deck == "deck_a" else "deck_a",
                    pilot_play_order=order,
                    starting_player=seat if order == "play" else other_seat,
                ),
                config.task,
            )

    def decks_for(self, data: XMageData) -> tuple[Path, Path]:
        """Matchup deck identities stay fixed even when their seats change."""
        decks = {
            "deck_a": self.config.deck_a or ROOT / "decks/white.txt",
            "deck_b": self.config.deck_b or ROOT / "decks/red.txt",
        }
        pair = (decks[data.pilot_deck], decks[data.opponent_deck])
        return pair if data.pilot_seat == "player_a" else pair[::-1]


def seat_agent() -> vf.AgentConfig:
    # No harness pin: an unpinned seat runs this package's XMageHarness, and run()
    # refuses any other. Seats are tool-less host chat loops, so stay local.
    return vf.AgentConfig(runtime=vf.SubprocessConfig(), max_turns=4000)


class XMageEnvConfig(vf.EnvConfig):
    """The pilot seat is always played by `pilot`; `rival` plays the other seat only
    under self_play. Every other opponent plays in-engine and measures the pilot's wins.

    Opponents: random, scripted_v1 (alias scripted), or native xmage_mad.
    MAD uses ComputerPlayer7 at fixed skill 4 (depth 4). It is omniscient:
    simulations copy the full game, including the pilot's real hand and exact
    library order. Its 12s wall-clock search budget uses a shared 5-thread pool;
    strength depends on hardware/load and search is not deterministic.
    Pilot observations remain private.

    benchmark recording keeps privacy projections, not restorable checkpoints.
    Text observations remove engine/UI serialization overhead; json is the raw
    ablation. max_turns caps model attempts (including invalid-reply retries) per
    seat, not per game.
    """

    pilot: vf.AgentConfig = seat_agent()
    """Plays the row's pilot seat."""
    rival: vf.AgentConfig = seat_agent()
    """Plays the other seat under self_play; unused otherwise."""
    opponent: Literal["self_play", "random", "scripted", "scripted_v1", "xmage_mad"] = (
        "self_play"
    )
    output_dir: Path = Path("environments/xmage_poc/outputs/games")
    """Each game's recording directory is created under this one."""
    java_bin: str | None = None
    """Java 21 executable (default: XMAGE_JAVA_BIN, then PATH)."""
    history_decisions: int = Field(4, ge=1)
    """Most recent own decisions kept in each seat's prompt."""
    auto_pass_priority: bool = True
    """Submit pass-only priority prompts without a model call."""
    observation_format: Literal["json", "text"] = "text"
    recording_mode: Literal["full_audit", "benchmark"] = "full_audit"
    max_action_attempts: int = Field(3, ge=1)
    """Replies per decision before the fallback action is submitted."""

    @field_validator("max_action_attempts", mode="before")
    @classmethod
    def _not_a_bool(cls, value):
        # CLI values arrive as strings, so stay lax except for booleans.
        if isinstance(value, bool):
            # Pydantic reports ValueError, not TypeError, as a ValidationError.
            raise ValueError("max_action_attempts must be an integer")  # noqa: TRY004
        return value

    @field_validator("opponent")
    @classmethod
    def _canonical_opponent(cls, opponent: str) -> str:
        return "scripted_v1" if opponent == "scripted" else opponent


class SeatStats:
    def __init__(self):
        self.model_action_attempts = 0
        self.invalid_action_count = 0
        self.unparseable_reply_count = 0
        self.fallback_action_count = 0

    def metrics(self) -> dict[str, float]:
        attempts = self.model_action_attempts
        return {
            "model_action_attempts": float(attempts),
            # All rejected model replies, including unparseable replies.
            "invalid_action_count": float(self.invalid_action_count),
            "unparseable_reply_count": float(self.unparseable_reply_count),
            # Rejected replies / model attempts, including corrective attempts.
            "invalid_action_rate": (
                self.invalid_action_count / attempts if attempts else 0.0
            ),
            "fallback_action_count": float(self.fallback_action_count),
        }


class XMageGame:
    """One game's host-side controller: the engine plays the user of every seat.

    Each seat's prompt is rebuilt per decision from that seat's own blocks only, so
    the other seat's hand, replies and corrections can never enter it.
    """

    def __init__(self, config: XMageEnvConfig, data: XMageData, session):
        self.config = config
        self.data = data
        self.session = session
        self.auto_passed_priority = 0
        self.stats = {seat: SeatStats() for seat in SEATS}
        self.histories: dict[str, list] = {}
        self.glossaries: dict[str, dict] = {}
        self.factors: dict | None = None
        self.result: dict | None = None
        self.audit: dict | None = None

    async def receive_for_model(self) -> dict:
        """Drain forced priority passes before spending a model turn."""
        session = self.session

        def receive():
            while True:
                message = session.receive()
                if (
                    message["type"] == "result"
                    or not self.config.auto_pass_priority
                    or not is_pass_only_priority(message["observation"])
                ):
                    return message
                obs = message["observation"]
                # The Java bridge records this prompt and response as usual.
                action = obs["actions"][0]["index"]
                session.send(obs, action)
                self.auto_passed_priority += 1
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

    def show(self, obs: dict) -> None:
        """Open this decision's block in its seat's history."""
        session = self.session
        context = DECK_CONTEXT_MARKER + json.dumps(session.deck_contexts[obs["player"]])
        history = self.histories.setdefault(
            obs["player_id"], [vf.SystemMessage(content=SYSTEM + context)]
        )
        # Presentation only: neither the action protocol nor seat history changes.
        # Play/draw is public and fixed by the bridge for both seats.
        starter = self.data.starting_player
        self.factors = {
            "pilot_play_order": (
                "play" if starter in {obs["player"], obs["player_id"]} else "draw"
            ),
            "starting_player": starter,
        }
        if self.config.observation_format == "text":
            glossary = self.glossaries.setdefault(obs["player_id"], {})
            glossary.update(public_card_rules(obs))
            history[0] = vf.SystemMessage(
                content=SYSTEM + TEXT_INSTRUCTIONS + glossary_text(glossary) + context
            )
            rendered = render_observation(obs, **self.factors)
        else:
            rendered = json.dumps(obs)
        history.append([vf.UserMessage(content=rendered)])

    async def prompt(self, obs: dict) -> list:
        """Exactly the messages for this inference, recorded before it is sent."""
        history = self.histories[obs["player_id"]]
        # Trim whole decisions, not messages: corrections must never evict the
        # current observation, even with history_decisions=1. Blocks stay private
        # to their seat, including rejected replies and fallback notifications.
        prompt = [
            history[0],
            *(
                message
                for block in history[1:][-self.config.history_decisions :]
                for message in block
            ),
        ]
        # Audit every inference input, including retries, the persistent glossary
        # and trimmed history, not just the raw view.
        record = {
            "decision": obs["decision"],
            "player": obs["player"],
            **self.factors,
            "messages": [{"role": m.role, "content": m.content} for m in prompt],
        }

        def record_prompt():
            with (self.session.output / "model-prompts.jsonl").open("a") as log:
                log.write(json.dumps(record) + "\n")

        await asyncio.to_thread(record_prompt)
        return prompt

    async def reply(self, obs: dict, messages, attempt: int) -> bool:
        """Apply one model reply; True once the decision was submitted."""
        stats = self.stats[obs["player"]]
        history = self.histories[obs["player_id"]]
        history[-1].extend(messages)
        stats.model_action_attempts += 1
        try:
            action = completion_action(messages)
        except InvalidAnswerError:
            stats.unparseable_reply_count += 1
            error = "Your reply could not be parsed. Follow the response format in the system message."
        else:
            try:
                await asyncio.to_thread(self.session.send, obs, action)
                return True
            except ValueError:
                error = "The selected action is not offered for this decision."
        stats.invalid_action_count += 1
        correction = {
            "error": error,
            "decision": obs["decision"],
            "attempts_remaining": self.config.max_action_attempts - attempt,
            "instruction": "Choose an offered index from the unchanged observation above.",
        }
        exhausted = attempt >= self.config.max_action_attempts
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
            await asyncio.to_thread(self.session.send, obs, action)
            stats.fallback_action_count += 1
        history[-1].append(vf.UserMessage(content=json.dumps(correction)))
        return exhausted

    async def play(self, interactions: dict) -> None:
        """Run the game until it ends or a seat's run does (turn cap, model error)."""
        pending = await self.receive_for_model()
        while pending["type"] != "result":
            obs = pending["observation"]
            interaction = interactions.get(obs["player"])
            if interaction is None:
                raise RuntimeError(f"Engine requested unseated {obs['player']}")
            self.show(obs)
            attempt = 0
            while True:
                attempt += 1
                segment = await interaction.turn(await self.prompt(obs))
                if segment.terminated:
                    return
                if await self.reply(obs, segment.messages, attempt):
                    break
            pending = await self.receive_for_model()
        self.result = pending
        try:
            self.audit = await asyncio.to_thread(verify, self.session.output)
        except (AssertionError, OSError, ValueError) as exc:
            raise RuntimeError(f"Recording failed audit: {exc}") from exc


class XMageEnv(vf.Env[XMageEnvConfig]):
    """The engine steps host-side as each seat's user; the Java bridge lives in run()."""

    async def start(self) -> None:
        resolve_java(self.config.java_bin)

    async def run(self, task, agents):
        config = self.config
        data = task.data
        seats = {data.pilot_seat: agents.pilot}
        if config.opponent == "self_play":
            other = "player_b" if data.pilot_seat == "player_a" else "player_a"
            seats[other] = agents.rival
        for agent in seats.values():
            if not isinstance(agent.harness, XMageHarness):
                raise TypeError(
                    "XMage seats need the xmage-poc harness: it sends each audited "
                    "prompt verbatim instead of appending to the conversation"
                )
        java = resolve_java(config.java_bin)
        path = config.output_dir.resolve() / uuid.uuid4().hex
        controller = {
            "seed": data.seed,
            "pilot_seat": data.pilot_seat,
            "pilot_deck": data.pilot_deck,
            "opponent_deck": data.opponent_deck,
            "pilot_play_order": data.pilot_play_order,
            "starting_player": data.starting_player,
            "opponent": config.opponent,
            "auto_pass_priority": config.auto_pass_priority,
            "observation_format": config.observation_format,
            "history_decisions": config.history_decisions,
            "max_action_attempts": config.max_action_attempts,
            "invalid_action_fallback": "pass_no_cancel_else_first",
        }
        session = None
        try:
            async with AsyncExitStack() as stack:
                interactions = {
                    seat: await stack.enter_async_context(agent.interaction(task))
                    for seat, agent in seats.items()
                }
                session = await asyncio.to_thread(
                    GameSession if config.opponent == "self_play" else PilotSession,
                    path,
                    data.seed,
                    java,
                    *self.taskset.decks_for(data),
                    starting_player=data.starting_player,
                    recording_mode=config.recording_mode,
                    **(
                        {}
                        if config.opponent == "self_play"
                        else {
                            "pilot_seat": data.pilot_seat,
                            "opponent": config.opponent,
                        }
                    ),
                )
                await asyncio.to_thread(
                    (path / "model-controller.json").write_text,
                    json.dumps(controller, indent=2) + "\n",
                )
                game = XMageGame(config, data, session)
                await game.play(interactions)
                traces = {seat: i.trace for seat, i in interactions.items()}
        finally:
            if session is not None:
                await asyncio.to_thread(session.close)
        info = {
            "pilot_seat": data.pilot_seat,
            "opponent": config.opponent,
            "recording_path": str(path),
            "auto_passed_priority": game.auto_passed_priority,
        }
        if game.result is not None:
            info["game_result"] = game.result
            info["recording_audit"] = game.audit
        for seat, trace in traces.items():
            trace.info.update(seat=seat, **info)
            if config.opponent == "self_play":
                trace.record_reward("recording_validity", recording_validity(info))
            else:
                trace.record_reward("pilot_win", pilot_win(info))
                trace.record_reward(
                    "recording_validity", recording_validity(info), weight=0.0
                )
            trace.record_metrics(game.stats[seat].metrics())
