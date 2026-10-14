"""Deterministic player-view presentation; never reads engine/internal state.

Rules live once per distinct public definition in the persistent system glossary,
not once per instance per historical observation. Changed rules get a new key.
Object references use collision-free UUID prefixes within each observation.
"""

from __future__ import annotations

import hashlib
import html
import json
import re

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TEXT_INSTRUCTIONS = (
    " Observations are compact text. # references identify objects within that decision; "
    "same-name cards are distinct objects. Select an action INDEX, not an object reference. "
    "Rules @ keys refer to the persistent public card glossary below. "
    "Changed rules receive a different key; use each object's current key. "
    "Stack and combat lists retain engine order (stack top first). "
    "Mana is the floating pool, not the mana you could produce from untapped lands."
)


def plain(value) -> str:
    """Remove tooltip markup, retaining text, mana symbols and line boundaries."""
    text = str(value if value is not None else "-")
    text = re.sub(r"<br\s*/?>", " / ", text, flags=re.IGNORECASE)
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", text)).split())


def rule_entry(card: dict) -> tuple[str, str] | None:
    rules = " / ".join(plain(r) for r in card.get("rules", []))
    if not rules:
        return None
    name = plain(card.get("name", "Unknown"))
    key = hashlib.sha256((name + "\n" + rules).encode()).hexdigest()[:12]
    return key, f"{name}: {rules}"


def public_card_rules(observation: dict) -> dict[str, str]:
    """Extract ONLY definitions actually delivered to this seat, including faces."""
    entries = {}

    def visit(value):
        if isinstance(value, dict):
            if "name" in value and "rules" in value:
                entry = rule_entry(value)
                if entry:
                    key, text = entry
                    if key in entries and entries[key] != text:
                        raise ValueError("Public rule key collision")
                    entries[key] = text
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(observation["view"])
    return entries


def glossary_text(entries: dict[str, str]) -> str:
    return "\nPublic card glossary (seen by your seat only):\n" + "\n".join(
        f"@{key} {text}" for key, text in sorted(entries.items())
    )


