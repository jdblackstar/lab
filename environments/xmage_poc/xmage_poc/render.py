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
from dataclasses import dataclass

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


COLORS = (
    ("white", "W"),
    ("blue", "U"),
    ("black", "B"),
    ("red", "R"),
    ("green", "G"),
)
MANA = (*COLORS, ("colorless", "C"))
CARD_FLAGS = (
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
)
SPLIT_FIELDS = (
    "leftSplitName",
    "leftSplitCostsStr",
    "leftSplitTypeLine",
    "leftSplitRules",
    "rightSplitName",
    "rightSplitCostsStr",
    "rightSplitTypeLine",
    "rightSplitRules",
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
    refs = _Refs.of(observation)
    stack = view.get("stack", {})
    lines = _header(observation, refs)
    lines += _play_draw(observation, refs, pilot_play_order, starting_player)
    for player in view.get("players", []):
        lines += _player(player, refs, stack)
    lines += _zone("Your hand", view.get("myHand", {}), refs, stack)
    lines += _zone("Stack (top first)", stack, refs, stack)
    lines += _combat(view.get("combat", []), refs)
    lines += _card_groups(view, refs, stack)
    lines.append(
        f"Query {observation['query_type']}: {refs.text(observation.get('message'))}"
    )
    lines += _actions(observation["actions"], refs)
    return "\n".join(lines)


@dataclass(frozen=True)
class _Refs:
    """How one observation's object and player UUIDs are shown to the model.

    ``aliases`` maps each UUID to its shortest collision-free ``#`` prefix,
    ``players`` maps player ids to names, and ``names`` maps every named
    object id to its name (players first, then the first name found in the view).
    """

    aliases: dict[str, str]
    players: dict[str, str]
    names: dict[str, str]

    @classmethod
    def of(cls, observation: dict) -> _Refs:
        view = observation["view"]
        players = {p["playerId"]: p["name"] for p in view.get("players", [])}
        return cls(_aliases(observation), players, _names(view, players))

    def ref(self, oid) -> str:
        if oid in self.players:
            return self.players[oid]
        alias = self.aliases.get(oid, plain(oid))
        return f"{self.names[oid]} {alias}" if oid in self.names else alias

    def text(self, value) -> str:
        return UUID.sub(lambda m: self.ref(m.group()), plain(value))

    def refs(self, oids) -> str:
        return ", ".join(self.ref(oid) for oid in oids)

    def counters(self, items) -> str:
        return ",".join(f"{self.text(c['name'])}:{c['count']}" for c in items)


def _aliases(observation: dict) -> dict[str, str]:
    ids = sorted(set(UUID.findall(json.dumps(observation))))
    aliases = {}
    for oid in ids:
        length = 8
        while any(other != oid and other[:length] == oid[:length] for other in ids):
            length += 1
        aliases[oid] = "#" + oid[:length]
    return aliases


def _names(view: dict, players: dict[str, str]) -> dict[str, str]:
    names = dict(players)

    def visit(value):
        if isinstance(value, dict):
            if "id" in value and "name" in value:
                names.setdefault(value["id"], plain(value["name"]))
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(view)
    return names


def _header(observation: dict, refs: _Refs) -> list[str]:
    view = observation["view"]
    return [
        f"Decision {observation['decision']} | You: {observation['player']}",
        f"Turn {view.get('turn', '-')} | {view.get('phase', '-')} / {view.get('step', '-')}",
        (
            f"Active: {refs.text(view.get('activePlayerName', view.get('activePlayerId')))} | "
            f"Priority: {refs.text(view.get('priorityPlayerName'))}"
        ),
    ]


def _play_draw(
    observation: dict,
    refs: _Refs,
    pilot_play_order: str | None,
    starting_player: str | None,
) -> list[str]:
    """A supplied play order wins; otherwise infer it from the starting player."""
    lines = []
    if starting_player is not None:
        lines.append("Starting player: " + refs.ref(starting_player))
        if pilot_play_order is None:
            you = {observation["player"], observation["player_id"]}
            pilot_play_order = "play" if starting_player in you else "draw"
    order = plain(pilot_play_order) if pilot_play_order else "unknown (not supplied)"
    lines.append("Play/draw: " + order)
    return lines


def _player(p: dict, refs: _Refs, stack: dict) -> list[str]:
    """Public summary line, player-level state, then the player's zones."""
    pool = p.get("manaPool", {})
    mana = " ".join(f"{symbol}:{pool.get(color, 0)}" for color, symbol in MANA)
    lines = [
        f"{p['name']}: life={p['life']} hand={p['handCount']} library={p['libraryCount']} mana=[{mana}]"
    ]
    if p.get("counters"):
        lines.append("  counters=" + refs.counters(p["counters"]))
    if p.get("attachments"):
        lines.append("  attachments=" + refs.refs(p["attachments"]))
    lines += [
        "  " + flag for flag in ("monarch", "initiative", "hasLeft") if p.get(flag)
    ]
    if p.get("designationNames"):
        lines.append(
            "  designations=" + ", ".join(refs.text(n) for n in p["designationNames"])
        )
    for field in ("battlefield", "graveyard", "exile"):
        lines += _zone(p["name"] + " " + field, p.get(field, {}), refs, stack)
    if p.get("helperCards"):
        lines += _zone(p["name"] + " helperCards", p["helperCards"], refs, stack)
    if p.get("topCard"):
        top = p["topCard"]
        lines += _zone(p["name"] + " revealed top", {top["id"]: top}, refs, stack)
    for command in p.get("commandList", []):
        lines.append("  command=" + refs.text(json.dumps(command, sort_keys=True)))
    return lines


def _zone(label: str, cards: dict, refs: _Refs, stack: dict) -> list[str]:
    lines = [label + ":"]
    lines += ["  " + _card_line(oid, card, refs, stack) for oid, card in cards.items()]
    if not cards:
        lines.append("  (empty)")
    return lines


def _combat(groups: list, refs: _Refs) -> list[str]:
    lines = ["Combat:"]
    for group in groups:
        lines.append(
            f"  attackers={refs.refs(group['attackers'])}"
            f" -> {refs.ref(group['defenderId'])}"
            f" blockers={refs.refs(group['blockers'])}"
            f" blocked={group['isBlocked']}"
        )
    if not groups:
        lines.append("  (none)")
    return lines


def _card_groups(view: dict, refs: _Refs, stack: dict) -> list[str]:
    """Revealed, looked-at, and companion cards; exile groups; helper emblems."""
    lines = []
    for field in ("revealed", "lookedAt", "companion"):
        for group in view.get(field, []):
            label = field + " " + refs.text(group["name"])
            lines += _zone(label, group["cards"], refs, stack)
    for index, group in enumerate(view.get("exiles", []), start=1):
        if group:
            lines.append(f"Exile group {index}: " + refs.refs(group))
    if view.get("myHelperEmblems"):
        lines += _zone("Helper emblems", view["myHelperEmblems"], refs, stack)
    return lines


def _actions(actions: list, refs: _Refs) -> list[str]:
    """Each action's label, plus its target or value when the label omits it."""
    lines = ["Actions (choose index):"]
    for action in actions:
        label = refs.text(action["label"])
        value = action.get("value")
        if action.get("response_type") == "uuid":
            label += " [" + refs.ref(value) + "]"
        elif (
            value is not None
            and not isinstance(value, bool)
            and str(value) != action["label"]
        ):
            label += " [value=" + refs.text(value) + "]"
        lines.append(f"  {action['index']}: {action['kind']} | {label}")
    return lines


def _card_line(oid: str, card: dict, refs: _Refs, stack: dict) -> str:
    """One card as ``; ``-separated parts, in this order:

    name and alias; mana cost; type line; MV; color; P/T, loyalty, defense;
    tapped/damage, flags, phasing; controller/owner; counters; relationships;
    paid (stack only); mutate; rules key; other face; split halves.
    """
    parts = [f"{plain(card.get('name', 'Unknown'))} {refs.aliases.get(oid, oid)}"]

    # Characteristics.
    costs = "".join(card.get("manaCostLeftStr", []))
    right = "".join(card.get("manaCostRightStr", []))
    if costs or right:
        parts.append(costs + (" // " + right if right else ""))
    types = [*card.get("superTypes", []), *card.get("cardTypes", [])]
    subtypes = card.get("subTypes", {})
    types += subtypes.get("subTypes", []) if isinstance(subtypes, dict) else subtypes
    if types:
        parts.append(" ".join(types))
    if "manaValue" in card:
        parts.append(f"MV={card['manaValue']}")
    if "color" in card:
        colors = "".join(symbol for color, symbol in COLORS if card["color"].get(color))
        parts.append("color=" + (colors or "C"))
    if "CREATURE" in card.get("cardTypes", []) or (
        card.get("power") not in (None, "", "0")
        or card.get("toughness") not in (None, "", "0")
    ):
        parts.append(f"{card.get('power', '-')}/{card.get('toughness', '-')}")
    for field in ("loyalty", "defense"):
        if card.get(field) not in (None, ""):
            parts.append(f"{field}={card[field]}")

    # Status.
    if "tapped" in card:
        parts.append("tapped" if card["tapped"] else "untapped")
        parts.append(f"damage={card.get('damage', 0)}")
    parts += [flag for flag in CARD_FLAGS if card.get(flag)]
    if card.get("phasedIn") is False:
        parts.append("phased-out")
    if card.get("nameController"):
        parts.append("controller=" + refs.text(card["nameController"]))
    if card.get("nameOwner"):
        parts.append("owner=" + refs.text(card["nameOwner"]))
    if card.get("counters"):
        parts.append("counters=" + refs.counters(card["counters"]))

    # Relationships to other objects.
    for field in ("attachments", "targets", "bandedCards"):
        if card.get(field):
            parts.append(field + "=" + refs.refs(card[field]))
    for field in ("attachedTo", "pairedCard"):
        if card.get(field):
            parts.append(field + "=" + refs.ref(card[field]))
    if card.get("sourceCard"):
        parts.append("source=" + refs.ref(card["sourceCard"]["id"]))
    if oid in stack and "paid" in card:
        parts.append(f"paid={card['paid']}")
    if card.get("mutated"):
        mutate = json.dumps(card.get("mutateView", {}), sort_keys=True)
        parts.append("mutate=" + refs.text(mutate))

    # Rules and faces. Alternate/split faces are part of the delivered card,
    # not inferred.
    entry = rule_entry(card)
    if entry:
        parts.append("rules=@" + entry[0])
    if card.get("secondCardFace"):
        face = card["secondCardFace"]
        parts.append("other face=" + _card_line(face.get("id", oid), face, refs, stack))
    for field in SPLIT_FIELDS:
        if card.get(field):
            value = card[field]
            joined = " / ".join(value) if isinstance(value, list) else value
            parts.append(field + "=" + refs.text(joined))
    return "; ".join(parts)
