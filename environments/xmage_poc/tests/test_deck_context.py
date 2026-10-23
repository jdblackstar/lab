import json

import pytest
from xmage_poc.decklist import deck_context
from xmage_poc.verify import verify


def test_registered_list_aggregates_copies_and_discards_order_and_comments():
    lines = [
        "# Opponent deck / filesystem metadata must not enter the context",
        " 20 Plains ",
        "",
        "4 Youthful Knight",
        "20 Plains",
        "16 Healer's Hawk",
    ]
    expected = {
        "player": "player_a",
        "deck_size": 60,
        "decklist": [
            {"name": "Healer's Hawk", "count": 16},
            {"name": "Plains", "count": 40},
            {"name": "Youthful Knight", "count": 4},
        ],
    }
    assert deck_context(lines, "player_a") == expected
    assert deck_context(list(reversed(lines)), "player_a") == expected


@pytest.mark.parametrize("leak", ["opponent_deck", "library_order"])
def test_audit_rejects_wrong_seat_or_hidden_information_in_deck_context(
    tmp_path, monkeypatch, leak
):
    (tmp_path / "internal").mkdir()
    (tmp_path / "players").mkdir()
    decks = {"deck_a": ["60 Plains"], "deck_b": ["60 Mountain"]}
    (tmp_path / "internal/manifest.json").write_text(json.dumps(decks))
    context = deck_context(decks["deck_a"], "player_a")
    if leak == "opponent_deck":
        context = deck_context(decks["deck_b"], "player_a")
    else:
        context["library_order"] = ["hidden-instance-id"]
    (tmp_path / "players/player_a.context.json").write_text(json.dumps(context))
    # Context validation must reject the disclosure before gameplay auditing.
    monkeypatch.setattr("xmage_poc.verify.read_lines", lambda _: [{}])
    with pytest.raises(AssertionError, match="Deck context differs"):
        verify(tmp_path)
