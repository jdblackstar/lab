"""Scripted-vs-scripted base rates on the same balanced cases as model evals.

Run: python -m xmage_poc.baseline --output <new-directory> --num-seeds 25
This is a native-controller baseline, not an LLM/Prime evaluation. Every game
passes the Python recording/privacy audit before counting. Recordings are kept
unless --discard-recordings is supplied; per-game results and audits always stay.
"""

from __future__ import annotations

import argparse
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from math import sqrt
from pathlib import Path
from threading import Lock

from .decklist import deck_context
from .environment import XMageConfig, XMageTaskset, resolve_java
from .transport import ROOT, run
from .verify import verify

FACTORS = {
    "seed",
    "pilot_seat",
    "pilot_deck",
    "opponent_deck",
    "pilot_play_order",
    "starting_player",
}


def summarize(records):
    """Stratified win proportions with binomial 95% Wilson score intervals.

    These intervals do not account for dependence between cases in a seed block.
    """
    strata = {}
    for keys in (
        (),
        ("pilot_deck",),
        ("pilot_play_order",),
        ("pilot_seat",),
        ("pilot_deck", "pilot_play_order"),
    ):
        groups = {}
        for record in records:
            label = "/".join(record[key] for key in keys) or "all"
            group = groups.setdefault(label, {"games": 0, "wins": 0, "losses": 0})
            group["games"] += 1
            group["wins"] += int(record["won"])
            group["losses"] += int(record["lost"])
        for group in groups.values():
            n = group["games"]
            p = group["wins"] / n
            z = 1.959963984540054
            denominator = 1 + z * z / n
            center = (p + z * z / (2 * n)) / denominator
            radius = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
            group["draws"] = n - group["wins"] - group["losses"]
            group["win_rate"] = p
            group["win_rate_ci95"] = [
                max(0.0, center - radius),
                min(1.0, center + radius),
            ]
        strata["/".join(keys) or "overall"] = groups
    return strata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-seeds", type=int, default=25)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--java-bin")
    parser.add_argument("--deck-a")
    parser.add_argument("--deck-b")
    parser.add_argument("--discard-recordings", action="store_true")
    args = parser.parse_args()
    if args.num_seeds < 1 or args.workers < 1:
        parser.error("num-seeds and workers must be positive")
    taskset = XMageTaskset(
        XMageConfig(
            id="xmage-poc",
            num_games=8 * args.num_seeds,
            seed=args.seed,
            deck_a=args.deck_a,
            deck_b=args.deck_b,
        )
    )
    java = resolve_java(args.java_bin)
    cases = [task.data for task in taskset]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(ROOT / "runtime/build.json", output / "runtime-build.json")
    records = []
    log_lock = Lock()

    def exercise(case):
        index, data = case
        recording = output / f"game-{index:04d}"
        deck_a, deck_b = taskset.decks_for(data)
        result = run(
            recording,
            seed=data.seed,
            java_bin=java,
            deck_a=deck_a,
            deck_b=deck_b,
            starting_player=data.starting_player,
        )
        audit = verify(recording)
        pilot = next(p for p in result["players"] if p["name"] == data.pilot_seat)
        record = {
            **data.model_dump(include=FACTORS),
            "won": pilot["won"],
            "lost": pilot["lost"],
            "game_result": result,
            "recording_audit": audit,
        }
        if not args.discard_recordings:
            record["recording_path"] = str(recording)
        # Persist in the worker: an earlier case may fail before map yields this one.
        with log_lock:
            log.write(json.dumps(record) + "\n")
            log.flush()
            records.append(record)
            print(
                f"Audited {len(records)}/{len(cases)} games",
                flush=True,
            )
        if args.discard_recordings:
            shutil.rmtree(recording)

    # Keep the log open until all running workers finish, including on failure.
    with (
        (output / "games.jsonl").open("w") as log,
        ThreadPoolExecutor(max_workers=args.workers) as executor,
    ):
        for _ in executor.map(exercise, enumerate(cases)):
            pass

    summary = {
        "controller": "scripted_v1 vs scripted_v1",
        "num_seeds": args.num_seeds,
        "first_seed": args.seed,
        "decks": {
            name: deck_context(path.read_text().splitlines(), name)
            for name, path in (
                ("deck_a", taskset.config.deck_a or ROOT / "decks/white.txt"),
                ("deck_b", taskset.config.deck_b or ROOT / "decks/red.txt"),
            )
        },
        "recordings_kept": not args.discard_recordings,
        "caveat": "Cases within a seed are paired, not independent trials; binomial 95% Wilson intervals ignore this dependence. Base rates describe only these decks and this controller.",
        "strata": summarize(records),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
