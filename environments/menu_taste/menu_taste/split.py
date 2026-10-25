"""Build a question set as separate train and eval files, split by menu family.

A model trained on one caterer's menus can learn which of its dishes go together
without learning anything about composition. The split keeps that memory from
counting as skill on the eval set:

- **Family-disjoint.** Menus that are versions of each other (``related_menu_ids``,
  joined transitively) all go to one side, so no eval menu, or a version of it, is
  ever a training question or a source of training options.
- **Unseen eval dishes.** Each side is built from its own menus only, so wrong options
  never cross over. An eval question is dropped if any of its options, the hidden
  dish or a wrong one, appears in training text (a menu or an option list): the same
  dish served on menus of both sides. Checking every option, not just the answer,
  keeps "pick the dish I never saw in training" from becoming a shortcut.

Splitting an already-built set can't give the second guarantee: wrong options are
drawn from the whole corpus, so most training questions would show some eval answer.
Building per side can, at the cost of new eval questions (not a subset of an
unsplit set's).

The overlap check is the one ``make_batches`` uses: a dish's name, lowercased with
whitespace collapsed, as a substring of the training text. It catches the same dish
under a longer name ("Plum Tart" in "Brown Butter Plum Tart"), not a renamed one.

    menu-taste-questions build private/menus.jsonl -o private/questions-v2.jsonl \
        --eval-fraction 0.2
    # -> private/questions-v2-train.jsonl, private/questions-v2-eval.jsonl (+ .meta.json)
"""

from __future__ import annotations

import datetime
import hashlib
import random
from pathlib import Path

from .cloze import ClozeQuestion, cloze_questions
from .corpus import load_menus
from .questions import FORMAT_VERSION, _norm, record, write_question_set
from .schema import Menu


def menu_families(records: list[dict]) -> dict[str, str]:
    """Each menu id -> a representative id of its family (connected components)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for rec in records:
        root = find(rec["info"]["menu_id"])
        for other in rec["related_menu_ids"]:
            parent[find(other)] = root
    return {m: find(m) for m in list(parent)}


def eval_menu_ids(
    records: list[dict], eval_fraction: float, seed: int
) -> tuple[set[str], int]:
    """Menus of whole families, in seeded order, until they hold ``eval_fraction``
    of the questions; and the question count of the largest family."""
    if not 0 < eval_fraction < 1:
        raise ValueError("eval_fraction must be between 0 and 1")
    family = menu_families(records)
    members: dict[str, set[str]] = {}
    for menu_id, fam in family.items():
        members.setdefault(fam, set()).add(menu_id)
    count: dict[str, int] = {}
    for rec in records:
        fam = family[rec["info"]["menu_id"]]
        count[fam] = count.get(fam, 0) + 1
    order = sorted(count)
    random.Random(f"{seed}:split").shuffle(order)
    chosen: set[str] = set()
    n = 0
    for fam in order:
        if n >= eval_fraction * len(records):
            break
        chosen |= members[fam]
        n += count[fam]
    return chosen, max(count.values(), default=0)


def unseen_in(train: list[dict], held: list[dict]) -> list[dict]:
    """The ``held`` questions none of whose options appears in ``train``'s text."""
    text = "\0".join(
        _norm(r["menu_text"] + "\n" + "\n".join(r["options"])) for r in train
    )
    return [r for r in held if not any(_norm(o) in text for o in r["info"]["options"])]


def _meta(
    questions: list[ClozeQuestion], records: list[dict], menus: list[Menu], seed: int
) -> dict:
    from .baselines import report_numbers

    return {
        "questions": len(records),
        "menus_shown": len({r["info"]["menu_id"] for r in records}),
        "num_options": len(records[0]["options"]) if records else 0,
        "baselines": report_numbers(questions, menus, seed=seed),
    }


def build_split(corpus: str, out: str, eval_fraction: float, **params) -> dict:
    """Write ``<stem>-train.jsonl`` and ``<stem>-eval.jsonl`` for ``out``, each with
    a ``.meta.json`` recording the split. Takes ``cloze_questions`` arguments."""
    menus = load_menus(corpus)
    seed = params.get("seed", 0)
    held_ids, largest = eval_menu_ids(
        [record(q) for q in cloze_questions(menus, **params)], eval_fraction, seed
    )
    sides = {
        "train": [m for m in menus if m.menu_id not in held_ids],
        "eval": [m for m in menus if m.menu_id in held_ids],
    }
    questions = {k: cloze_questions(v, **params) for k, v in sides.items()}
    records = {k: [record(q) for q in v] for k, v in questions.items()}
    kept = unseen_in(records["train"], records["eval"])
    dropped = len(records["eval"]) - len(kept)
    records["eval"] = kept
    kept_ids = {r["id"] for r in kept}
    questions["eval"] = [q for q in questions["eval"] if record(q)["id"] in kept_ids]
    if not records["train"] or not records["eval"]:
        raise ValueError(
            f"split left {len(records['train'])} train and {len(records['eval'])} "
            "eval questions; the corpus needs more unrelated menus"
        )

    path = Path(out)
    split = {
        "eval_fraction": eval_fraction,
        "seed": seed,
        # Versions chain (A~B, B~C), so one family can grow large; if it holds most
        # questions, the split can't be balanced.
        "largest_family_questions": largest,
        "train_menus": len(sides["train"]),
        "eval_menus": len(sides["eval"]),
        "train_questions": len(records["train"]),
        "eval_questions": len(records["eval"]),
        "eval_dropped_dish_seen_in_train": dropped,
        "guarantees": [
            "no menu family (versions of one menu) is on both sides; each side's "
            "wrong options come from its own menus",
            "no option of an eval question appears in any training menu or option",
        ],
    }
    common = {
        "format_version": FORMAT_VERSION,
        "created": datetime.date.today().isoformat(),
        "corpus_sha256": hashlib.sha256(Path(corpus).read_bytes()).hexdigest(),
        "corpus_menus": len(menus),
        "params": {k: v for k, v in params.items() if k != "courses"},
    }
    written = {}
    for part in ("train", "eval"):
        part_path = path.with_name(f"{path.stem}-{part}{path.suffix}")
        meta = {
            **common,
            **_meta(questions[part], records[part], sides[part], seed),
            "split": {"part": part, **split},
        }
        write_question_set(part_path, records[part], meta)
        written[part] = str(part_path)
    return {**written, **split}
