import json
import sys
from threading import Event
from types import SimpleNamespace

import pytest
from xmage_poc import baseline
from xmage_poc.baseline import summarize
from xmage_poc.environment import XMageConfig, XMageData, XMageTaskset, pilot_win


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
    taskset = XMageTaskset(XMageConfig(num_games=16, seed=31))
    for seed in (31, 32):
        cases = [task.data for task in taskset if task.data.seed == seed]
        assert {(c.pilot_seat, c.pilot_deck, c.pilot_play_order) for c in cases} == {
            (seat, deck, order)
            for seat in ("player_a", "player_b")
            for deck in ("deck_a", "deck_b")
            for order in ("play", "draw")
        }
        assert len(cases) == 8
        for case in cases:
            assert (case.starting_player == case.pilot_seat) == (
                case.pilot_play_order == "play"
            )
            assert case.pilot_deck != case.opponent_deck


@pytest.mark.parametrize("seat", ["player_a", "player_b"])
@pytest.mark.parametrize("deck", ["deck_a", "deck_b"])
@pytest.mark.parametrize("order", ["play", "draw"])
def test_factors_can_be_fixed_independently(tmp_path, seat, deck, order):
    decks = [tmp_path / "fixture-a.txt", tmp_path / "fixture-b.txt"]
    for path, contents in zip(decks, ("60 Plains", "60 Mountain"), strict=True):
        path.write_text(contents)
    taskset = XMageTaskset(
        XMageConfig(
            num_games=2,
            seed=41,
            deck_a=decks[0],
            deck_b=decks[1],
            pilot_seat=seat,
            pilot_deck=deck,
            pilot_play_order=order,
        )
    )
    tasks = [task.data for task in taskset]
    assert [data.seed for data in tasks] == [41, 42]
    for data in tasks:
        assert (data.pilot_seat, data.pilot_deck, data.pilot_play_order) == (
            seat,
            deck,
            order,
        )
        seated = dict(
            zip(("player_a", "player_b"), taskset.decks_for(data), strict=True)
        )
        assert seated[seat] == decks[0 if deck == "deck_a" else 1]
        assert (data.starting_player == seat) == (order == "play")


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


@pytest.mark.parametrize("discard_recordings", [True, False])
def test_baseline_preserves_audited_results_when_an_earlier_game_fails(
    tmp_path, monkeypatch, discard_recordings
):
    output = tmp_path / "baseline"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "build.json").write_text("{}")
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    infos = [
        {
            "seed": seed,
            "pilot_seat": "player_b",
            "pilot_deck": "deck_a",
            "opponent_deck": "deck_b",
            "pilot_play_order": "draw",
            "starting_player": "player_a",
        }
        for seed in (7, 8)
    ]

    class Taskset:
        config = XMageConfig()

        def __init__(self, config):
            pass

        def __iter__(self):
            return iter(SimpleNamespace(data=XMageData(**info)) for info in infos)

        def decks_for(self, data):
            return None, None

    monkeypatch.setattr(baseline, "XMageTaskset", Taskset)
    monkeypatch.setattr(baseline, "resolve_java", lambda _: "/bin/false")
    audited = Event()
    result = {
        "players": [
            {"name": "player_a", "won": False, "lost": True},
            {"name": "player_b", "won": True, "lost": False},
        ]
    }
    audit = {"privacy_passed": True, "decisions": 23}

    def run(recording, *, seed, **_):
        recording.mkdir()
        if seed == 7:
            assert audited.wait(timeout=10), "Later game never reached its audit"
            raise RuntimeError("Injected earlier-game failure")
        return result

    def verify(_):
        audited.set()
        return audit

    monkeypatch.setattr(baseline, "run", run)
    monkeypatch.setattr(baseline, "verify", verify)
    argv = ["baseline", "--output", str(output), "--workers", "2"]
    if discard_recordings:
        argv.append("--discard-recordings")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(RuntimeError, match="Injected earlier-game failure"):
        baseline.main()

    records = [
        json.loads(line) for line in (output / "games.jsonl").read_text().splitlines()
    ]
    expected = {
        **infos[1],
        "won": True,
        "lost": False,
        "game_result": result,
        "recording_audit": audit,
    }
    recording = output / "game-0001"
    if not discard_recordings:
        expected["recording_path"] = str(recording)
    assert records == [expected]
    assert recording.exists() == (not discard_recordings)
    assert (output / "game-0000").exists()
