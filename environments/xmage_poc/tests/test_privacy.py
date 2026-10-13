import copy

import pytest
from xmage_poc.verify import audit_observation


def boundary():
    state = {
        "players": [
            {
                "id": "a",
                "life": 20,
                "hand": [{"id": "own-card"}],
                "library": [{"id": "own-hidden-card"}],
            },
            {
                "id": "b",
                "life": 19,
                "hand": [{"id": "opponent-hidden-card"}],
                "library": [{"id": "opponent-library-card"}],
            },
        ]
    }
    observation = {
        "player_id": "a",
        "view": {
            "myHand": {"own-card": {"name": "Plains"}},
            "opponentHands": {},
            "watchedHands": {},
            "players": [
                {
                    "playerId": p["id"],
                    "life": p["life"],
                    "handCount": 1,
                    "libraryCount": 1,
                    "sideboard": {},
                }
                for p in state["players"]
            ],
        },
        "actions": [{"index": 0, "label": "Pass"}],
    }
    return observation, state


@pytest.mark.parametrize(
    "hidden", ["own-hidden-card", "opponent-hidden-card", "opponent-library-card"]
)
@pytest.mark.parametrize("location", ["action", "message"])
def test_reject_hidden_ids_including_embedded_text(hidden, location):
    observation, state = boundary()
    audit_observation(observation, state)
    leaked = copy.deepcopy(observation)
    if location == "action":
        leaked["actions"][0]["value"] = hidden
    else:
        leaked["message"] = f"Choose <span id='{hidden}'>card</span>"
    with pytest.raises(AssertionError, match="Hidden card identifiers"):
        audit_observation(leaked, state)


def test_reject_wrong_own_hand():
    observation, state = boundary()
    observation["view"]["myHand"] = {}
    with pytest.raises(AssertionError, match="Own hand"):
        audit_observation(observation, state)


def test_reject_false_public_counts():
    observation, state = boundary()
    observation["view"]["players"][1]["libraryCount"] = 42
    with pytest.raises(AssertionError):
        audit_observation(observation, state)


def test_reject_internal_manifest_in_prompt():
    observation, state = boundary()
    observation["deck_b"] = ["60 secret cards"]
    with pytest.raises(AssertionError, match="Internal recording"):
        audit_observation(observation, state)


def test_audit_still_rejects_leaks_with_python_optimization():
    import subprocess
    import sys

    code = (
        "from xmage_poc.verify import audit_observation; "
        "audit_observation({'player_id':'a','view':{'myHand':{},'players':[{'playerId':'a'}]}}, "
        "{'players':[{'id':'a','hand':[{'id':'missing-card'}]}]})"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", code], check=False, capture_output=True, text=True
    )
    assert result.returncode != 0 and "Own hand" in result.stderr
