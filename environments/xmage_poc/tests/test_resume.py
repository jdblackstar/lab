import json
import os
import shutil
import subprocess

import pytest
from xmage_poc.positions import at_boundary, label, resumable
from xmage_poc.transport import ROOT, run
from xmage_poc.verify import read_lines


def candidate(index, outcomes):
    wins, draws = outcomes.count("W"), outcomes.count("D")
    decided = len(outcomes) - outcomes.count("E")
    return {
        "candidate": index,
        "outcomes": outcomes,
        "win_rate": (wins + 0.5 * draws) / decided,
    }


def test_label_needs_a_paired_margin_over_every_alternative():
    # Same win rates, different pairing: candidate 1 wins only in worlds where
    # candidate 0 also wins in the first result, and in other worlds in the second.
    best = "W" * 12 + "L" * 4
    consistent = {"candidates": [candidate(0, best), candidate(1, "W" * 6 + "L" * 10)]}
    crossed = {"candidates": [candidate(0, best), candidate(1, "L" * 10 + "W" * 6)]}
    assert label(consistent, z=2)["answer"] == 0
    assert label(crossed, z=2)["answer"] is None
    # The best must clear the closest alternative, not just the average one.
    close = {
        "candidates": [
            candidate(0, "WWWWWWWW"),
            candidate(1, "LLLLLLLL"),
            candidate(2, "WWWWWWWL"),
        ]
    }
    verdict = label(close, z=2)
    assert verdict["answer"] is None and verdict["runner_up"] == 2


def test_empty_stack_boundary_skips_responses_and_unresumable_prompts():
    def obs(stack, kinds=("cast", "pass"), query="SELECT"):
        return {
            "query_type": query,
            "view": {"stack": stack},
            "actions": [{"kind": k} for k in kinds],
        }

    responding = obs({"spell-id": {"name": "Shock"}})
    assert at_boundary(obs({}), "empty-stack")
    assert not at_boundary(responding, "empty-stack")
    assert at_boundary(responding, "any")
    assert not at_boundary(obs({}, query="PICK_TARGET"), "any")
    assert not at_boundary(obs({}, kinds=("remove_attacker", "pass")), "empty-stack")


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    output = tmp_path_factory.mktemp("resume") / "game"
    result = run(output, seed=7, java_bin=os.environ.get("XMAGE_JAVA_BIN"))
    assert result["ended"] and result["errors"] == 0
    return output


def bridge(*args):
    java = os.environ.get("XMAGE_JAVA_BIN") or shutil.which("java")
    command = [
        java,
        "-Xmx1g",
        "-cp",
        str(ROOT / "runtime/xmage-poc.jar"),
        "lab.xmage.PocMain",
    ]
    result = subprocess.run(
        command + [str(a) for a in args], capture_output=True, text=True, timeout=900
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return [json.loads(line) for line in result.stdout.splitlines()]


@pytest.mark.skipif(
    os.environ.get("XMAGE_INTEGRATION") != "1",
    reason="Set XMAGE_INTEGRATION=1 with the XMage runtime installed and Java 21",
)
def test_resumed_checkpoints_replay_every_later_decision_and_event(recording):
    decisions = read_lines(recording / "internal/decisions.jsonl")
    late = [d for d in reversed(decisions) if resumable(d["observation"])]

    def last(predicate):
        return next(d["decision"] for d in late if predicate(d["observation"]))

    picks = {
        last(lambda o: o["message"].startswith("Select attackers")),
        last(lambda o: o["message"].startswith("Select blockers")),
        last(lambda o: o["view"]["step"] == "COMBAT_DAMAGE"),
        last(
            lambda o: len(o["actions"]) > 1 and not o["message"].startswith("Select ")
        ),
    }
    reports = bridge("replay", recording, *sorted(picks))
    assert len(reports) == 4
    for report in reports:
        assert report["faithful"], report
        assert report["matched_events"] == report["expected_events"] > 0
    # A selection already in progress is not re-asked, so it is not resumable.
    partial = next(
        d
        for d in decisions
        if any(a["kind"].startswith("remove_") for a in d["observation"]["actions"])
    )
    assert not resumable(partial["observation"])
    assert not bridge("replay", recording, partial["decision"])[0]["resumable"]


@pytest.mark.skipif(
    os.environ.get("XMAGE_INTEGRATION") != "1",
    reason="Set XMAGE_INTEGRATION=1 with the XMage runtime installed and Java 21",
)
def test_rollouts_force_each_candidate_on_the_recorded_position(recording):
    decision = next(
        d
        for d in reversed(read_lines(recording / "internal/decisions.jsonl"))
        if resumable(d["observation"])
        and len(d["observation"]["actions"]) > 1
        and not d["observation"]["message"].startswith("Select ")
    )
    args = ("rollout", recording, decision["decision"], "--playouts=2", "--seed=3")
    first, again = bridge(*args)[0], bridge(*args)[0]
    assert first["checks"]["seat_view_matches"] and first["checks"]["sources_match"]
    labels = [c["ref_label"] for c in first["candidates"]]
    assert labels[-1] == "Pass priority" and len(labels) == len(set(labels)) > 1
    for c in first["candidates"]:
        assert len(c["outcomes"]) == 2 and "E" not in c["outcomes"]

    def timeless(result):
        return [
            {k: v for k, v in c.items() if k != "seconds"} for c in result["candidates"]
        ]

    assert timeless(first) == timeless(again)
