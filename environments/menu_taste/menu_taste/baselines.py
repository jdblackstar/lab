"""Baselines with no taste, to check what the missing-course task actually measures.

Each baseline scores the options of a question with cues that need no taste: shared
words with the menu, description length, writing style, how common a dish is, words tied
to the menu's stated season, the one option whose dietary tags differ from the rest, and
how often the caterer serves each option with the dishes shown. If any of them,
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

from .cloze import (
    ELIGIBLE_KINDS,
    ClozeQuestion,
    cloze_questions,
    dish_tokens,
    same_dish,
)
from .corpus import load_menus
from .schema import Item, Menu, Season

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


# Ingredients a menu writer reaches for in each season. Matching the menu's stated
# season by vocabulary alone takes no judgment of how the menu fits together.
SEASON_WORDS = {
    Season.spring: words(
        "asparagus ramp ramps pea peas fava morel morels rhubarb radish radishes "
        "artichoke artichokes strawberry strawberries nettle fiddlehead chervil "
        "elderflower spring"
    ),
    Season.summer: words(
        "tomato tomatoes heirloom corn peach peaches watermelon melon zucchini "
        "cucumber cucumbers berry berries blueberry blueberries blackberry raspberry "
        "cherry cherries basil gazpacho nectarine apricot okra eggplant plum plums summer"
    ),
    Season.fall: words(
        "squash pumpkin apple apples cider sage pear pears fig figs mushroom mushrooms "
        "chestnut cranberry butternut delicata quince persimmon maple pecan brussels "
        "grapes autumn harvest"
    ),
    Season.winter: words(
        "citrus parsnip parsnips celery root turnip cabbage kale beet beets pomegranate "
        "chestnut chestnuts cranberry peppermint gingerbread truffle venison juniper "
        "mulled winter"
    ),
}


def infer_season(shown_words: set[str]) -> Season:
    """The season the shown dishes point to: at least two of its words, and more than
    any other season has. Otherwise unknown."""
    hits = {season: len(shown_words & ws) for season, ws in SEASON_WORDS.items()}
    best = max(hits.values())
    top = [season for season, n in hits.items() if n == best]
    return top[0] if best >= 2 and len(top) == 1 else Season.unknown


def season_pick(season: Season, option_words: list[set[str]]) -> int | None:
    """The one option with words of ``season``, or None when no single option has any."""
    hits = [
        i for i, w in enumerate(option_words) if w & SEASON_WORDS.get(season, set())
    ]
    return hits[0] if len(hits) == 1 else None


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
    season_words: set[str]
    inferred_season_words: set[str]
    shown: list[frozenset[str]]
    held_out: frozenset[str]


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
    shown_words = set().union(*(item_words(i) for i in items)) if items else set()
    return Context(
        items=items,
        section_items=section_items,
        words=shown_words,
        section_words=set().union(*(item_words(i) for i in section_items))
        if section_items
        else set(),
        desc_len=sum(len(i.description or "") for i in items) / n,
        name_len=sum(len(i.name.split()) for i in items) / n,
        has_desc=sum(bool(i.description) for i in items) / n,
        has_tags=sum(bool(i.dietary) for i in items) / n,
        capitals=sum(_capital_share(i.name) for i in items) / n,
        season_words=SEASON_WORDS.get(q.menu.event.season, set()),
        inferred_season_words=SEASON_WORDS.get(infer_season(shown_words), set()),
        shown=[dish_tokens(i.name) for i in items],
        held_out=frozenset(q.related_menu_ids or (q.menu.menu_id,)),
    )


def dish_popularity(menus: list[Menu]) -> Callable[[Item], float]:
    """How many menus serve a dish (log scale). Models never see this; it checks
    whether the way wrong options are drawn favors common or rare dishes."""
    counts: Counter = Counter()
    for menu in menus:
        for tokens in {dish_tokens(i.name) for i in menu.items()}:
            counts[tokens] += 1
    return lambda item: math.log1p(counts.get(dish_tokens(item.name), 0))


def dish_cooccurrence(menus: list[Menu]) -> Callable[[Item, Context], list[float]]:
    """How often the caterer serves a dish on menus with the dishes shown, counting
    only menus outside the question's own family (the target menu and its versions).

    Returns [log of the number of (menu, shown dish) pairs, share of the shown dishes
    found on the dish's other menus]. Models never see the corpus; this checks whether
    the corpus's own pairing habits give the answer away."""
    eligible = [m for m in menus if m.kind in ELIGIBLE_KINDS]
    index = {m.menu_id: i for i, m in enumerate(eligible)}
    exact: defaultdict[frozenset[str], set[int]] = defaultdict(set)
    by_word: defaultdict[str, set[frozenset[str]]] = defaultdict(set)
    for i, menu in enumerate(eligible):
        for tokens in {dish_tokens(it.name) for it in menu.items()}:
            exact[tokens].add(i)
            for w in tokens:
                by_word[w].add(tokens)
    cache: dict[frozenset[str], set[int]] = {}

    def serving(tokens: frozenset[str]) -> set[int]:
        """Menus serving this dish or one the question builder counts as the same."""
        if tokens not in cache:
            similar = set().union(*(by_word[w] for w in tokens)) if tokens else set()
            cache[tokens] = set().union(
                *(exact[u] for u in similar if same_dish(tokens, u))
            )
        return cache[tokens]

    def score(item: Item, ctx: Context) -> list[float]:
        held = {index[m] for m in ctx.held_out if m in index}
        mine = serving(dish_tokens(item.name)) - held
        hits = sum(len(mine & serving(t)) for t in ctx.shown)
        share = hits / (len(mine) * len(ctx.shown)) if mine and ctx.shown else 0.0
        return [math.log1p(hits), share]

    return score


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
    "season_words",
    "inferred_season_words",
    "tag_set_shared",
    "cooccurrence",
    "cooccurrence_share",
]


