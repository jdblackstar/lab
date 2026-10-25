"""Answer a frozen question set in batches, e.g. with Claude Code subagents.

An alternative to the eval for readers that answer several questions at once. Each
reader gets one batch file and writes its answers next to it; ``collect`` turns those
into a run file that ``menu-taste-score`` reads.

    menu-taste-batches write private/questions-v1.jsonl --out private/runs/haiku-r0
    menu-taste-batches collect private/runs/haiku-r0 -o private/runs/haiku-r0.jsonl
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


_HEADING = re.compile(r"^#{2,4}\s*(q-[0-9a-f]{10})\b.*$", re.MULTILINE)


def split_answers(text: str) -> dict[str, str]:
    """``### q-id`` sections of a reader's answer file -> {id: completion text}."""
    marks = list(_HEADING.finditer(text))
    out = {}
    for m, nxt in zip(marks, [*marks[1:], None]):
        out[m.group(1)] = text[m.end() : nxt.start() if nxt else len(text)].strip()
    return out


def collect(run_dir: str, out: str) -> dict:
    """Gather answers-NNN.md files written for each batch into one run file."""
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
    c = sub.add_parser("collect", help="Gather answers-NNN.md files into a run file")
    c.add_argument("run_dir")
    c.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "write":
        paths = write_batches(
            args.questions, args.out, args.size, args.rotation, args.limit, args.seed
        )
        print(f"wrote {len(paths)} batches to {args.out}")
    else:
        print(json.dumps(collect(args.run_dir, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
