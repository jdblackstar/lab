"""Read and write menu corpora (JSON Lines, one ``Menu`` per line)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from .schema import Menu

MENUS_ENV_VAR = "MENU_TASTE_MENUS"
SAMPLE_CORPUS = "sample_menus.jsonl"


def load_menus(path: str | os.PathLike) -> list[Menu]:
    menus = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                menus.append(Menu.model_validate_json(line))
            except ValueError as e:
                raise ValueError(f"{path}:{line_no}: invalid menu record: {e}") from e
    return menus


def write_menus(menus: Iterable[Menu], path: str | os.PathLike) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(menu.model_dump_json(exclude_none=True) + "\n" for menu in menus)


def sample_corpus_path() -> Path:
    return Path(str(resources.files("menu_taste") / "data" / SAMPLE_CORPUS))


def resolve_corpus(path: str | None) -> Path:
    """Explicit path, then ``$MENU_TASTE_MENUS``, then the bundled synthetic sample."""
    chosen = path or os.environ.get(MENUS_ENV_VAR)
    return Path(chosen).expanduser() if chosen else sample_corpus_path()


def dump_json(menu: Menu) -> str:
    return json.dumps(menu.model_dump(mode="json", exclude_none=True), indent=2)
