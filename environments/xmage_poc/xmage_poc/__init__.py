"""Two fixture decks, private controller histories, omniscient engine records."""

from __future__ import annotations

__all__ = ["XMageEnv", "XMageHarness", "XMageTaskset"]


def __getattr__(name: str):
    # Keep the standalone game/audit CLIs independent of Verifiers startup.
    if name in {"XMageEnv", "XMageTaskset"}:
        from . import environment

        return getattr(environment, name)
    if name == "XMageHarness":
        from .harness import XMageHarness

        return XMageHarness
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
