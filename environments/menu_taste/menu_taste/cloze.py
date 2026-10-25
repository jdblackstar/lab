"""Missing-course task: hide one dish, offer it among dishes from other menus.

Distractors come from the same caterer and the same course (a missing dessert competes
with that caterer's other desserts), so every option reads like it was written by the
same kitchen. A corpus may pool several caterers (``Menu.caterer``); options never
cross between them.
What separates the real dish from the rest is how well it fits the menu around it.
"""

from __future__ import annotations

import math
import random
import re
import string
import unicodedata
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from .render import render_item, render_menu
from .schema import (
    DRINK_COURSES,
    Course,
    Item,
    ItemRole,
    Menu,
    MenuKind,
    SelectionMode,
)

DEFAULT_COURSES = frozenset(
    {
        Course.hors_doeuvres,
        Course.raw_bar,
        Course.display,
        Course.soup,
        Course.salad,
        Course.appetizer,
        Course.pasta,
        Course.intermezzo,
        Course.main,
        Course.side,
        Course.cheese,
        Course.dessert,
        Course.late_night,
    }
)
ELIGIBLE_KINDS = frozenset({MenuKind.event, MenuKind.sample})

# Two dish names this similar count as the same dish (token Jaccard).
SAME_DISH_THRESHOLD = 0.5
# Two menus sharing this fraction of dishes count as versions of one menu.
SAME_MENU_THRESHOLD = 0.5

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "the",
        "of",
        "with",
        "in",
        "on",
        "de",
        "du",
        "la",
        "le",
        "au",
        "aux",
        "et",
        "served",
        "house",
        "our",
        "fresh",
    ]
)
_PUNCT = str.maketrans({c: " " for c in string.punctuation + "–—’‘“”"})


def dish_tokens(name: str) -> frozenset[str]:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.sub(r"\s+", " ", text.lower().translate(_PUNCT)).split()
    return frozenset(w.rstrip("s") for w in words if w not in _STOPWORDS and len(w) > 1)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def same_dish(a: frozenset[str], b: frozenset[str]) -> bool:
    return jaccard(a, b) >= SAME_DISH_THRESHOLD


@dataclass(frozen=True)
class _Slot:
    menu_idx: int
    section_idx: int
    item_idx: int
    course: Course
    tokens: frozenset[str]


def _menu_families(token_sets: list[set[frozenset[str]]]) -> list[set[int]]:
    """For each menu, the indices of menus that are versions of it (including itself)."""
    families = [{i} for i in range(len(token_sets))]
    for i, j in combinations(range(len(token_sets)), 2):
        a, b = token_sets[i], token_sets[j]
        if not a or not b:
            continue
        shared = sum(1 for t in a if any(same_dish(t, u) for u in b))
        if shared / min(len(a), len(b)) >= SAME_MENU_THRESHOLD:
            families[i].add(j)
            families[j].add(i)
    return families


LETTERS = string.ascii_uppercase

SYSTEM_PROMPT = (
    "You are an experienced chef and caterer reviewing menus. Judge how well dishes "
    "fit together: balance, pacing, seasonality, and how the food is served."
)

INSTRUCTIONS = """One dish has been removed from this catered menu and replaced with {marker}. \
The options below are the removed dish plus dishes of the same course taken from other menus \
by {source}. Pick the dish that was removed: the one that fits this menu's balance, \
flavors, season, and service best.

<menu>
{menu}
</menu>

Options:
{options}

Reason briefly if useful, then give only the letter inside <answer></answer> tags."""


@dataclass(frozen=True)
class ClozeQuestion:
    """One question before formatting: a menu with one dish hidden, and the options."""

    menu: Menu
    section_idx: int
    item_idx: int
    options: tuple[Item, ...]
    option_menu_ids: tuple[str, ...]
    answer_index: int
    # Menus that are versions of this one (including itself).
    related_menu_ids: tuple[str, ...] = ()

    @property
    def target(self) -> Item:
        return self.options[self.answer_index]

    @property
    def course(self) -> Course:
        return self.menu.sections[self.section_idx].course

    def menu_text(self) -> str:
        return render_menu(self.menu, missing=(self.section_idx, self.item_idx))

    def to_row(self) -> dict:
        options = [render_item(item) for item in self.options]
        return {
            "question": format_question(self.menu_text(), options, self.menu.caterer),
            "answer": LETTERS[self.answer_index],
            "info": self.info(),
        }

    def info(self) -> dict:
        menu = self.menu
        return {
            "menu_id": menu.menu_id,
            "caterer": menu.caterer,
            "course": self.course.value,
            "service": menu.service.value,
            "section_service": (
                menu.sections[self.section_idx].service or menu.service
            ).value,
            "target": self.target.name,
            "options": [item.name for item in self.options],
            "distractor_menu_ids": [
                m for i, m in enumerate(self.option_menu_ids) if i != self.answer_index
            ],
        }


def format_question(
    menu_text: str, options: list[str], caterer: str | None = None
) -> str:
    """``caterer`` is the menu's label (``Menu.caterer``). Unlabeled menus count as
    one caterer and keep the original wording, so frozen v1 prompts don't change; in a
    labeled corpus, every option comes from this menu's own caterer."""
    return INSTRUCTIONS.format(
        marker="[MISSING DISH]",
        source="the same caterer" if caterer is None else "this menu's caterer",
        menu=menu_text,
        options="\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(options)),
    )