def features(
    item: Item,
    options: tuple[Item, ...],
    ctx: Context,
    popularity: Callable[[Item], float],
    cooccurrence: Callable[[Item, Context], list[float]],
) -> list[float]:
    w = item_words(item)
    tags = frozenset(item.dietary)
    same_tags = sum(frozenset(o.dietary) == tags for o in options) - 1
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
        len(w & ctx.season_words),
        len(w & ctx.inferred_season_words),
        same_tags / max(len(options) - 1, 1),
        *cooccurrence(item, ctx),
    ]


def feature_tensor(questions: list[ClozeQuestion], menus: list[Menu]) -> np.ndarray:
    pop, cooc = dish_popularity(menus), dish_cooccurrence(menus)
    out = []
    for q in questions:
        ctx = context(q)
        out.append([features(item, q.options, ctx, pop, cooc) for item in q.options])
    return np.asarray(out, dtype=float)


INFERRED_SEASON_RULE = "most words tied to the season the shown dishes suggest"

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
    ("most words tied to the menu's stated season", "season_words", max),
    (INFERRED_SEASON_RULE, "inferred_season_words", max),
    ("only option whose dietary tags differ", "tag_set_shared", min),
    ("most often served with the shown dishes", "cooccurrence", max),
    ("largest share of the shown dishes on its other menus", "cooccurrence_share", max),
]


def applicable(questions: list[ClozeQuestion], X: np.ndarray) -> dict[str, np.ndarray]:
    """Rules that only make sense on some questions; the rest are left unanswered."""
    shared = X[:, :, FEATURES.index("tag_set_shared")]
    return {
        "most words tied to the menu's stated season": np.array(
            [q.menu.event.season is not Season.unknown for q in questions], dtype=bool
        ),
        INFERRED_SEASON_RULE: np.array(
            [infer_season(context(q).words) is not Season.unknown for q in questions],
            dtype=bool,
        ),
        # Three wrong options share one tag set and the fourth option has another.
        "only option whose dietary tags differ": np.array(
            [
                X.shape[1] > 2
                and sorted(row)[0] == 0
                and np.allclose(sorted(row)[1:], (X.shape[1] - 2) / (X.shape[1] - 1))
                for row in shared
            ],
            dtype=bool,
        ),
    }


def _pick(values: np.ndarray, best, rng: random.Random) -> int:
    target = best(values)
    ties = [i for i, v in enumerate(values) if math.isclose(v, target)]
    return rng.choice(ties)


def rule_predictions(
    X: np.ndarray, seed: int = 0, only: dict[str, np.ndarray] | None = None
) -> dict[str, np.ndarray]:
    """The option each rule picks, or -1 where ``only`` says the rule does not apply."""
    rng = random.Random(seed)
    only = only or {}
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
        if name in only:
            preds[name][~only[name]] = -1
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


def _scored(pred: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Hits on the questions a baseline answered."""
    return (pred == y)[pred >= 0]


def _all_predictions(questions, menus, seed):
    X = feature_tensor(questions, menus)
    y = np.array([q.answer_index for q in questions])
    preds = rule_predictions(X, seed, applicable(questions, X))
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
    out = {}
    for name, pred in preds.items():
        hits = _scored(pred, y)
        if not len(hits):
            continue
        p, lo, hi = interval(hits)
        out[name] = {"accuracy": round(p, 4), "low": round(lo, 4), "high": round(hi, 4)}
        if len(hits) < len(y):
            out[name]["questions"] = len(hits)
    return out


def report(questions: list[ClozeQuestion], menus: list[Menu], seed: int = 0) -> str:
    X, y, preds, weights = _all_predictions(questions, menus, seed)
    combo = preds.get(BEST)
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
        hits = _scored(pred, y)
        if len(hits) < len(y):
            name = f"{name} (on the {len(hits)} questions it applies to)"
        if not len(hits):
            lines.append(f"| {name} | – | – |")
            continue
        p, lo, hi = interval(hits)
        lines.append(f"| {name} | {p:.1%} | {lo:.1%}–{hi:.1%} |")
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
