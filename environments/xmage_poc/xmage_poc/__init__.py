"""Two fixture decks, private controller histories, omniscient engine records."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import verifiers as vf

__all__ = ["load_environment"]


def load_environment(
    num_games: int = 1,
    seed: int = 7,
    output_dir: str | None = None,
    java_bin: str | None = None,
    max_turns: int = 4000,
    history_decisions: int = 4,
    deck_a: str | None = None,
    deck_b: str | None = None,
    opponent: str = "self_play",
    pilot_seat: str = "alternate",
    auto_pass_priority: bool = True,
    max_action_attempts: int = 3,
) -> vf.Environment:
    # Keep the standalone game/audit CLIs independent of Verifiers startup.
    from .environment import load_environment as load

    return load(
        num_games=num_games,
        seed=seed,
        output_dir=output_dir,
        java_bin=java_bin,
        max_turns=max_turns,
        history_decisions=history_decisions,
        deck_a=deck_a,
        deck_b=deck_b,
        opponent=opponent,
        pilot_seat=pilot_seat,
        auto_pass_priority=auto_pass_priority,
        max_action_attempts=max_action_attempts,
    )