def build_cloze_items(menus: list[Menu], **kwargs) -> list[dict]:
    """Build multiple-choice rows (``question``, ``answer``, ``info``).

    Takes the same arguments as ``cloze_questions``.
    """
    return [q.to_row() for q in cloze_questions(menus, **kwargs)]


def cloze_questions(
    menus: list[Menu],
    *,
    num_options: int = 4,
    courses: frozenset[Course] | None = None,
    include_drinks: bool = False,
    max_per_menu: int | None = None,
    min_menu_items: int = 4,
    max_menus: int | None = None,
    max_per_dish: int | None = 2,
    match_surface: bool = True,
    seed: int = 0,
) -> list[ClozeQuestion]:
    """Pick hidden dishes and wrong options.

    ``min_menu_items``: menus with fewer dishes give too little context to ask about,
    though their dishes still serve as wrong options. ``max_menus``: ask about only a
    seeded sample of menus, which limits how much of the corpus one eval run reveals.
    ``max_per_dish``: how many questions one dish can be the answer to. House staples
    appear on dozens of menus; without a cap they dominate the questions.
    ``match_surface``: draw wrong options that look like the answer on the surface (has
    a description, has dietary tags, about as common in the corpus), so formatting
    habits and popularity don't give the answer away.
    """
    if num_options < 2 or num_options > len(LETTERS):
        raise ValueError("num_options must be between 2 and 26")
    allowed = set(courses or DEFAULT_COURSES)
    if include_drinks:
        allowed |= DRINK_COURSES

    eligible = [m for m in menus if m.kind in ELIGIBLE_KINDS]
    slots: list[_Slot] = []
    menu_tokens: list[set[frozenset[str]]] = []
    for m_idx, menu in enumerate(eligible):
        tokens_here: set[frozenset[str]] = set()
        for s_idx, section in enumerate(menu.sections):
            for i_idx, item in enumerate(section.items):
                tokens = dish_tokens(item.name)
                tokens_here.add(tokens)
                if (
                    section.course in allowed
                    and section.selection is not SelectionMode.host_choice
                    and item.role is ItemRole.standard
                    and tokens
                ):
                    slots.append(_Slot(m_idx, s_idx, i_idx, section.course, tokens))
        menu_tokens.append(tokens_here)

    def item_of(slot: _Slot):
        return eligible[slot.menu_idx].sections[slot.section_idx].items[slot.item_idx]

    menus_serving: Counter = Counter(t for tokens in menu_tokens for t in tokens)

    def surface(slot: _Slot) -> tuple[bool, bool]:
        item = item_of(slot)
        return (bool(item.description), bool(item.dietary))

    families = _menu_families(menu_tokens)
    by_course: dict[Course, list[_Slot]] = {}
    for slot in slots:
        by_course.setdefault(slot.course, []).append(slot)

    askable = [
        i for i, m in enumerate(eligible) if sum(1 for _ in m.items()) >= min_menu_items
    ]
    if max_menus is not None and max_menus < len(askable):
        askable = random.Random(f"{seed}:menus").sample(askable, max_menus)
    askable_set = set(askable)

    questions: list[ClozeQuestion] = []
    per_menu: dict[int, int] = {}
    per_dish: Counter = Counter()
    order = list(slots)
    random.Random(f"{seed}:order").shuffle(order)  # which copies of a staple get asked
    for target in order:
        if target.menu_idx not in askable_set:
            continue
        if (
            max_per_menu is not None
            and per_menu.get(target.menu_idx, 0) >= max_per_menu
        ):
            continue
        if max_per_dish is not None and per_dish[target.tokens] >= max_per_dish:
            continue
        menu = eligible[target.menu_idx]
        rng = random.Random(
            f"{seed}:{menu.menu_id}:{target.section_idx}:{target.item_idx}"
        )
        pool = [
            s
            for s in by_course[target.course]
            if s.menu_idx not in families[target.menu_idx]
            # A corpus can pool several caterers; the prompt says the options come
            # from the same caterer, so they must.
            and eligible[s.menu_idx].caterer == menu.caterer
            and not any(same_dish(s.tokens, t) for t in menu_tokens[target.menu_idx])
        ]
        rng.shuffle(pool)
        if match_surface:
            # Same formatting as the answer first, then as close in popularity as
            # possible; the shuffle above breaks ties.
            want = surface(target)
            pool.sort(
                key=lambda c: (
                    surface(c) != want,
                    abs(
                        math.log(menus_serving[c.tokens])
                        - math.log(menus_serving[target.tokens])
                    ),
                )
            )
        distractors: list[_Slot] = []
        for cand in pool:
            if len(distractors) == num_options - 1:
                break
            if any(same_dish(cand.tokens, d.tokens) for d in distractors):
                continue
            distractors.append(cand)
        if len(distractors) < num_options - 1:
            continue

        options = [target, *distractors]
        rng.shuffle(options)

        questions.append(
            ClozeQuestion(
                menu=menu,
                section_idx=target.section_idx,
                item_idx=target.item_idx,
                options=tuple(item_of(o) for o in options),
                option_menu_ids=tuple(eligible[o.menu_idx].menu_id for o in options),
                answer_index=options.index(target),
                related_menu_ids=tuple(
                    sorted(eligible[i].menu_id for i in families[target.menu_idx])
                ),
            )
        )
        per_menu[target.menu_idx] = per_menu.get(target.menu_idx, 0) + 1
        per_dish[target.tokens] += 1
    questions.sort(key=lambda q: (q.menu.menu_id, q.section_idx, q.item_idx))
    return questions
