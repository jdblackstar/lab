"""Static registration information, independent of shuffled game zones."""

from collections import Counter


def deck_context(lines: list[str], player: str) -> dict:
    counts = Counter()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        count, name = line.split(maxsplit=1)
        if not count.isdecimal() or int(count) < 1:
            raise ValueError(f"Invalid deck count: {count}")
        counts[name.strip()] += int(count)
    total = sum(counts.values())
    if total != 60:
        raise ValueError(f"Fixture must contain 60 cards; got {total}")
    return {
        "player": player,
        "deck_size": total,
        "decklist": [
            {"name": name, "count": count} for name, count in sorted(counts.items())
        ],
    }
