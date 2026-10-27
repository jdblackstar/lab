"""Read answers and score a run against a frozen question set.

    menu-taste-score private/questions-v1.jsonl private/runs/haiku-r0.jsonl [more runs]

A run is the episode JSONL of a verifiers v1 eval on the question set (``traces.jsonl``,
or prime-rl's ``monitors/file/traces/stream/*.jsonl.zst`` once decompressed), or a
JSONL of ``{id, rotation, completion}`` (what ``menu-taste-questions collect`` writes).
A run may answer each question several times (``-r``). Intervals are bootstrapped by
menu, since questions from one menu aren't independent. Rollouts that errored (the
model call failed) are counted, not scored.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .baselines import words
from .cloze import LETTERS
from .questions import load_meta, load_question_set, rotate
from .render import MISSING_MARKER

_ANSWER = re.compile(r"<answer>(.*?)</answer>", re.IGNORECASE | re.DOTALL)
_LETTER = re.compile(
    r"^[\s*_`\"'(\[]*(?:(?:option|choice|answer)\s*:?\s*)?([a-z])(?![a-z])",
    re.IGNORECASE,
)


def extract_letter(text: str, num_options: int = 4) -> str | None:
    """The letter in the last <answer> tag: "B", "(B)", "**B**", "B) Plum tart",
    "Option B" all read as B. No tag, or no valid letter in it, is no answer."""
    tags = _ANSWER.findall(text or "")
    if not tags:
        return None
    m = _LETTER.match(tags[-1])
    letter = m.group(1).upper() if m else None
    return letter if letter and letter in LETTERS[:num_options] else None


def completion_text(completion) -> str:
    if isinstance(completion, str):
        return completion
    return "\n".join(
        m.get("content") or "" for m in completion if m.get("role") == "assistant"
    )


def load_run(path: str | Path) -> list[dict]:
    """[{id, rotation, completion, error}] from a verifiers v1 traces.jsonl (one
    episode per line) or from a JSONL of ``{id, rotation, completion}``. ``error`` is
    true for a rollout that failed (e.g. the provider refused the request); evals exit
    0 even then."""
    if str(path).endswith(".zst"):
        raise ValueError(
            f"{path} is compressed; prime-rl writes its traces as zstd. Run "
            "`zstd -dc <out>/<run>/monitors/file/traces/stream/*.jsonl.zst > run.jsonl` "
            "and score run.jsonl."
        )
    rows = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if "traces" in r and "task" in r:  # verifiers v1 episode
                rows.extend(_episode_rows(r))
            else:
                rows.append(
                    {
                        **r,
                        "completion": completion_text(r["completion"]),
                        "error": False,
                    }
                )
    return rows


def _episode_rows(episode: dict) -> list[dict]:
    import verifiers.v1 as vf

    data = episode["task"]["data"]
    failed = episode.get("ok") is False or bool(episode.get("errors"))
    return [
        {
            "id": data["id"],
            "rotation": data.get("rotation", 0),
            "completion": vf.Trace.model_validate(trace).last_reply,
            "error": failed or trace.get("ok") is False or bool(trace.get("errors")),
        }
        for trace in episode["traces"]
    ] or [
        {
            "id": data["id"],
            "rotation": data.get("rotation", 0),
            "completion": "",
            "error": True,
        }
    ]


def grade(records: dict[str, dict], run: list[dict]) -> list[dict]:
    """Per answer: which option (in the question set's original order) was chosen."""
    out = []
    for r in run:
        rec = records[r["id"]]
        options, answer = rotate(rec, r["rotation"])
        letter = extract_letter(r["completion"], len(options))
        chosen = None
        if letter is not None:
            shown = LETTERS.index(letter)
            chosen = (shown + r["rotation"]) % len(options)  # back to stored order
        out.append(
            {
                "id": r["id"],
                "menu_id": rec["info"]["menu_id"],
                "course": rec["info"]["course"],
                "letter": letter,
                "chosen": chosen,
                "correct": chosen == rec["answer_index"],
                "answer_letter": LETTERS[answer],
            }
        )
    return out


def bootstrap(values: dict[str, list[float]], reps: int = 2000, seed: int = 0):
    """Mean with a 95% interval, resampling whole menus."""
    groups = list(values)
    sums = np.array([sum(values[g]) for g in groups])
    counts = np.array([len(values[g]) for g in groups])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(groups), size=(reps, len(groups)))
    stats = sums[idx].sum(1) / counts[idx].sum(1)
    return sums.sum() / counts.sum(), *np.percentile(stats, [2.5, 97.5])


def _by_menu(graded, value) -> dict[str, list[float]]:
    out = defaultdict(list)
    for g in graded:
        out[g["menu_id"]].append(value(g))
    return out


RULE = "most words shared with the menu"
CUTS = [
    "answer shares the most words with the menu (rule right)",
    "another option shares more words (rule wrong)",
    "answer tied for the most shared words",
    "answer shares no words with the menu",
]


def word_cuts(rec: dict) -> list[str]:
    """The sensitivity cuts a question falls in, by the no-taste cue "most words shared
    with the menu", computed on the dish lines and options the model is shown."""
    menu = set().union(
        *(
            words(line[2:])
            for line in rec["menu_text"].splitlines()
            if line.startswith("- ") and line[2:] != MISSING_MARKER
        )
    )
    shared = [len(words(o) & menu) for o in rec["options"]]
    answer, best = shared[rec["answer_index"]], max(shared)
    if answer < best:
        cuts = [CUTS[1]]
    elif shared.count(best) == 1:
        cuts = [CUTS[0]]
    else:
        cuts = [CUTS[2]]
    return cuts + [CUTS[3]] * (answer == 0)


