"""Train/eval question sets split by menu family. All menus invented."""

import json
import string
from itertools import product

import pytest
from menu_taste.cloze import dish_tokens
from menu_taste.questions import _norm, load_question_set, main
from menu_taste.schema import Menu
from menu_taste.split import build_split
from menu_taste.taskset import MenuTasteConfig, MenuTasteTaskset

# Two-letter codes that survive dish_tokens (not stopwords, no trailing s to stem),
# so dishes are distinct and no dish name is a substring of another's.
CODES = [
    c
    for c in map("".join, product(string.ascii_lowercase, repeat=2))
    if dish_tokens(c) == {c}
]
SHARED = "Quince Tart"


def _menu(menu_id, mains, desserts):
    return {
        "menu_id": menu_id,
        "kind": "event",
        "service": "plated",
        "sections": [
            {"course": "main", "items": [{"name": n} for n in mains]},
            {"course": "dessert", "items": [{"name": n} for n in desserts]},
        ],
    }


def _corpus(path):
    codes = iter(CODES)
    menus = []
    for i in range(20):
        mains = [f"Roast {next(codes)}" for _ in range(4)]
        desserts = [f"Cake {next(codes)}"]
        if i % 3 == 0:
            desserts.append(SHARED)  # one dish served on menus of both sides
        menus.append(_menu(f"m{i:02d}", mains, desserts))
        if i % 4 == 0:  # a revision: same mains, a new dessert
            menus.append(_menu(f"m{i:02d}-rev", mains, [f"Cake {next(codes)}"]))
    for m in menus:
        Menu.model_validate(m)
    path.write_text("".join(json.dumps(m) + "\n" for m in menus))
    return path


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    return _corpus(tmp_path_factory.mktemp("c") / "menus.jsonl")


def _family(menu_id):
    return menu_id.removesuffix("-rev")


@pytest.mark.parametrize("seed", range(8))
def test_split_is_family_disjoint_and_eval_dishes_are_unseen(corpus, tmp_path, seed):
    out = build_split(str(corpus), str(tmp_path / "q.jsonl"), 0.3, seed=seed)
    train = load_question_set(out["train"])
    eval_ = load_question_set(out["eval"])
    assert train and eval_

    # Every menu a question shows or draws an option from stays on one side, and
    # versions of a menu (m04 and m04-rev) stay with it.
    sides = {}
    for part, rows in (("train", train), ("eval", eval_)):
        for r in rows:
            ids = [r["info"]["menu_id"], *r["info"]["distractor_menu_ids"]]
            for menu_id in ids + r["related_menu_ids"]:
                assert sides.setdefault(_family(menu_id), part) == part, menu_id

    train_text = [_norm(r["menu_text"]) for r in train] + [
        _norm(o) for r in train for o in r["options"]
    ]
    for r in eval_:
        for option in r["info"]["options"]:
            assert not any(_norm(option) in t for t in train_text), option


def test_eval_questions_showing_a_dish_trained_on_are_dropped(corpus, tmp_path):
    dropped = []
    for seed in range(8):
        out = build_split(str(corpus), str(tmp_path / f"q{seed}.jsonl"), 0.3, seed=seed)
        dropped.append(out["eval_dropped_dish_seen_in_train"])
        train = load_question_set(out["train"])
        if any(SHARED in r["menu_text"] for r in train):
            for r in load_question_set(out["eval"]):
                assert SHARED not in r["info"]["options"]
    # The shared dessert lands on both sides for some seeds, and costs eval questions.
    assert any(dropped)


def test_build_with_eval_fraction_writes_halves_the_taskset_loads(corpus, tmp_path):
    out = tmp_path / "questions.jsonl"
    assert main(["build", str(corpus), "-o", str(out), "--eval-fraction", "0.3"]) == 0
    assert not out.exists()

    halves = {}
    for part in ("train", "eval"):
        path = tmp_path / f"questions-{part}.jsonl"
        meta = json.loads((tmp_path / f"questions-{part}.meta.json").read_text())
        assert meta["split"]["part"] == part
        assert meta["questions"] == len(load_question_set(path))
        assert meta["split"][f"{part}_questions"] == meta["questions"]
        assert "best combination of all cues (held-out menus)" in meta["baselines"]
        tasks = list(
            MenuTasteTaskset(MenuTasteConfig(id="menu-taste", questions_path=str(path)))
        )
        halves[part] = {_family(t.data.menu_id) for t in tasks}
    assert not halves["train"] & halves["eval"]
