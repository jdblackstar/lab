"""Mine "best move" eval questions from full_audit recordings by playout.

For each resumable decision (priority, or the first declare attackers/blockers
ask), the bridge resumes the engine checkpoint, enumerates every complete
candidate action (a spell with its targets, an attacker subset, a blocker
assignment), and plays each out many times from the same resampled hidden
worlds. A candidate is labeled best only when it beats every alternative by a
paired margin; the rendered board comes from the seat's own observation.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

from .environment import resolve_java
from .render import glossary_text, public_card_rules, render_observation
from .transport import ROOT

SCORE = {"W": 1.0, "D": 0.5, "L": 0.0}


def resumable(observation: dict) -> bool:
    """Mirror of Resume.resumable in the bridge."""
    return observation["query_type"] == "SELECT" and not any(
        a["kind"].startswith("remove_") for a in observation["actions"]
    )


def at_boundary(observation: dict, boundary: str) -> bool:
    """Whether a decision is a question position: `any` resumable prompt, or
    (`empty-stack`) one with nothing on the stack, so it needs no
    "in response to" context."""
    if not resumable(observation):
        return False
    return boundary == "any" or not observation["view"].get("stack")


def rollout(recording: Path, decision: int, *, java: str, jar: Path, **options) -> dict:
    flags = [f"--{key.replace('_', '-')}={value}" for key, value in options.items()]
    result = subprocess.run(
        [java, "-Djava.awt.headless=true", "-cp", str(jar), "lab.xmage.PocMain"]
        + ["rollout", str(recording), str(decision), *flags],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def paired(best: str, other: str) -> tuple[float, float]:
    """Mean and standard error of per-playout score differences (common random numbers).

    A failed playout's outcome is unknown, so it counts against the best
    candidate: a loss for it and a win for the alternative. Errors then can
    only withhold an answer, never create one.
    """
    diffs = [
        (0.0 if a == "E" else SCORE[a]) - (1.0 if b == "E" else SCORE[b])
        for a, b in zip(best, other, strict=True)
    ]
    if len(diffs) < 2:
        return 0.0, math.inf
    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)
    return mean, math.sqrt(var / len(diffs))


def label(result: dict, z: float) -> dict:
    """Best candidate and its weakest paired margin; answer is None unless it clears z."""
    candidates = result["candidates"]
    best = max(
        candidates, key=lambda c: c["win_rate"] if c["win_rate"] is not None else -1
    )
    margins = [
        (*paired(best["outcomes"], c["outcomes"]), c["candidate"])
        for c in candidates
        if c is not best
    ]
    mean, se, runner_up = min(margins, key=lambda m: m[0] - z * m[1])
    return {
        "answer": best["candidate"] if mean - z * se > 0 else None,
        "best": best["candidate"],
        "runner_up": runner_up,
        "margin": mean,
        "margin_se": se,
    }


def question(
    recording: Path, record: dict, result: dict, verdict: dict, boundary: str
) -> dict:
    observation = dict(record["observation"])
    observation["actions"] = [
        {
            "index": c["candidate"],
            "kind": "candidate",
            "label": c["ref_label"],
            "response_type": "string",
            "value": c["ref_label"],
        }
        for c in result["candidates"]
    ]
    # What the seat legitimately knows, as the environment shows it: play/draw,
    # rules of cards this observation shows, and its own registered deck list.
    starter = json.loads((recording / "internal/manifest.json").read_text())[
        "starting_player"
    ]
    deck = (recording / "players" / f"{observation['player']}.context.json").read_text()
    prompt = (
        render_observation(observation, starting_player=starter)
        + "\n"
        + glossary_text(public_card_rules(observation))
        + "\nYour deck list: "
        + json.dumps(json.loads(deck)["decklist"])
    )
    return {
        "recording": str(recording),
        "decision": record["decision"],
        "player": observation["player"],
        "turn": result["turn"],
        "step": result["step"],
        "prompt": prompt,
        "candidates": [
            {
                key: c[key]
                for key in (
                    "candidate",
                    "label",
                    "win_rate",
                    "wins",
                    "losses",
                    "draws",
                    "errors",
                )
            }
            for c in result["candidates"]
        ],
        **verdict,
        "boundary": boundary,
        "rollout": {
            key: result[key]
            for key in (
                "policy",
                "playouts",
                "seed",
                "turn_cap",
                "determinize",
                "checks",
            )
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--decisions", type=int, nargs="*", help="Default: every decision at --boundary"
    )
    parser.add_argument("--playouts", type=int, default=64)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--policy", choices=["greedy", "random", "mad"], default="greedy"
    )
    parser.add_argument("--turn-cap", type=int, default=20)
    parser.add_argument(
        "--z", type=float, default=2.0, help="Paired margin, in standard errors"
    )
    parser.add_argument(
        "--boundary",
        choices=["empty-stack", "any"],
        default="empty-stack",
        help="Which resumable decisions become questions",
    )
    parser.add_argument("--java-bin")
    parser.add_argument("--jar", type=Path, default=ROOT / "runtime/xmage-poc.jar")
    args = parser.parse_args()
    java = resolve_java(args.java_bin)
    records = [
        json.loads(line)
        for line in (args.recording / "internal/decisions.jsonl")
        .read_text()
        .splitlines()
    ]
    wanted = set(args.decisions or [])
    with args.output.open("a") as out:
        for record in records:
            if wanted and record["decision"] not in wanted:
                continue
            # Skip forced choices; the bridge offers pass alongside every real option.
            if (
                not at_boundary(record["observation"], args.boundary)
                or len(record["observation"]["actions"]) < 2
            ):
                continue
            result = rollout(
                args.recording,
                record["decision"],
                java=java,
                jar=args.jar,
                playouts=args.playouts,
                seed=args.seed,
                policy=args.policy,
                turn_cap=args.turn_cap,
            )
            if len(result["candidates"]) < 2 or not all(
                result["checks"][k] for k in ("seat_view_matches", "sources_match")
            ):
                continue
            verdict = label(result, args.z)
            item = question(args.recording, record, result, verdict, args.boundary)
            out.write(json.dumps(item) + "\n")
            out.flush()
            print(
                json.dumps(
                    {
                        k: item[k]
                        for k in (
                            "decision",
                            "turn",
                            "step",
                            "answer",
                            "best",
                            "margin",
                            "margin_se",
                        )
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
