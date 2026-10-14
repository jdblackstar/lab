"""Only player observations cross the subprocess protocol; internal files stay private."""

from __future__ import annotations

import json
import os
import random
import selectors
import shutil
import subprocess
from pathlib import Path

from .decklist import deck_context

ROOT = Path(__file__).resolve().parent


class GameSession:
    def __init__(
        self,
        output: Path,
        seed: int = 7,
        java_bin: str | None = None,
        deck_a: Path | None = None,
        deck_b: Path | None = None,
        engine_ai_seat: str | None = None,
    ):
        if engine_ai_seat not in {None, "player_a", "player_b"}:
            raise ValueError("engine_ai_seat must be player_a, player_b, or None")
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        java = java_bin or os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
        jar = ROOT / "runtime" / "xmage-poc.jar"
        if not java or not jar.is_file():
            raise RuntimeError(
                "Build the bridge with scripts/build_xmage_poc.py and provide Java 21 on PATH or XMAGE_JAVA_BIN."
            )
        build_manifest = ROOT / "runtime/build.json"
        if build_manifest.is_file():
            shutil.copyfile(build_manifest, self.output / "runtime-build.json")
        deck_paths = [
            (deck_a or ROOT / "decks/white.txt").resolve(),
            (deck_b or ROOT / "decks/red.txt").resolve(),
        ]
        self.deck_contexts = {
            player: deck_context(path.read_text().splitlines(), player)
            for player, path in zip(("player_a", "player_b"), deck_paths, strict=True)
        }
        # Capture the registered list before starting the engine/shuffle. The
        # context contains counts, never instance IDs or live library order.
        (self.output / "players").mkdir()
        for player, context in self.deck_contexts.items():
            (self.output / "players" / f"{player}.context.json").write_text(
                json.dumps(context, indent=2) + "\n"
            )
        self.stderr = (self.output / "engine.stderr.log").open("w")
        self.process = subprocess.Popen(
            [
                java,
                "-Djava.awt.headless=true",
                "-jar",
                str(jar),
                str(self.output),
                str(seed),
                *(str(path) for path in deck_paths),
                engine_ai_seat or "none",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
            cwd=self.output,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def receive(self, timeout: float = 60) -> dict:
        if not self.selector.select(timeout):
            raise TimeoutError(
                "XMage did not produce a decision; see engine.stderr.log"
            )
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(
                f"XMage exited with code {self.process.poll()}; see {self.output / 'engine.stderr.log'}"
            )
        value = json.loads(line)
        if value["type"] == "result" and (
            not value["ended"] or value["errors"] or value["technical_failure"]
        ):
            raise RuntimeError(f"Invalid game result: {value}")
        return value

    def send(self, observation: dict, action: int) -> None:
        if type(action) is not int or not 0 <= action < len(observation["actions"]):
            raise ValueError("Action must be an index in this observation's actions")
        self.process.stdin.write(
            json.dumps({"decision": observation["decision"], "action": action}) + "\n"
        )
        self.process.stdin.flush()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()
        self.stderr.close()


def is_pass_only_priority(observation: dict) -> bool:
    """Recognize priority passes, without swallowing combat or other choices."""
    actions = observation["actions"]
    return (
        observation["query_type"] == "SELECT"
        and observation["message"]
        in {"Play spells and abilities", "Play instants and activated abilities"}
        and len(actions) == 1
        and actions[0]["kind"] == "pass"
    )


def advance_action(observation: dict) -> int:
    """Simple local controller that uses ONLY the delivered observation."""
    actions = observation["actions"]
    if "starting player" in str(observation.get("message") or "").lower():
        own = next(
            (a for a in actions if a.get("value") == observation["player_id"]), None
        )
        if own:
            return own["index"]
    for kind in ("no", "attack", "block", "land", "cast", "mana"):
        found = next((a for a in actions if a["kind"] == kind), None)
        if found is not None:
            return found["index"]
    # Prefer the other player as a burn target, using public player identifiers.
    opponent_ids = {
        p["playerId"]
        for p in observation["view"]["players"]
        if p["playerId"] != observation["player_id"]
    }
    opponent = next(
        (a for a in actions if a["kind"] == "target" and a["value"] in opponent_ids),
        None,
    )
    if opponent:
        return opponent["index"]
    passed = next((a for a in actions if a["kind"] == "pass"), None)
    return passed["index"] if passed else actions[0]["index"]


class PilotSession:
    """Expose one seat, with a local observation-only policy or engine-native AI."""

    def __init__(
        self,
        output: Path,
        seed: int = 7,
        java_bin: str | None = None,
        deck_a: Path | None = None,
        deck_b: Path | None = None,
        pilot_seat: str = "player_a",
        auto_forced: bool = False,
        opponent: str = "scripted_v1",
    ):
        if pilot_seat not in {"player_a", "player_b"}:
            raise ValueError("pilot_seat must be player_a or player_b")
        if opponent == "scripted":
            opponent = "scripted_v1"
        if opponent not in {"random", "scripted_v1", "xmage_mad"}:
            raise ValueError("opponent must be random, scripted_v1, or xmage_mad")
        opponent_seat = "player_b" if pilot_seat == "player_a" else "player_a"
        self.game = GameSession(
            output,
            seed,
            java_bin,
            deck_a,
            deck_b,
            engine_ai_seat=opponent_seat if opponent == "xmage_mad" else None,
        )
        self.output = self.game.output
        self.deck_contexts = self.game.deck_contexts
        self.pilot_seat = pilot_seat
        self.auto_forced = auto_forced
        self.opponent = opponent
        self.random = random.Random(seed)
        self.opponent_decisions = 0
        self.forced_pilot_decisions = 0
        (self.output / "controllers.json").write_text(
            json.dumps(
                {
                    "pilot_seat": pilot_seat,
                    "opponent": opponent,
                    "auto_forced": auto_forced,
                },
                indent=2,
            )
            + "\n"
        )

    def receive(self, timeout: float = 60) -> dict:
        while True:
            message = self.game.receive(timeout)
            if message["type"] == "result":
                message["pilot_seat"] = self.pilot_seat
                message["opponent_decisions"] = self.opponent_decisions
                message["forced_pilot_decisions"] = self.forced_pilot_decisions
                return message
            observation = message["observation"]
            if observation["player"] != self.pilot_seat:
                if self.opponent == "xmage_mad":
                    raise RuntimeError(
                        "Engine AI unexpectedly requested a controller action"
                    )
                action = (
                    self.random.choice(observation["actions"])["index"]
                    if self.opponent == "random"
                    else advance_action(observation)
                )
                self.game.send(observation, action)
                self.opponent_decisions += 1
            elif self.auto_forced and len(observation["actions"]) == 1:
                self.game.send(observation, 0)
                self.forced_pilot_decisions += 1
            else:
                return message

    def send(self, observation: dict, action: int) -> None:
        if observation["player"] != self.pilot_seat:
            raise ValueError("Observation belongs to the other seat")
        self.game.send(observation, action)

    def close(self) -> None:
        self.game.close()


def run(
    output: Path,
    seed: int = 7,
    interactive: bool = False,
    java_bin: str | None = None,
    deck_a: Path | None = None,
    deck_b: Path | None = None,
    pilot_seat: str | None = None,
    auto_forced: bool = False,
    opponent: str = "scripted_v1",
    pilot_policy: str = "scripted_v1",
) -> dict:
    if pilot_policy not in {"scripted_v1", "random"}:
        raise ValueError("pilot_policy must be scripted_v1 or random")
    if not pilot_seat and opponent != "scripted_v1":
        raise ValueError("Choose pilot_seat to select an opponent")
    session = (
        PilotSession(
            output, seed, java_bin, deck_a, deck_b, pilot_seat, auto_forced, opponent
        )
        if pilot_seat
        else GameSession(output, seed, java_bin, deck_a, deck_b)
    )
    rng = random.Random(seed)
    try:
        if interactive:
            seats = [pilot_seat] if pilot_seat else ["player_a", "player_b"]
            for player in seats:
                print(
                    json.dumps(
                        {"type": "deck_context", **session.deck_contexts[player]},
                        indent=2,
                    ),
                    flush=True,
                )
        while True:
            message = session.receive()
            if message["type"] == "result":
                return message
            observation = message["observation"]
            action = (
                rng.choice(observation["actions"])["index"]
                if pilot_policy == "random"
                else advance_action(observation)
            )
            if interactive:
                view = observation["view"]
                print(
                    json.dumps(
                        {
                            "decision": observation["decision"],
                            "player": observation["player"],
                            "turn": view["turn"],
                            "step": view.get("step"),
                            "hand": [c["name"] for c in view["myHand"].values()],
                            "players": [
                                {
                                    "name": p["name"],
                                    "life": p["life"],
                                    "hand_count": p["handCount"],
                                    "library_count": p["libraryCount"],
                                    "battlefield": [
                                        {
                                            "name": c["name"],
                                            "power": c.get("power"),
                                            "toughness": c.get("toughness"),
                                            "tapped": c.get("tapped"),
                                            "id": cid,
                                        }
                                        for cid, c in p["battlefield"].items()
                                    ],
                                }
                                for p in view["players"]
                            ],
                            "query": observation["message"],
                            "actions": observation["actions"],
                            "stack": [
                                {"name": c["name"], "id": cid}
                                for cid, c in view["stack"].items()
                            ],
                            "combat": [
                                {
                                    "attackers": {
                                        cid: c["name"]
                                        for cid, c in group["attackers"].items()
                                    },
                                    "blockers": {
                                        cid: c["name"]
                                        for cid, c in group["blockers"].items()
                                    },
                                    "defender": group.get("defenderName"),
                                    "blocked": group["isBlocked"],
                                }
                                for group in view["combat"]
                            ],
                        },
                        indent=2,
                    ),
                    flush=True,
                )
                answer = input(
                    f"Action [suggested {action}; 'auto' to finish]: "
                ).strip()
                if answer == "auto":
                    interactive = False
                elif answer:
                    action = int(answer)
            session.send(observation, action)
    finally:
        session.close()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--java-bin")
    parser.add_argument("--deck-a", type=Path)
    parser.add_argument("--deck-b", type=Path)
    parser.add_argument(
        "--pilot-seat",
        choices=["player_a", "player_b"],
        help="Control one seat against the selected opponent",
    )
    parser.add_argument(
        "--opponent",
        choices=["random", "scripted_v1", "scripted", "xmage_mad"],
        default="scripted_v1",
    )
    parser.add_argument(
        "--pilot-policy",
        choices=["scripted_v1", "random"],
        default="scripted_v1",
        help="Local pilot policy for opponent ladder checks (overridden by interactive input)",
    )
    parser.add_argument(
        "--auto-forced",
        action="store_true",
        help="Automatically take single-option pilot choices in single-seat mode",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.output,
                args.seed,
                args.interactive,
                args.java_bin,
                args.deck_a,
                args.deck_b,
                args.pilot_seat,
                args.auto_forced,
                args.opponent,
                args.pilot_policy,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
