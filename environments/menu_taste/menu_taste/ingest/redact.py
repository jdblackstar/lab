"""Remove prices and contact details; flag anything that might identify a client.

The extractor is told to leave these out, and this pass catches what it misses. Prices
and contact details are unambiguous, so they're removed. Names and events ("the Smith
wedding") are too easy to confuse with dish names ("Beef Wellington"), so they're only
flagged for a person to review.
"""

from __future__ import annotations

import re

from ..schema import Menu

_UNIT = r"(?:\s*(?:\+\+|pp|p/p|/\s*(?:person|guest|pp|piece|pc|dozen|doz)|per\s+(?:person|guest|piece|dozen|serving|platter|tray)|each|ea\.?))?"
PRICE_PATTERNS = [
    re.compile(r"[$£€]\s?\d[\d,]*(?:\.\d{1,2})?" + _UNIT, re.IGNORECASE),
    re.compile(r"\b\d[\d,]*(?:\.\d{2})?\s?(?:USD|dollars)\b" + _UNIT, re.IGNORECASE),
    re.compile(
        r"\b\d+(?:\.\d{2})?\s*(?:pp|p/p|per\s+(?:person|guest|piece|dozen)|/\s*(?:person|guest|pp))\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+(?:\.\d{2})?\s?\+\+"),  # "125++" = plus tax and service
    re.compile(r"\bmarket\s+price\b|\(\s*MP\s*\)", re.IGNORECASE),
    # A bare decimal amount at the end of a line ("Burrata ... 14.50").
    re.compile(r"(?:\s*[|·•]\s*|\s+)\d{1,4}\.\d{2}\s*$"),
]
CONTACT_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"),
    re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE),
]
FLAG_PATTERNS = [
    (re.compile(r"\b(?:Mr|Mrs|Ms|Mx|Dr)\.?\s+[A-Z][a-z]+"), "honorific + name"),
    (
        re.compile(
            r"\b[A-Z][a-z]+\s*(?:&|and)\s*[A-Z][a-z]+(?:'s)?\s+(?:wedding|reception|dinner|party|celebration)",
            re.IGNORECASE,
        ),
        "couple's names",
    ),
    (
        re.compile(
            r"\b[Tt]he\s+[A-Z][a-z]+(?:[-\s][A-Z][a-z]+)?\s+(?i:wedding|reception|bar mitzvah|bat mitzvah|party|dinner)\b"
        ),
        "family name",
    ),
    (
        re.compile(
            r"\b(?:wedding|marriage|celebration|memorial)\s+of\b", re.IGNORECASE
        ),
        "names an honoree",
    ),
    (
        re.compile(r"\bin\s+(?:honou?r|memory)\s+of\b", re.IGNORECASE),
        "names an honoree",
    ),
    (
        re.compile(
            r"\b[A-Z][a-z]+'s\s+(?:\d+\w*\s+)?(?:birthday|wedding|retirement|bar mitzvah|bat mitzvah|graduation|party)",
            re.IGNORECASE,
        ),
        "names an honoree",
    ),
    (
        re.compile(
            r"\b\d{1,5}\s+[A-Z][\w.]*(?:\s+[A-Z][\w.]*)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Place|Pl)\b"
        ),
        "street address",
    ),
    (
        re.compile(r"\b(?:Inc|LLC|Corp|Corporation|Foundation|Associates)\b"),
        "organization name",
    ),
    (
        re.compile(
            r"\b(?:invoice|deposit|gratuity|service charge|tax|subtotal|total)\b",
            re.IGNORECASE,
        ),
        "billing language",
    ),
    (
        re.compile(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b"
        ),
        "exact date",
    ),
]


def scrub(text: str) -> tuple[str, int]:
    """Remove prices and contact details. Returns the cleaned text and removal count."""
    count = 0
    for pattern in PRICE_PATTERNS + CONTACT_PATTERNS:
        text, n = pattern.subn("", text)
        count += n
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;|·•-–—")
    return text, count


def flags(text: str) -> list[str]:
    return [label for pattern, label in FLAG_PATTERNS if pattern.search(text)]


def redact_menu(menu: Menu) -> Menu:
    """Return a copy with prices/contacts removed and review warnings attached."""
    menu = menu.model_copy(deep=True)
    removed = 0
    warnings: list[str] = []

    def clean(value: str | None, where: str) -> str | None:
        nonlocal removed
        if not value:
            return value
        out, n = scrub(value)
        removed += n
        for label in flags(out):
            warnings.append(f"review {where}: {label}: {out!r}")
        return out or None

    menu.title = clean(menu.title, "title")
    menu.notes = [n for n in (clean(n, "note") for n in menu.notes) if n]
    for section in menu.sections:
        section.heading = clean(section.heading, "heading")
        for item in section.items:
            item.name = clean(item.name, "item name") or ""
            item.description = clean(item.description, f"description of {item.name!r}")
            item.pairing = clean(item.pairing, f"pairing for {item.name!r}")
        # A name that was nothing but a price or contact is not a dish.
        section.items = [item for item in section.items if item.name]
    if removed:
        warnings.insert(0, f"removed {removed} price/contact fragment(s)")
    menu.warnings = list(dict.fromkeys(menu.warnings + warnings))
    return menu
