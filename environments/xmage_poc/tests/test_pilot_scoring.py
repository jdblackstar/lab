import pytest
from xmage_poc import load_environment
from xmage_poc.baseline import summarize
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


def test_balanced_dataset_crosses_all_factors_within_each_seed():
    env = load_environment(num_games=16, seed=31, java_bin="/bin/false")
    for seed in (31, 32):
        cases = [row["info"] for row in env.dataset if row["info"]["seed"] == seed]
        assert {
            (c["pilot_seat"], c["pilot_deck"], c["pilot_play_order"]) for c in cases
        } == {
            (seat, deck, order)
            for seat in ("player_a", "player_b")
            for deck in ("deck_a", "deck_b")
            for order in ("play", "draw")
        }
        assert len(cases) == 8
        for case in cases:
            assert (case["starting_player"] == case["pilot_seat"]) == (
                case["pilot_play_order"] == "play"
            )
            assert case["pilot_deck"] != case["opponent_deck"]


@pytest.mark.parametrize("seat", ["player_a", "player_b"])
@pytest.mark.parametrize("deck", ["deck_a", "deck_b"])
@pytest.mark.parametrize("order", ["play", "draw"])
def test_factors_can_be_fixed_independently(tmp_path, seat, deck, order):
    decks = [tmp_path / "fixture-a.txt", tmp_path / "fixture-b.txt"]
    for path, contents in zip(decks, ("60 Plains", "60 Mountain"), strict=True):
        path.write_text(contents)
    env = load_environment(
        num_games=2,
        seed=41,
        java_bin="/bin/false",
        deck_a=str(decks[0]),
        deck_b=str(decks[1]),
        pilot_seat=seat,
        pilot_deck=deck,
        pilot_play_order=order,
    )
    assert [row["info"]["seed"] for row in env.dataset] == [41, 42]
    for row in env.dataset:
        info = row["info"]
        assert (info["pilot_seat"], info["pilot_deck"], info["pilot_play_order"]) == (
            seat,
            deck,
            order,
        )
        seated = dict(zip(("player_a", "player_b"), env.decks_for(info), strict=True))
        assert seated[seat] == decks[0 if deck == "deck_a" else 1]
        assert (info["starting_player"] == seat) == (order == "play")


@pytest.mark.parametrize(
    "wins, games, interval",
    [
        (0, 10, [0.0, 0.2775327998628892]),
        (1, 4, [0.0455872608097006, 0.6993581574175982]),
        (10, 10, [0.7224672001371108, 1.0]),
    ],
)
def test_baseline_reports_wilson_intervals_including_boundary_rates(
    wins, games, interval
):
    records = [
        {
            "pilot_seat": "player_b",
            "pilot_deck": "deck_a",
            "pilot_play_order": "draw",
            "won": i < wins,
            "lost": i >= wins,
        }
        for i in range(games)
    ]
    for groups in summarize(records).values():
        for group in groups.values():
            assert group["games"] == games
            assert group["win_rate"] == wins / games
            assert group["win_rate_ci95"] == pytest.approx(interval, abs=1e-12)


def test_baseline_intervals_use_each_stratums_denominator_and_include_draws():
    records = [
        {
            "pilot_seat": "player_a",
            "pilot_deck": "deck_a",
            "pilot_play_order": "play",
            "won": False,
            "lost": True,
        },
        {
            "pilot_seat": "player_b",
            "pilot_deck": "deck_a",
            "pilot_play_order": "draw",
            "won": False,
            "lost": False,
        },
        {
            "pilot_seat": "player_a",
            "pilot_deck": "deck_b",
            "pilot_play_order": "play",
            "won": True,
            "lost": False,
        },
    ]
    strata = summarize(records)
    assert strata["overall"]["all"]["draws"] == 1
    assert strata["overall"]["all"]["win_rate"] == pytest.approx(1 / 3)
    assert strata["pilot_deck"]["deck_a"]["win_rate_ci95"] == pytest.approx(
        [0.0, 0.6576197724933469], abs=1e-12
    )
    assert strata["pilot_deck"]["deck_b"]["win_rate_ci95"] == pytest.approx(
        [0.2065493143772374, 1.0], abs=1e-12
    )
