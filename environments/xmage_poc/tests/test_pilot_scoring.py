import pytest
from xmage_poc.environment import pilot_win


@pytest.mark.parametrize("seat", ["player_a", "player_b"])
def test_score_uses_pilot_seat_and_requires_verified_game(seat):
    state = {
        "pilot_seat": seat,
        "recording_audit": {"privacy_passed": True},
        "game_result": {
            "players": [
                {"name": "player_a", "won": True},
                {"name": "player_b", "won": False},
            ]
        },
    }
    assert pilot_win(state) == (1.0 if seat == "player_a" else 0.0)
    state["recording_audit"]["privacy_passed"] = False
    assert pilot_win(state) == 0.0


def test_draw_or_interrupted_game_is_not_a_win():
    assert pilot_win({"pilot_seat": "player_a"}) == 0.0
    state = {
        "pilot_seat": "player_a",
        "recording_audit": {"privacy_passed": True},
        "game_result": {"players": [{"name": "player_a", "won": False}]},
    }
    assert pilot_win(state) == 0.0