def render_observation(
    observation: dict,
    *,
    pilot_play_order: str | None = None,
    starting_player: str | None = None,
) -> str:
    """Pure rendering of the delivered observation plus public play/draw factors.

    UI artwork, timers, caches, redundant originals, and engine diagnostics are
    deliberately omitted. Current characteristics/rules and object relationships
    are retained. No deck knowledge, inferred draws, or omniscient file access.
    """
    view = observation["view"]
    ids = sorted(set(UUID.findall(json.dumps(observation))))
    aliases = {}
    for oid in ids:
        length = 8
        while any(other != oid and other[:length] == oid[:length] for other in ids):
            length += 1
        aliases[oid] = "#" + oid[:length]
    players = {p["playerId"]: p["name"] for p in view.get("players", [])}
    names = dict(players)

    def collect(value):
        if isinstance(value, dict):
            if "id" in value and "name" in value:
                names.setdefault(value["id"], plain(value["name"]))
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(view)

    def ref(oid):
        if oid in players:
            return players[oid]
        alias = aliases.get(oid, plain(oid))
        return f"{names[oid]} {alias}" if oid in names else alias

    def text(value):
        return UUID.sub(lambda m: ref(m.group()), plain(value))

    def counters(items):
        return ",".join(f"{text(c['name'])}:{c['count']}" for c in items)

    def card_line(oid, card):
        parts = [f"{plain(card.get('name', 'Unknown'))} {aliases.get(oid, oid)}"]
        costs = "".join(card.get("manaCostLeftStr", []))
        right = "".join(card.get("manaCostRightStr", []))
        if costs or right:
            parts.append(costs + (" // " + right if right else ""))
        types = [*card.get("superTypes", []), *card.get("cardTypes", [])]
        subtypes = card.get("subTypes", {})
        types += (
            subtypes.get("subTypes", []) if isinstance(subtypes, dict) else subtypes
        )
        if types:
            parts.append(" ".join(types))
        if "manaValue" in card:
            parts.append(f"MV={card['manaValue']}")
        if "color" in card:
            colors = "".join(
                symbol
                for color, symbol in (
                    ("white", "W"),
                    ("blue", "U"),
                    ("black", "B"),
                    ("red", "R"),
                    ("green", "G"),
                )
                if card["color"].get(color)
            )
            parts.append("color=" + (colors or "C"))
        if "CREATURE" in card.get("cardTypes", []) or (
            card.get("power") not in (None, "", "0")
            or card.get("toughness") not in (None, "", "0")
        ):
            parts.append(f"{card.get('power', '-')}/{card.get('toughness', '-')}")
        for field in ("loyalty", "defense"):
            if card.get(field) not in (None, ""):
                parts.append(f"{field}={card[field]}")
        if "tapped" in card:
            parts.append("tapped" if card["tapped"] else "untapped")
            parts.append(f"damage={card.get('damage', 0)}")
        for flag in (
            "summoningSickness",
            "faceDown",
            "transformed",
            "flipped",
            "copy",
            "isToken",
            "morphed",
            "disguised",
            "manifested",
            "cloaked",
            "mutated",
        ):
            if card.get(flag):
                parts.append(flag)
        if card.get("phasedIn") is False:
            parts.append("phased-out")
        if card.get("nameController"):
            parts.append("controller=" + text(card["nameController"]))
        if card.get("nameOwner"):
            parts.append("owner=" + text(card["nameOwner"]))
        if card.get("counters"):
            parts.append("counters=" + counters(card["counters"]))
        for field in ("attachments", "targets", "bandedCards"):
            if card.get(field):
                parts.append(field + "=" + ", ".join(ref(i) for i in card[field]))
        for field in ("attachedTo", "pairedCard"):
            if card.get(field):
                parts.append(field + "=" + ref(card[field]))
        if card.get("sourceCard"):
            parts.append("source=" + ref(card["sourceCard"]["id"]))
        if oid in view.get("stack", {}) and "paid" in card:
            parts.append(f"paid={card['paid']}")
        if card.get("mutated"):
            parts.append(
                "mutate=" + text(json.dumps(card.get("mutateView", {}), sort_keys=True))
            )
        entry = rule_entry(card)
        if entry:
            parts.append("rules=@" + entry[0])
        # Alternate/split faces are part of the delivered card, not inferred.
        if card.get("secondCardFace"):
            face = card["secondCardFace"]
            parts.append("other face=" + card_line(face.get("id", oid), face))
        for field in (
            "leftSplitName",
            "leftSplitCostsStr",
            "leftSplitTypeLine",
            "leftSplitRules",
            "rightSplitName",
            "rightSplitCostsStr",
            "rightSplitTypeLine",
            "rightSplitRules",
        ):
            if card.get(field):
                value = card[field]
                parts.append(
                    field
                    + "="
                    + text(" / ".join(value) if isinstance(value, list) else value)
                )
        return "; ".join(parts)

    def zone(label, cards):
        lines.append(label + ":")
        lines.extend("  " + card_line(oid, card) for oid, card in cards.items())
        if not cards:
            lines.append("  (empty)")

    lines = [
        f"Decision {observation['decision']} | You: {observation['player']}",
        f"Turn {view.get('turn', '-')} | {view.get('phase', '-')} / {view.get('step', '-')}",
        (
            f"Active: {text(view.get('activePlayerName', view.get('activePlayerId')))} | "
            f"Priority: {text(view.get('priorityPlayerName'))}"
        ),
    ]
    if starting_player is not None:
        lines.append("Starting player: " + ref(starting_player))
        if pilot_play_order is None:
            pilot_play_order = (
                "play"
                if starting_player in {observation["player"], observation["player_id"]}
                else "draw"
            )
    lines.append(
        "Play/draw: "
        + (plain(pilot_play_order) if pilot_play_order else "unknown (not supplied)")
    )
    for p in view.get("players", []):
        mana = " ".join(
            f"{symbol}:{p.get('manaPool', {}).get(color, 0)}"
            for color, symbol in (
                ("white", "W"),
                ("blue", "U"),
                ("black", "B"),
                ("red", "R"),
                ("green", "G"),
                ("colorless", "C"),
            )
        )
        lines.append(
            f"{p['name']}: life={p['life']} hand={p['handCount']} library={p['libraryCount']} mana=[{mana}]"
        )
        if p.get("counters"):
            lines.append("  counters=" + counters(p["counters"]))
        if p.get("attachments"):
            lines.append("  attachments=" + ", ".join(ref(i) for i in p["attachments"]))
        for flag in ("monarch", "initiative", "hasLeft"):
            if p.get(flag):
                lines.append("  " + flag)
        if p.get("designationNames"):
            lines.append(
                "  designations=" + ", ".join(text(n) for n in p["designationNames"])
            )
        for field in ("battlefield", "graveyard", "exile", "helperCards"):
            if field != "helperCards" or p.get(field):
                zone(p["name"] + " " + field, p.get(field, {}))
        if p.get("topCard"):
            zone(p["name"] + " revealed top", {p["topCard"]["id"]: p["topCard"]})
        for command in p.get("commandList", []):
            lines.append("  command=" + text(json.dumps(command, sort_keys=True)))
    zone("Your hand", view.get("myHand", {}))
    zone("Stack (top first)", view.get("stack", {}))
    lines.append("Combat:")
    for group in view.get("combat", []):
        lines.append(
            "  attackers="
            + ", ".join(ref(i) for i in group["attackers"])
            + " -> "
            + ref(group["defenderId"])
            + " blockers="
            + ", ".join(ref(i) for i in group["blockers"])
            + f" blocked={group['isBlocked']}"
        )
    if not view.get("combat"):
        lines.append("  (none)")
    for field in ("revealed", "lookedAt", "companion"):
        for group in view.get(field, []):
            zone(field + " " + text(group["name"]), group["cards"])
    for index, group in enumerate(view.get("exiles", []), start=1):
        if group:
            lines.append(f"Exile group {index}: " + ", ".join(ref(i) for i in group))
    if view.get("myHelperEmblems"):
        zone("Helper emblems", view["myHelperEmblems"])
    lines.append(
        f"Query {observation['query_type']}: {text(observation.get('message'))}"
    )
    lines.append("Actions (choose index):")
    for action in observation["actions"]:
        label = text(action["label"])
        value = action.get("value")
        if action.get("response_type") == "uuid":
            label += " [" + ref(value) + "]"
        elif (
            value is not None
            and not isinstance(value, bool)
            and str(value) != action["label"]
        ):
            label += " [value=" + text(value) + "]"
        lines.append(f"  {action['index']}: {action['kind']} | {label}")
    return "\n".join(lines)
