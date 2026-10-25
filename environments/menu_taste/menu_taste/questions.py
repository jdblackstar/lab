"""A frozen question set: built once from a corpus, then every run reads the same file.

Rebuilding questions from the corpus on every run means any parser fix changes the
questions, so scores from different days can't be compared, and every new seed shows
providers a different slice of the menus. A frozen file fixes both: the questions, and
which menus leave the machine, are known in advance.

    menu-taste-questions build private/menus.jsonl -o private/questions-v1.jsonl

Each record holds the rendered menu and options separately, so the options can be
rotated (``rotation``) to measure position bias without changing the question.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path

from .cloze import LETTERS, ClozeQuestion, cloze_questions, format_question
from .corpus import load_menus
from .render import render_item
from .schema import Course

FORMAT_VERSION = 1


def record(q: ClozeQuestion) -> dict:
    """The frozen form of a question; ``to_row`` turns it into a prompt."""
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
        "params": {
            **params,
            "courses": sorted(c.value for c in params["courses"])
            if params.get("courses")
            else None,
        },
        "questions": len(records),
        "menus_shown": len({r["info"]["menu_id"] for r in records}),
        "num_options": len(records[0]["options"]) if records else 0,
        "baselines": report_numbers(questions, menus, seed=params.get("seed", 0)),
    }
    write_question_set(out, records, meta)
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="menu-taste-questions",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Freeze a question set from a corpus")
    b.add_argument("corpus", help="JSONL corpus from menu-taste-ingest")
    b.add_argument("-o", "--out", required=True)
    b.add_argument(
        "--num-options",
        type=int,
        default=4,
        help="Choices per question, including the right one",
    )
    b.add_argument(
        "--courses",
        nargs="+",
        choices=[c.value for c in Course],
        default=None,
        metavar="COURSE",
        help="Courses to hide (schema.Course values); default: food courses",
    )
    b.add_argument(
        "--include-drinks",
        action="store_true",
        help="Also hide cocktails, wine, and other drinks",
    )
    b.add_argument("--max-per-menu", type=int, default=None)
    b.add_argument(
        "--min-menu-items",
        type=int,
        default=4,
        help="Don't ask about smaller menus (they still supply wrong options)",
    )
    b.add_argument(
        "--max-menus",
        type=int,
        default=None,
        help="Ask about a seeded sample of this many menus",
    )
    b.add_argument(
        "--max-per-dish",
        type=int,
        default=2,
        help="How many questions one dish can answer; 0 for no cap",
    )
    b.add_argument(
        "--match-surface",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Wrong options look like the answer (description, tags, popularity)",
    )
    b.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    meta = build(
        args.corpus,
        args.out,
        num_options=args.num_options,
        courses=frozenset(Course(c) for c in args.courses) if args.courses else None,
        include_drinks=args.include_drinks,
        max_per_menu=args.max_per_menu,
        min_menu_items=args.min_menu_items,
        max_menus=args.max_menus,
        max_per_dish=args.max_per_dish if args.max_per_dish > 0 else None,
        match_surface=args.match_surface,
        seed=args.seed,
    )
    print(json.dumps({k: v for k, v in meta.items() if k != "baselines"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
