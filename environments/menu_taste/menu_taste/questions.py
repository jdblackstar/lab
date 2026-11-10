"""A frozen question set: built once from a corpus, then every run reads the same file.

Rebuilding questions from the corpus on every run means any parser fix changes the
questions, so scores from different days can't be compared, and every new seed shows
providers a different slice of the menus. A frozen file fixes both: the questions, and
which menus leave the machine, are known in advance.

    menu-taste-questions build private/menus.jsonl -o private/questions-v1.jsonl
    menu-taste-questions batches private/questions-v1.jsonl --out private/runs/haiku-r0

Each record holds the rendered menu and options separately, so the options can be
rotated (``rotation``) to measure position bias without changing the question.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import re
from pathlib import Path

from .cloze import (
    LETTERS,
    SYSTEM_PROMPT,
    ClozeQuestion,
    cloze_questions,
    format_question,
)
from .corpus import load_menus
from .render import render_item

FORMAT_VERSION = 1


def record(q: ClozeQuestion) -> dict:
    menu_text = q.menu_text()
    options = [render_item(item) for item in q.options]
    key = json.dumps([menu_text, options], ensure_ascii=False)
    return {
        "id": "q-" + hashlib.sha256(key.encode()).hexdigest()[:10],
        "menu_text": menu_text,
        "options": options,
        "answer_index": q.answer_index,
        "related_menu_ids": list(q.related_menu_ids),
        "info": q.info(),
    }


def rotate(rec: dict, rotation: int) -> tuple[list[str], int]:
    """Options shifted left by ``rotation``; the answer moves with them."""
    k = len(rec["options"])
    r = rotation % k
    return rec["options"][r:] + rec["options"][:r], (rec["answer_index"] - r) % k


def to_row(rec: dict, rotation: int = 0) -> dict:
    """The (question, answer, info) row the environment serves."""
    options, answer = rotate(rec, rotation)
    return {
        "question": format_question(rec["menu_text"], options),
        "answer": LETTERS[answer],
        "info": {**rec["info"], "id": rec["id"], "rotation": rotation},
    }


def write_question_set(path: str | Path, records: list[dict], meta: dict) -> None:
    path = Path(path)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    meta_path(path).write_text(json.dumps(meta, indent=2) + "\n")


def load_question_set(path: str | Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def meta_path(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(path.stem + ".meta.json")


def load_meta(path: str | Path) -> dict:
    p = meta_path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def build(corpus: str, out: str, **params) -> dict:
    from .baselines import report_numbers

    menus = load_menus(corpus)
    questions = cloze_questions(menus, **params)
    records = [record(q) for q in questions]
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("duplicate question ids")
    meta = {
        "format_version": FORMAT_VERSION,
        "created": datetime.date.today().isoformat(),
        "corpus_sha256": hashlib.sha256(Path(corpus).read_bytes()).hexdigest(),
        "corpus_menus": len(menus),
        "params": {k: v for k, v in params.items() if k != "courses"},
        "questions": len(records),
        "menus_shown": len({r["info"]["menu_id"] for r in records}),
        "num_options": len(records[0]["options"]) if records else 0,
        "baselines": report_numbers(questions, menus, seed=params.get("seed", 0)),
    }
    write_question_set(out, records, meta)
    return meta


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
        prog="menu-taste-questions",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Freeze a question set from a corpus")
    b.add_argument("corpus")
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--num-options", type=int, default=4)
    b.add_argument("--max-menus", type=int, default=None)
    b.add_argument("--max-per-menu", type=int, default=None)
    b.add_argument("--max-per-dish", type=int, default=2)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument(
        "--eval-fraction",
        type=float,
        default=None,
        help="Write <stem>-train and <stem>-eval split by menu family (see split.py)",
    )
    bt = sub.add_parser(
        "batches", help="Split a question set into batch files to answer"
    )
    bt.add_argument("questions")
    bt.add_argument("--out", required=True)
    bt.add_argument("--size", type=int, default=15)
    bt.add_argument("--rotation", type=int, default=0)
    bt.add_argument(
        "--limit", type=int, default=None, help="Seeded sample of N questions"
    )
    bt.add_argument("--seed", type=int, default=0)
    c = sub.add_parser("collect", help="Gather answers-NNN.md files into a run file")
    c.add_argument("run_dir")
    c.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "build":
        if args.eval_fraction is not None:
            from .split import build_split

            make, extra = build_split, {"eval_fraction": args.eval_fraction}
        else:
            make, extra = build, {}
        meta = make(
            args.corpus,
            args.out,
            **extra,
            num_options=args.num_options,
            max_menus=args.max_menus,
            max_per_menu=args.max_per_menu,
            max_per_dish=args.max_per_dish if args.max_per_dish > 0 else None,
            seed=args.seed,
        )
        print(json.dumps({k: v for k, v in meta.items() if k != "baselines"}, indent=2))
    elif args.cmd == "batches":
        paths = write_batches(
            args.questions, args.out, args.size, args.rotation, args.limit, args.seed
        )
        print(f"wrote {len(paths)} batches to {args.out}")
    else:
        print(json.dumps(collect(args.run_dir, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
