"""Shared helpers for matching scenario sample-data rows."""

from __future__ import annotations

from typing import Any


def matching_sample_rows(
    table_obj: dict[str, Any],
    match: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return sample-data rows matching all key/value pairs in *match*."""
    rows = table_obj.get("rows") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(row.get(key) == value for key, value in match.items()):
            out.append(row)
    return out
