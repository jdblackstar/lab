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


L2_GRID = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)
"""Ridge penalties (on standardized features) the combination chooses from. The cues
are weak and a few hundred questions are few, so a fixed small penalty overfits: on
the 93-question sample, l2=0.01 scored 36% on its training menus, 25% on held-out ones,
with a held-out log loss worse than guessing uniformly."""


def _log_softmax(logits: np.ndarray) -> np.ndarray:
    logits = logits - logits.max(1, keepdims=True)
    return logits - np.log(np.exp(logits).sum(1, keepdims=True))


def fit_choice_model(X: np.ndarray, y: np.ndarray, l2: float = 0.1):
    """Conditional logit: softmax over each question's options of a linear score.

    The penalized log likelihood is concave with a handful of weights, so Newton's
    method solves it exactly in a few steps, with no learning rate or step count to
    tune (a fixed-rate gradient descent diverges once ``l2`` is large)."""
    mean = X.reshape(-1, X.shape[-1]).mean(0)
    std = X.reshape(-1, X.shape[-1]).std(0) + 1e-9
    Z = (X - mean) / std
    rows = np.arange(len(y))
    w = np.zeros(X.shape[-1])
    for _ in range(50):
        p = np.exp(_log_softmax(Z @ w))
        expected = np.einsum("qk,qkf->qf", p, Z)
        grad = -(Z[rows, y] - expected).mean(0) + l2 * w
        second = np.einsum("qk,qkf,qkg->fg", p, Z, Z) / len(y)
        hessian = second - expected.T @ expected / len(y) + l2 * np.eye(len(w))
        step = np.linalg.solve(hessian, grad)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return lambda Xn: ((Xn - mean) / std) @ w, w / std


def _menu_folds(groups: list[str], folds: int, seed: int) -> list[np.ndarray]:
    """Test masks that hold out whole menus."""
    unique = sorted(set(groups))
    random.Random(seed).shuffle(unique)
    fold_of = {g: i % folds for i, g in enumerate(unique)}
    masks = [np.array([fold_of[g] == k for g in groups]) for k in range(folds)]
    return [m for m in masks if m.any() and not m.all()]


def choose_l2(
    X: np.ndarray, y: np.ndarray, groups: list[str], folds: int = 4, seed: int = 0
) -> float:
    """The penalty in ``L2_GRID`` with the best held-out-menu log likelihood."""
    masks = _menu_folds(groups, folds, seed)
    if not masks:
        return max(L2_GRID)

    def held_out_loss(l2: float) -> float:
        loss = 0.0
        for test in masks:
            score, _ = fit_choice_model(X[~test], y[~test], l2)
            lp = _log_softmax(score(X[test]))
            loss -= lp[np.arange(test.sum()), y[test]].sum()
        return loss

    return min(L2_GRID, key=held_out_loss)


def cross_validated_choice_model(
    X: np.ndarray, y: np.ndarray, groups: list[str], folds: int = 5, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Predictions where every question's menu was held out of training, including
    out of the choice of penalty (chosen again inside each training split)."""
    pred = np.zeros(len(y), dtype=int)
    for test in _menu_folds(groups, folds, seed):
        train_groups = [g for g, t in zip(groups, test) if not t]
        l2 = choose_l2(X[~test], y[~test], train_groups, seed=seed)
        score, _ = fit_choice_model(X[~test], y[~test], l2)
        pred[test] = score(X[test]).argmax(1)
    _, weights = fit_choice_model(X, y, choose_l2(X, y, groups, seed=seed))
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
    groups = [q.menu.menu_id for q in questions]
    if len(set(groups)) > 1:
        preds[BEST], weights = cross_validated_choice_model(X, y, groups, seed=seed)
    else:  # with one menu there is nothing to hold out, so no honest score exists
        _, weights = fit_choice_model(X, y)
    return X, y, preds, weights


BEST = "best combination of all cues (held-out menus)"


def report_numbers(
    questions: list[ClozeQuestion], menus: list[Menu], seed: int = 0
) -> dict[str, dict[str, float]]:
    """Accuracy and 95% interval of every baseline, for storing with a question set."""
    if not questions:
        return {}
    _, y, preds, _ = _all_predictions(questions, menus, seed)
    return _numbers(y, preds)


def _numbers(
    y: np.ndarray, preds: dict[str, np.ndarray]
) -> dict[str, dict[str, float]]:
    out = {}
    for name, pred in preds.items():
        p, lo, hi = interval(pred == y)
        out[name] = {"accuracy": round(p, 4), "low": round(lo, 4), "high": round(hi, 4)}
    return out


def bar(numbers: dict[str, dict[str, float]]) -> list[str]:
    """The baselines a model has to beat, highest first: the best single cue and the
    held-out combination. Neither alone is the bar. With few questions the combination
    can't learn its weights and lands below the best cue (on the bundled sample, 26% vs
    31%); with many it can find what single cues miss. The best cue is picked after
    scoring every cue on these same questions, so it leans high, which is the safe
    direction for a bar."""
    singles = [name for name, _, _ in RULES if name in numbers]
    rows = [max(singles, key=lambda n: numbers[n]["accuracy"])] if singles else []
    rows += [BEST] if BEST in numbers else []
    return sorted(rows, key=lambda n: -numbers[n]["accuracy"])


def report(questions: list[ClozeQuestion], menus: list[Menu], seed: int = 0) -> str:
    X, y, preds, weights = _all_predictions(questions, menus, seed)
    combo = preds.get(BEST)
    k = X.shape[1]
    numbers = _numbers(y, preds)
    top = bar(numbers)[0]
    lines = [
        (
            f"{len(questions)} questions from {len({q.menu.menu_id for q in questions})} "
            f"menus, {k} options each (chance = {1 / k:.0%})"
        ),
        "",
        (
            f"Bar to clear: {numbers[top]['accuracy']:.1%} ({top}), the higher of the "
            "best single cue and the held-out combination. The best cue is picked "
            "after scoring all of them on these questions, so it leans high."
        ),
        "",
        "| Baseline | Accuracy | 95% interval |",
        "| --- | --- | --- |",
    ]
    for name, n in numbers.items():
        lines.append(
            f"| {name} | {n['accuracy']:.1%} | {n['low']:.1%}–{n['high']:.1%} |"
        )
    if combo is None:
        lines.append(f"| {BEST} | unavailable: needs at least two menus | |")
    else:
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
