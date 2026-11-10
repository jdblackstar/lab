"""Answer a frozen question set in batches, e.g. with Claude Code subagents.

An alternative to the eval for readers that answer several questions at once. Each
reader gets one batch file and writes its answers next to it; ``collect`` turns those
into a run file that ``menu-taste-score`` reads. ``human`` writes one sheet for a
person to fill in, without the key, under the same rule.

    menu-taste-batches write private/questions-v1.jsonl --out private/runs/haiku-r0
    menu-taste-batches collect private/runs/haiku-r0 -o private/runs/haiku-r0.jsonl
    menu-taste-batches human private/questions-v1.jsonl -n 50 --out private/human/chef-a
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from .cloze import SYSTEM_PROMPT
from .questions import load_question_set, to_row


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def make_batches(records: list[dict], size: int, seed: int = 0) -> list[list[dict]]:
    """Group questions for a reader that answers several at once (one subagent per batch).

    Two questions from the same menu (or versions of it) never share a batch: one
    would show the dish the other hides. Nor does a question share a batch with any
    question whose text contains its hidden dish.
    """
    order = list(records)
    random.Random(f"{seed}:batches").shuffle(order)
    batches: list[list[dict]] = []
    for rec in order:
        related = set(rec["related_menu_ids"]) | {rec["info"]["menu_id"]}
        target = _norm(rec["info"]["target"])
        text = _norm(rec["menu_text"] + " " + " ".join(rec["options"]))
        for batch in batches:
            if len(batch) >= size:
                continue
            if any(o["info"]["menu_id"] in related for o in batch):
                continue
            if any(
                target in o["_text"] or _norm(o["info"]["target"]) in text
                for o in batch
            ):
                continue
            batch.append({**rec, "_text": text})
            break
        else:
            batches.append([{**rec, "_text": text}])
    return [[{k: v for k, v in r.items() if k != "_text"} for r in b] for b in batches]


BATCH_HEADER = """{system}

Answer each of the {n} questions below on its own. Each is a different menu; don't
use one question to answer another. For each question, write its id as a heading
(`### q-...`), reason briefly if useful, then give the letter inside <answer></answer>
tags.
"""


def batch_text(batch: list[dict], rotation: int, system: str) -> str:
    parts = [BATCH_HEADER.format(system=system, n=len(batch))]
    for rec in batch:
        parts.append(
            f"\n---\n\n### {rec['id']}\n\n{to_row(rec, rotation)['question']}\n"
        )
    return "".join(parts)


def write_batches(
    questions: str, out: str, size: int, rotation: int, limit: int | None, seed: int
) -> list[Path]:
    records = load_question_set(questions)
    if limit:
        records = random.Random(f"{seed}:limit").sample(
            records, min(limit, len(records))
        )
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    manifest = {"questions": str(questions), "rotation": rotation, "batches": {}}
    for i, batch in enumerate(make_batches(records, size, seed)):
        path = out_dir / f"batch-{i:03d}.md"
        path.write_text(batch_text(batch, rotation, SYSTEM_PROMPT))
        manifest["batches"][path.name] = [r["id"] for r in batch]
        paths.append(path)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return paths


def sample_questions(records: list[dict], n: int, seed: int = 0) -> list[dict]:
    """A seeded sample of up to ``n`` questions, no two of which reveal each other.

    The same rule as ``make_batches`` within a batch: its first batch is a seeded
    first-fit pass over all the questions. Fewer than ``n`` come back only when the
    set has too few compatible questions.
    """
    return make_batches(records, n, seed)[0] if records else []


HUMAN_HEADER = """# Menu quiz: {n} questions

Each question below is a catered menu with one dish removed. Pick the option you think
was removed and type its letter between the answer tags under the question, like
<answer>B</answer>. A line of reasoning above the tags is welcome but not needed.

Answer every question, guessing when unsure. Work alone, and don't look the menus or
dishes up. Each question is a different menu; don't use one to answer another.
"""


def write_sheet(
    questions: str, out: str, n: int, rotation: int = 0, seed: int = 0
) -> tuple[Path, int]:
    """Write ``sheet.md``: a seeded sample of ``n`` questions for a person to answer
    in place, without the key. ``collect`` reads the answers back from it."""
    records = sample_questions(load_question_set(questions), n, seed)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / "sheet.md"
    sheet.write_text(
        HUMAN_HEADER.format(n=len(records))
        + "".join(
            f"\n---\n\n### {rec['id']}\n\n{to_row(rec, rotation)['question']}\n\n"
            "Your answer: <answer></answer>\n"
            for rec in records
        )
    )
    # One "batch" whose answer file is the sheet itself (collect maps batch-NNN.md
    # to answers-NNN.md and leaves other names alone).
    manifest = {
        "questions": str(questions),
        "rotation": rotation,
        "batches": {sheet.name: [r["id"] for r in records]},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return sheet, len(records)


_HEADING = re.compile(r"^#{2,4}\s*(q-[0-9a-f]{10})\b.*$", re.MULTILINE)


def split_answers(text: str) -> dict[str, str]:
    """``### q-id`` sections of a reader's answer file -> {id: completion text}."""
    marks = list(_HEADING.finditer(text))
    out = {}
    for m, nxt in zip(marks, [*marks[1:], None]):
        out[m.group(1)] = text[m.end() : nxt.start() if nxt else len(text)].strip()
    return out


def collect(run_dir: str, out: str) -> dict:
    """Gather answers-NNN.md files written for each batch (or a filled sheet) into
    one run file."""
    run = Path(run_dir)
    manifest = json.loads((run / "manifest.json").read_text())
    rows, missing = [], []
    for batch_name, ids in manifest["batches"].items():
        answer_file = run / batch_name.replace("batch-", "answers-")
        answers = split_answers(answer_file.read_text()) if answer_file.exists() else {}
        for qid in ids:
            if qid in answers:
                rows.append(
                    {
                        "id": qid,
                        "rotation": manifest["rotation"],
                        "completion": answers[qid],
                    }
                )
            else:
                missing.append(qid)
    Path(out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {"answered": len(rows), "missing": len(missing)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="menu-taste-batches",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="Split a question set into batch files to answer")
    w.add_argument("questions")
    w.add_argument("--out", required=True)
    w.add_argument("--size", type=int, default=15)
    w.add_argument("--rotation", type=int, default=0)
    w.add_argument(
        "--limit", type=int, default=None, help="Seeded sample of N questions"
    )
    w.add_argument("--seed", type=int, default=0)
    h = sub.add_parser(
        "human",
        help="Write a sampled quiz sheet for a person to answer, without the key",
    )
    h.add_argument("questions")
    h.add_argument("--out", required=True)
    h.add_argument("-n", type=int, default=50, help="How many questions")
    h.add_argument("--rotation", type=int, default=0)
    h.add_argument("--seed", type=int, default=0)
    c = sub.add_parser(
        "collect",
        help="Gather answers-NNN.md files (or a filled sheet) into a run file",
    )
    c.add_argument("run_dir")
    c.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "write":
        paths = write_batches(
            args.questions, args.out, args.size, args.rotation, args.limit, args.seed
        )
        print(f"wrote {len(paths)} batches to {args.out}")
    elif args.cmd == "human":
        sheet, n = write_sheet(
            args.questions, args.out, args.n, args.rotation, args.seed
        )
        print(f"wrote {n} questions to {sheet}")
        if n < args.n:
            print(
                f"only {n} of the questions can share one sheet without one "
                "revealing another; answer more on a sheet with another --seed, "
                "given to a different person"
            )
    else:
        print(json.dumps(collect(args.run_dir, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