def _accuracy(graded: list[dict]) -> str:
    if not graded:
        return "–"
    acc, lo, hi = bootstrap(_by_menu(graded, lambda x: float(x["correct"])))
    return f"{acc:.1%} ({lo:.1%}–{hi:.1%})"


def report(questions: str, runs: list[str], labels: list[str] | None = None) -> str:
    records = {r["id"]: r for r in load_question_set(questions)}
    meta = load_meta(questions)
    k = meta.get("num_options") or len(next(iter(records.values()))["options"])
    labels = labels or [Path(r).stem for r in runs]
    if len(labels) != len(runs) or len(set(labels)) != len(labels):
        raise ValueError(
            f"need one unique label per run: {len(runs)} run(s), labels {labels}"
        )
    loaded = {label: load_run(path) for label, path in zip(labels, runs)}
    errored = {label: sum(r["error"] for r in run) for label, run in loaded.items()}
    graded = {
        label: grade(records, [r for r in run if not r["error"]])
        for label, run in loaded.items()
    }

    lines = [
        (
            f"Question set: {Path(questions).name}, {len(records)} questions, "
            f"{k} options (chance {1 / k:.0%})"
        ),
        "",
        "| Run | Answered | Accuracy | 95% interval (by menu) | Unparsed | Errored |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, g in graded.items():
        unparsed = sum(x["letter"] is None for x in g)
        asked = len({x["id"] for x in g})
        answered = f"{asked} of {len(records)}"
        if len(g) != asked:
            answered += f" ({len(g)} answers)"
        if g:
            acc, lo, hi = bootstrap(_by_menu(g, lambda x: float(x["correct"])))
            scores = f"{acc:.1%} | {lo:.1%}–{hi:.1%}"
        else:  # an empty collected run has no accuracy to report
            scores = "– | –"
        lines.append(
            f"| {label} | {answered} | {scores} | {unparsed} | {errored[label]} |"
        )
    base = meta.get("baselines", {})
    for name in ("best combination of all cues (held-out menus)", RULE):
        if name in base:
            b = base[name]
            lines.append(
                f"| baseline: {name} | all | {b['accuracy']:.1%} "
                f"| {b['low']:.1%}–{b['high']:.1%} | | |"
            )

    lines += ["", "By course:", ""]
    courses = Counter(r["info"]["course"] for r in records.values())
    lines.append("| Course | Questions | " + " | ".join(graded) + " |")
    lines.append("| --- | --- |" + " --- |" * len(graded))
    for course, n in courses.most_common():
        cells = []
        for g in graded.values():
            hits = [x["correct"] for x in g if x["course"] == course]
            cells.append(f"{np.mean(hits):.0%} ({len(hits)})" if hits else "–")
        lines.append(f"| {course} | {n} | " + " | ".join(cells) + " |")

    cuts = {qid: word_cuts(rec) for qid, rec in records.items()}
    lines += [
        "",
        f'Sensitivity: accuracy (95% interval) by whether the no-taste rule "{RULE}" '
        "picks the answer:",
        "",
        "| Questions where | Questions | " + " | ".join(graded) + " |",
        "| --- | --- |" + " --- |" * len(graded),
    ]
    for cut in CUTS:
        n = sum(cut in c for c in cuts.values())
        cells = [
            _accuracy([x for x in g if cut in cuts[x["id"]]]) for g in graded.values()
        ]
        lines.append(f"| {cut} | {n} | " + " | ".join(cells) + " |")

    lines += ["", "Letters chosen (position bias) vs. right answers:", ""]
    for label, g in graded.items():
        chosen = Counter(x["letter"] for x in g if x["letter"])
        right = Counter(x["answer_letter"] for x in g)
        lines.append(
            f"- {label}: chose "
            + ", ".join(f"{L} {chosen[L]}" for L in LETTERS[:k])
            + "; right "
            + ", ".join(f"{L} {right[L]}" for L in LETTERS[:k])
        )

    names = list(graded)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1 :]]
    if pairs:
        lines += [
            "",
            "Pairs (questions both answered; repeats matched in order):",
            "",
            "| A | B | Shared | Same dish chosen | A − B accuracy (95%) |",
            "| --- | --- | --- | --- | --- |",
        ]
    for a, b in pairs:
        ga, gb = defaultdict(list), defaultdict(list)
        for x in graded[a]:
            ga[x["id"]].append(x)
        for x in graded[b]:
            gb[x["id"]].append(x)
        shared = sorted(set(ga) & set(gb))
        if not shared:
            continue
        same = np.mean(
            [
                xa["chosen"] is not None and xa["chosen"] == xb["chosen"]
                for i in shared
                for xa, xb in zip(ga[i], gb[i])
            ]
        )
        diff = defaultdict(list)
        for i in shared:
            diff[records[i]["info"]["menu_id"]].append(
                np.mean([x["correct"] for x in ga[i]])
                - np.mean([x["correct"] for x in gb[i]])
            )
        d, lo, hi = bootstrap(diff)
        lines.append(
            f"| {a} | {b} | {len(shared)} | {same:.0%} | {d:+.1%} ({lo:+.1%} to {hi:+.1%}) |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="menu-taste-score",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("questions")
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--labels", nargs="+", default=None)
    args = parser.parse_args(argv)
    print(report(args.questions, args.runs, args.labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
