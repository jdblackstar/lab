"""Render menus as plain text for prompts.

Every menu is rendered the same way regardless of how its source looked, so a model
can't tell menus apart by typography or layout. Section headings are replaced with
canonical course labels by default: a verbatim heading like "Cheese Board" can give away
which dish belongs in a section without any judgment about composition.
"""

from __future__ import annotations

from .schema import (
    Course,
    EventContext,
    Item,
    ItemRole,
    Menu,
    SelectionMode,
    ServiceStyle,
)

COURSE_LABELS = {
    Course.hors_doeuvres: "Hors d'oeuvres",
    Course.raw_bar: "Raw bar",
    Course.display: "Display",
    Course.bread: "Bread",
    Course.soup: "Soup",
    Course.salad: "Salad",
    Course.appetizer: "First course",
    Course.pasta: "Pasta",
    Course.intermezzo: "Intermezzo",
    Course.main: "Main",
    Course.side: "Sides",
    Course.cheese: "Cheese course",
    Course.dessert: "Dessert",
    Course.late_night: "Late night",
    Course.kids: "Children's menu",
    Course.cocktail: "Cocktails",
    Course.wine: "Wine",
    Course.beer: "Beer",
    Course.spirits: "Spirits",
    Course.non_alcoholic: "Non-alcoholic",
    Course.coffee_tea: "Coffee and tea",
    Course.bar_service: "Bar",
    Course.other: "Other",
}

SERVICE_LABELS = {
    ServiceStyle.plated: "plated",
    ServiceStyle.family_style: "family style",
    ServiceStyle.buffet: "buffet",
    ServiceStyle.stations: "stations",
    ServiceStyle.passed: "passed",
    ServiceStyle.display: "displayed",
    ServiceStyle.reception: "cocktail reception",
    ServiceStyle.drop_off: "drop-off",
    ServiceStyle.mixed: "mixed service",
}

MISSING_MARKER = "[MISSING DISH]"


def _label(value) -> str:
    return value.value.replace("_", " ")


def render_context(menu: Menu) -> str:
    event: EventContext = menu.event
    parts = []
    if menu.service is not ServiceStyle.unknown:
        parts.append(f"Service: {SERVICE_LABELS[menu.service]}")
    if event.event_type.value != "unknown":
        parts.append(f"Event: {_label(event.event_type)}")
    if event.meal_period.value != "unknown":
        parts.append(f"Meal: {_label(event.meal_period)}")
    if event.season.value != "unknown":
        parts.append(f"Season: {event.season.value}")
    if event.guest_count.value != "unknown":
        parts.append(f"Guests: {event.guest_count.value.replace('_', ' ')}")
    return "\n".join(parts)


def render_item(item: Item) -> str:
    line = item.name
    if item.description:
        line += f" — {item.description}"
    tags = [_label(d) for d in item.dietary]
    if item.role is not ItemRole.standard:
        tags.insert(0, _label(item.role))
    if tags:
        line += f" ({', '.join(tags)})"
    if item.pairing:
        line += f" [paired with {item.pairing}]"
    return line


def render_menu(
    menu: Menu,
    *,
    missing: tuple[int, int] | None = None,
    verbatim_headings: bool = False,
    include_notes: bool = False,
) -> str:
    """Render a menu, optionally replacing item ``(section_idx, item_idx)`` with a marker."""
    lines: list[str] = []
    context = render_context(menu)
    if context:
        lines += [context, ""]
    for s_idx, section in enumerate(menu.sections):
        heading = COURSE_LABELS[section.course]
        if verbatim_headings and section.heading:
            heading = section.heading
        details = []
        if section.service and section.service is not menu.service:
            details.append(SERVICE_LABELS.get(section.service, ""))
        if section.selection is SelectionMode.guest_choice:
            details.append("guests choose one")
        details = [d for d in details if d]
        if details:
            heading += f" ({', '.join(details)})"
        lines.append(heading)
        for i_idx, item in enumerate(section.items):
            if missing == (s_idx, i_idx):
                lines.append(f"- {MISSING_MARKER}")
            else:
                lines.append(f"- {render_item(item)}")
        lines.append("")
    if include_notes and menu.notes:
        lines.append("Notes")
        lines += [f"- {n}" for n in menu.notes]
    return "\n".join(lines).strip()
