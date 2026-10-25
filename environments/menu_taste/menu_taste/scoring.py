"""Read answers and score a run against a frozen question set.

    menu-taste-score private/questions-v1.jsonl private/runs/haiku-r0.jsonl [more runs]

A run is the episode JSONL of a verifiers v1 eval on the question set (``traces.jsonl``,
or prime-rl's ``monitors/file/traces/stream/*.jsonl.zst`` once decompressed), or a
JSONL of ``{id, rotation, completion}`` (what ``menu-taste-questions collect`` writes). Intervals are bootstrapped
by menu, since questions from one menu aren't independent.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .baselines import bar
from .cloze import LETTERS
from .questions import load_meta, load_question_set, rotate

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
    """[{id, rotation, completion}] from a verifiers v1 traces.jsonl (one episode per
    line) or from a JSONL of ``{id, rotation, completion}``."""
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
                rows.append({**r, "completion": completion_text(r["completion"])})
    return rows


def _episode_rows(episode: dict) -> list[dict]:
    import verifiers.v1 as vf

    data = episode["task"]["data"]
    return [
        {
            "id": data["id"],
            "rotation": data.get("rotation", 0),
            "completion": vf.Trace.model_validate(trace).last_reply,
        }
        for trace in episode["traces"]
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


def report(questions: str, runs: list[str], labels: list[str] | None = None) -> str:
    records = {r["id"]: r for r in load_question_set(questions)}
    meta = load_meta(questions)
    k = meta.get("num_options") or len(next(iter(records.values()))["options"])
    labels = labels or [Path(r).stem for r in runs]
    if len(labels) != len(runs) or len(set(labels)) != len(labels):
        raise ValueError(
            f"need one unique label per run: {len(runs)} run(s), labels {labels}"
        )
    graded = {
        label: grade(records, load_run(path)) for label, path in zip(labels, runs)
    }

    lines = [
        (
            f"Question set: {Path(questions).name}, {len(records)} questions, "
            f"{k} options (chance {1 / k:.0%})"
        ),
        "",
        "| Run | Answered | Accuracy | 95% interval (by menu) | Unparsed |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, g in graded.items():
        unparsed = sum(x["letter"] is None for x in g)
        if g:
            acc, lo, hi = bootstrap(_by_menu(g, lambda x: float(x["correct"])))
            scores = f"{acc:.1%} | {lo:.1%}–{hi:.1%}"
        else:  # an empty collected run has no accuracy to report
            scores = "– | –"
        lines.append(
            f"| {label} | {len(g)} of {len(records)} | {scores} | {unparsed} |"
        )
    base = meta.get("baselines", {})
    for i, name in enumerate(bar(base)):  # the first, higher row is the bar to clear
        b = base[name]
        lines.append(
            f"| baseline{' (bar)' if i == 0 else ''}: {name} | all | "
            f"{b['accuracy']:.1%} | {b['low']:.1%}–{b['high']:.1%} | |"
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
        lines += ["", "Pairs (questions both answered):", ""]
        lines.append("| A | B | Shared | Same dish chosen | A − B accuracy (95%) |")
        lines.append("| --- | --- | --- | --- | --- |")
    for a, b in pairs:
        ga = {x["id"]: x for x in graded[a]}
        gb = {x["id"]: x for x in graded[b]}
        shared = sorted(set(ga) & set(gb))
        if not shared:
            continue
        same = np.mean(
            [
                ga[i]["chosen"] is not None and ga[i]["chosen"] == gb[i]["chosen"]
                for i in shared
            ]
        )
        diff = defaultdict(list)
        for i in shared:
            diff[ga[i]["menu_id"]].append(
                float(ga[i]["correct"]) - float(gb[i]["correct"])
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
