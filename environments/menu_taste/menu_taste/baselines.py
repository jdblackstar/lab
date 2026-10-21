"""Baselines with no taste, to check what the missing-course task actually measures.

Each baseline scores the options of a question with surface cues only: shared words
with the menu, description length, writing style, how common a dish is. If any of them,
or a model trained to combine all of them, beats chance by a wide margin, then the
questions can be answered without judging how a menu fits together, and the task needs
fixing before model scores mean anything.

    menu-taste-baselines private/menus.jsonl
    menu-taste-baselines private/menus.jsonl --max-menus 150 --max-per-menu 2

Runs locally; nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .cloze import ClozeQuestion, cloze_questions, dish_tokens
from .corpus import load_menus
from .schema import Item, Menu

_STOP = frozenset(
    [
        "and",
        "with",
        "the",
        "of",
        "in",
        "on",
        "for",
        "a",
        "an",
        "or",
        "to",
        "served",
        "house",
        "made",
        "our",
        "fresh",
        "seasonal",
    ]
)


def words(text: str | None) -> set[str]:
    return {
        w.rstrip("s")
        for w in re.findall(r"[a-z]{3,}", (text or "").lower())
        if w not in _STOP
    }


def item_words(item: Item) -> set[str]:
    return words(item.name) | words(item.description)


def _capital_share(name: str) -> float:
    tokens = re.findall(r"[A-Za-z]+", name)
    return sum(t[0].isupper() for t in tokens) / len(tokens) if tokens else 0.0


@dataclass
class Context:
    """What a question shows besides the options: the menu with one dish removed."""

    items: list[Item]
    section_items: list[Item]
    words: set[str]
    section_words: set[str]
    desc_len: float
    name_len: float
    has_desc: float
    has_tags: float
    capitals: float


def context(q: ClozeQuestion) -> Context:
    items, section_items = [], []
    for s_idx, section in enumerate(q.menu.sections):
        for i_idx, item in enumerate(section.items):
            if (s_idx, i_idx) == (q.section_idx, q.item_idx):
                continue
            items.append(item)
            if s_idx == q.section_idx:
                section_items.append(item)
    n = max(len(items), 1)
    return Context(
        items=items,
        section_items=section_items,
        words=set().union(*(item_words(i) for i in items)) if items else set(),
        section_words=set().union(*(item_words(i) for i in section_items))
        if section_items
        else set(),
        desc_len=sum(len(i.description or "") for i in items) / n,
        name_len=sum(len(i.name.split()) for i in items) / n,
        has_desc=sum(bool(i.description) for i in items) / n,
        has_tags=sum(bool(i.dietary) for i in items) / n,
        capitals=sum(_capital_share(i.name) for i in items) / n,
    )


def dish_popularity(menus: list[Menu]) -> Callable[[Item], float]:
    """How many menus serve a dish (log scale). Models never see this; it checks
    whether the way wrong options are drawn favors common or rare dishes."""
    counts: Counter = Counter()
    for menu in menus:
        for tokens in {dish_tokens(i.name) for i in menu.items()}:
            counts[tokens] += 1
    return lambda item: math.log1p(counts.get(dish_tokens(item.name), 0))


FEATURES = [
    "menu_overlap",
    "menu_overlap_share",
    "section_overlap",
    "desc_len_gap",
    "name_len_gap",
    "desc_style_match",
    "tag_style_match",
    "capitals_gap",
    "popularity",
]


def features(
    item: Item, ctx: Context, popularity: Callable[[Item], float]
) -> list[float]:
    w = item_words(item)
    overlap = len(w & ctx.words)
    return [
        overlap,
        overlap / len(w) if w else 0.0,
        len(w & ctx.section_words),
        abs(len(item.description or "") - ctx.desc_len) / 100,
        abs(len(item.name.split()) - ctx.name_len),
        1 - abs(bool(item.description) - ctx.has_desc),
        1 - abs(bool(item.dietary) - ctx.has_tags),
        abs(_capital_share(item.name) - ctx.capitals),
        popularity(item),
    ]


def feature_tensor(questions: list[ClozeQuestion], menus: list[Menu]) -> np.ndarray:
    pop = dish_popularity(menus)
    out = []
    for q in questions:
        ctx = context(q)
        out.append([features(item, ctx, pop) for item in q.options])
    return np.asarray(out, dtype=float)


# Single-cue rules: (name, feature, pick the highest or lowest value)
RULES = [
    ("most words shared with the menu", "menu_overlap", max),
    ("fewest words shared with the menu", "menu_overlap", min),
    ("most words shared with its own section", "section_overlap", max),
    ("description length closest to the menu's", "desc_len_gap", min),
    ("dish-name length closest to the menu's", "name_len_gap", min),
    ("description and tag style match the menu", "style", max),
    ("capitalization closest to the menu's", "capitals_gap", min),
    ("most common dish in the corpus", "popularity", max),
    ("least common dish in the corpus", "popularity", min),
]


def _pick(values: np.ndarray, best, rng: random.Random) -> int:
    target = best(values)
    ties = [i for i, v in enumerate(values) if math.isclose(v, target)]
    return rng.choice(ties)


def rule_predictions(X: np.ndarray, seed: int = 0) -> dict[str, np.ndarray]:
    rng = random.Random(seed)
    idx = {f: i for i, f in enumerate(FEATURES)}
    preds = {
        "random guess": np.array([rng.randrange(X.shape[1]) for _ in range(len(X))])
    }
    preds["always the first option"] = np.zeros(len(X), dtype=int)
    for name, feat, best in RULES:
        if feat == "style":
            col = X[:, :, idx["desc_style_match"]] + X[:, :, idx["tag_style_match"]]
        else:
            col = X[:, :, idx[feat]]
        preds[name] = np.array([_pick(row, best, rng) for row in col])
    return preds


def fit_choice_model(X: np.ndarray, y: np.ndarray, l2: float = 1e-2, steps: int = 400):
    """Conditional logit: softmax over each question's options of a linear score."""
    mean = X.reshape(-1, X.shape[-1]).mean(0)
    std = X.reshape(-1, X.shape[-1]).std(0) + 1e-9
    Z = (X - mean) / std
    w = np.zeros(X.shape[-1])
    for _ in range(steps):
        logits = Z @ w
        logits -= logits.max(1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(1, keepdims=True)
        chosen = Z[np.arange(len(y)), y]
        expected = (p[..., None] * Z).sum(1)
        grad = -(chosen - expected).mean(0) + l2 * w
        w -= 0.5 * grad
    return lambda Xn: ((Xn - mean) / std) @ w, w / std


def cross_validated_choice_model(
    X: np.ndarray, y: np.ndarray, groups: list[str], folds: int = 5, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Predictions where every question's menu was held out of training."""
    unique = sorted(set(groups))
    random.Random(seed).shuffle(unique)
    fold_of = {g: i % folds for i, g in enumerate(unique)}
    pred = np.zeros(len(y), dtype=int)
    for k in range(folds):
        test = np.array([fold_of[g] == k for g in groups])
        if test.all() or not test.any():
            continue
        score, _ = fit_choice_model(X[~test], y[~test])
        pred[test] = score(X[test]).argmax(1)
    _, weights = fit_choice_model(X, y)
    return pred, weights


def interval(correct: np.ndarray) -> tuple[float, float, float]:
    """Accuracy with a 95% Wilson interval."""
    n = len(correct)
    p = correct.mean() if n else 0.0
    z = 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, centre - half, centre + half


def _all_predictions(questions, menus, seed):
    X = feature_tensor(questions, menus)
    y = np.array([q.answer_index for q in questions])
    preds = rule_predictions(X, seed)
    combo, weights = cross_validated_choice_model(
        X, y, [q.menu.menu_id for q in questions], seed=seed
    )
    preds[BEST] = combo
    return X, y, preds, weights


BEST = "best combination of all cues (held-out menus)"


def report_numbers(
    questions: list[ClozeQuestion], menus: list[Menu], seed: int = 0
) -> dict[str, dict[str, float]]:
    """Accuracy and 95% interval of every baseline, for storing with a question set."""
    if not questions:
        return {}
    _, y, preds, _ = _all_predictions(questions, menus, seed)
    out = {}
    for name, pred in preds.items():
        p, lo, hi = interval(pred == y)
        out[name] = {"accuracy": round(p, 4), "low": round(lo, 4), "high": round(hi, 4)}
    return out


def report(questions: list[ClozeQuestion], menus: list[Menu], seed: int = 0) -> str:
    X, y, preds, weights = _all_predictions(questions, menus, seed)
    combo = preds[BEST]
    k = X.shape[1]
    lines = [
        (
            f"{len(questions)} questions from {len({q.menu.menu_id for q in questions})} "
            f"menus, {k} options each (chance = {1 / k:.0%})"
        ),
        "",
        "| Baseline | Accuracy | 95% interval |",
        "| --- | --- | --- |",
    ]
    for name, pred in preds.items():
        p, lo, hi = interval(pred == y)
        lines.append(f"| {name} | {p:.1%} | {lo:.1%}–{hi:.1%} |")

    lines += [
        "",
        "Combination by course:",
        "",
        "| Course | Questions | Accuracy |",
        "| --- | --- | --- |",
    ]
    by_course = defaultdict(list)
    for i, q in enumerate(questions):
        by_course[q.course.value].append(combo[i] == y[i])
    for course, hits in sorted(by_course.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {course} | {len(hits)} | {np.mean(hits):.1%} |")

    lines += ["", "What the combination leans on (weight per standard deviation):", ""]
    std = X.reshape(-1, k and X.shape[-1]).std(0)
    for name, w, s in sorted(
        zip(FEATURES, weights, std), key=lambda t: -abs(t[1] * t[2])
    ):
        lines.append(f"- {name}: {w * s:+.2f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="menu-taste-baselines",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("corpus")
    parser.add_argument("--num-options", type=int, default=4)
    parser.add_argument("--max-menus", type=int, default=None)
    parser.add_argument("--max-per-menu", type=int, default=None)
    parser.add_argument("--max-per-dish", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--no-surface-matching",
        action="store_true",
        help="Draw wrong options without matching the answer's surface (measures the leak)",
    )
    args = parser.parse_args(argv)
    menus = load_menus(args.corpus)
    questions = cloze_questions(
        menus,
        num_options=args.num_options,
        max_menus=args.max_menus,
        max_per_menu=args.max_per_menu,
        max_per_dish=args.max_per_dish if args.max_per_dish > 0 else None,
        match_surface=not args.no_surface_matching,
        seed=args.seed,
    )
    print(report(questions, menus, seed=args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
