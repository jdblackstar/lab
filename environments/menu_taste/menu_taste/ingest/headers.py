"""Classify inline section headers ("FAMILY STYLE MAINS", "Passed Canapés").

Spreadsheet exports often put section headers in the same cells as dishes. A header
tells us the course, how it is served, whether guests choose, and sometimes that the
items below aren't guest food at all (vendor meals, things the client brings).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..schema import Course, ItemRole, SelectionMode, ServiceStyle


@dataclass(frozen=True)
class HeaderInfo:
    course: Course
    service: ServiceStyle | None = None
    selection: SelectionMode = SelectionMode.all
    role: ItemRole = ItemRole.standard
    # "drop": items under it are not guest food the caterer served.
    # "attach": continues the previous section ("SERVED WITH", "INCLUDED IN ...").
    action: str = "section"


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# A string must contain one of these to be read as a header at all.
HEADER_WORDS = _rx(
    r"\b(small bites?|bites|h/?d'?s?|hors d'?oeuvres|canap[eé]s|amuse|passed|tray|stationa?r?y|"
    r"stations?|stationed|course|salad|soup|entr[eé]es?|main|sides?|desserts?|sweets|"
    r"buffet|family[- ]style|plated|pre-?set|seated|pre-?selected|pre-?ordered|choice of|"
    r"late night|snacks?|grazing|board|platter(ed|s)?|reception|delivery|pick ?up|to go|boxed|"
    r"boxes|lunch(es)?|dinner|brunch|breakfast|option|vegetarian|vegan|allergy|veg\.?|"
    r"cart|bar|pizza|pasta|taco|carving|active|at the table|on the table|served with|"
    r"included in|included with|each box contains|client|vendor|invoice|sample menu|cheese|ice cream|"
    r"gelato|sundae|bowls|beverages|restaurant style|duet|pairing|tasting|activation|"
    r"kitchen|flatbreads|potatoes)\b"
)

MIXED_CASE_HEADER_VOCAB = frozenset(
    [
        "passed",
        "h",
        "d's",
        "hd's",
        "ds",
        "h/d's",
        "hors",
        "d'oeuvres",
        "canapes",
        "canapés",
        "amuse",
        "bouche",
        "small",
        "bite",
        "bites",
        "tray",
        "stationary",
        "station",
        "stations",
        "stationed",
        "late",
        "night",
        "snack",
        "snacks",
        "boxed",
        "box",
        "boxes",
        "lunch",
        "lunches",
        "dinner",
        "breakfast",
        "brunch",
        "buffet",
        "family",
        "style",
        "family-style",
        "main",
        "course",
        "courses",
        "dessert",
        "desserts",
        "sweets",
        "salad",
        "salads",
        "soup",
        "first",
        "second",
        "third",
        "fourth",
        "plated",
        "pre-set",
        "preset",
        "seated",
        "served",
        "sides",
        "side",
        "entree",
        "entrees",
        "entrée",
        "entrées",
        "vegetarian",
        "vegan",
        "veg",
        "option",
        "options",
        "menu",
        "reception",
        "welcome",
        "grazing",
        "board",
        "mini",
        "at",
        "on",
        "the",
        "table",
        "of",
        "choice",
        "pre-selected",
        "pre-ordered",
        "alfresco",
        "al",
        "fresco",
        "included",
        "with",
        "continental",
        "to",
        "go",
        "pick",
        "up",
        "delivery",
        "and",
        "cocktail",
        "hour",
        "active",
        "chef",
        "chef's",
        "pizza",
        "oven",
        "from",
        "cart",
        "bar",
        "platter",
        "platters",
        "plattered",
        "pasta",
        "course",
    ]
)

_SERVICE_RULES: list[tuple[re.Pattern, ServiceStyle]] = [
    (
        _rx(r"\b(boxed|boxes|delivery|pick ?up|to go|disposable|re-?heatable)\b"),
        ServiceStyle.drop_off,
    ),
    (
        _rx(r"\b(family[- ]style|at the table|on the table)\b"),
        ServiceStyle.family_style,
    ),
    (_rx(r"\b(buffet|al ?fresco)\b"), ServiceStyle.buffet),
    (_rx(r"\b(passed|tray)\b"), ServiceStyle.passed),
    (
        _rx(r"\b(stationary|grazing|board|platter(ed|s)?|display)\b"),
        ServiceStyle.display,
    ),
    (
        _rx(r"\b(stations?|stationed|active|cart|bar|kitchen|activation)\b"),
        ServiceStyle.stations,
    ),
    (
        _rx(
            r"\b(plated|pre-?set|seated|pre-?selected|pre-?ordered|restaurant style)\b"
        ),
        ServiceStyle.plated,
    ),
    (_rx(r"\breception\b"), ServiceStyle.reception),
]

# First match wins; order goes from most to least specific.
_COURSE_RULES: list[tuple[re.Pattern, dict]] = [
    (_rx(r"\b(vendor|invoice only)\b"), {"course": Course.other, "action": "drop"}),
    (
        _rx(r"\b(client to provide|provided by client)\b"),
        {"course": Course.other, "action": "drop"},
    ),
    (
        _rx(r"\b(served with|included (in|with)|each box contains)\b"),
        {"course": Course.other, "action": "attach"},
    ),
    (
        _rx(
            r"\b(veg\.?|vegetarian|vegan|allergy)[\w\s/&.-]*\b(entr[eé]e|option|opt|meal)\b|\bveg(etarian)?\s*opt"
        ),
        {"course": Course.main, "role": ItemRole.dietary_alternate},
    ),
    (_rx(r"\blate night\b"), {"course": Course.late_night}),
    (
        _rx(r"\b(desserts?|sweets|ice cream|gelato|sundae|cake)\b"),
        {"course": Course.dessert},
    ),
    (
        _rx(
            r"\b(small bites?|bites|h/?d'?s?|hors d'?oeuvres|canap[eé]s|amuse|snacks?)\b|^passed$"
        ),
        {"course": Course.hors_doeuvres},
    ),
    (_rx(r"\breception\b"), {"course": Course.hors_doeuvres}),
    (_rx(r"\b(grazing|board|cheese station)\b"), {"course": Course.display}),
    (_rx(r"\bcheese course\b"), {"course": Course.cheese}),
    (_rx(r"\bsalad\b"), {"course": Course.salad}),
    (_rx(r"\bsoup\b"), {"course": Course.soup}),
    (_rx(r"\b(first course|pre-?set first)\b"), {"course": Course.appetizer}),
    (_rx(r"\bsecond course\b"), {"course": Course.appetizer}),
    (_rx(r"\b(third|fourth|duet) course\b"), {"course": Course.main}),
    (_rx(r"\b(sides?|potatoes)\b"), {"course": Course.side}),
    (_rx(r"\bpasta\b(?!.*\bmain\b)"), {"course": Course.pasta}),
    (_rx(r"\bbeverages\b"), {"course": Course.non_alcoholic}),
    (
        _rx(
            r"\b(entr[eé]es?|main|dinner|lunch(es)?|brunch|breakfast|buffet|stations?|bowls|"
            r"taco|carving|pizza|flatbreads|kitchen|activation|platters|boxed)\b"
        ),
        {"course": Course.main},
    ),
]

_GUEST_CHOICE = _rx(r"\b(choice of|pre-?selected|pre-?ordered)\b")
_TIME = re.compile(
    r"\(?\b\d{1,2}(:\d{2})?\s*(-|–)\s*\d{1,2}(:\d{2})?\)?|\(\d{1,2}:\d{2}\)"
)


# "Included with the Gyros Station" continues the section above, whatever its casing.
_CONTINUES = _rx(r"^(served with|included (in|with)|each box contains)\b")


def clean_header(text: str) -> str:
    text = _TIME.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" :-–!*#")


def looks_like_header(text: str, description: str = "") -> bool:
    """A header has header vocabulary and reads like a label, not a dish."""
    t = clean_header(text)
    if not t or not HEADER_WORDS.search(t):
        return False
    letters = [c for c in t if c.isalpha()]
    all_caps = bool(letters) and all(c.isupper() for c in letters)
    if all_caps or _CONTINUES.match(t):
        return True
    # Mixed-case labels ("Passed Canapés", "Late Night Snack") use only header words, so
    # "Apricot Linzer Bar" and "Breakfast Kolaches" stay dishes.
    words = [w for w in re.split(r"[\s/&+,.!-]+", t.lower()) if w and not w.isdigit()]
    return bool(words) and all(w in MIXED_CASE_HEADER_VOCAB for w in words)


def classify_header(text: str) -> HeaderInfo:
    t = clean_header(text)
    fields: dict = {"course": Course.other}
    for pattern, values in _COURSE_RULES:
        if pattern.search(t):
            fields = dict(values)
            break
    service = next((s for p, s in _SERVICE_RULES if p.search(t)), None)
    if fields["course"] is Course.display and service is None:
        service = ServiceStyle.display
    selection = (
        SelectionMode.guest_choice if _GUEST_CHOICE.search(t) else SelectionMode.all
    )
    return HeaderInfo(service=service, selection=selection, **fields)


_INLINE = re.compile(
    r"^(?P<head>[^a-z]{4,}?)\s*(?:\s[-–]\s?|:\s*|\s?[-–]\s)(?P<rest>.+)$"
)


def split_inline_header(title: str) -> tuple[str | None, str]:
    """'SALAD COURSE: Frisée' -> ('SALAD COURSE', 'Frisée')."""
    m = _INLINE.match(title)
    if m and looks_like_header(m.group("head")) and m.group("rest").strip():
        return m.group("head").strip(), m.group("rest").strip()
    return None, title
