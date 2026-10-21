"""Frozen question sets, rotation, batching, and reading answers. All data invented."""

import json

import pytest
from menu_taste.cloze import cloze_questions
from menu_taste.corpus import load_menus, sample_corpus_path
from menu_taste.questions import (
    build,
    collect,
    load_question_set,
    make_batches,
    record,
    to_row,
    write_batches,
)
from menu_taste.scoring import extract_letter, grade, report


@pytest.mark.parametrize(
    "text, expected",
    [
        ("<answer>B</answer>", "B"),
        ("<answer>b.</answer>", "B"),
        ("<answer>(B)</answer>", "B"),
        ("<answer>**B**</answer>", "B"),
        ("<answer>B) Plum tart</answer>", "B"),
        ("<answer> Option B </answer>", "B"),
        ("<answer>A</answer> no, wait: <answer>C</answer>", "C"),
        ("<answer>Plum tart</answer>", None),
        ("<answer>E</answer>", None),
        ("The answer is B", None),
    ],
)
def test_extract_letter(text, expected):
    assert extract_letter(text, 4) == expected


@pytest.fixture(scope="module")
def question_set(tmp_path_factory):
    out = tmp_path_factory.mktemp("q") / "questions.jsonl"
    build(str(sample_corpus_path()), str(out))
    return out


def test_build_is_deterministic_and_records_baselines(question_set, tmp_path):
    again = tmp_path / "again.jsonl"
    build(str(sample_corpus_path()), str(again))
    assert again.read_text() == question_set.read_text()
    meta = json.loads(question_set.with_name("questions.meta.json").read_text())
    assert meta["questions"] == len(load_question_set(question_set))
    assert "best combination of all cues (held-out menus)" in meta["baselines"]


def test_rotation_moves_the_answer_with_the_options(question_set):
    rec = load_question_set(question_set)[0]
    right = rec["options"][rec["answer_index"]]
    for r in range(4):
        row = to_row(rec, r)
        letter = row["answer"]
        assert f"{letter}. {right}" in row["question"]


def test_a_rotated_run_is_graded_against_the_original_order(question_set):
    recs = {r["id"]: r for r in load_question_set(question_set)}
    rec = next(iter(recs.values()))
    run = [
        {
            "id": rec["id"],
            "rotation": r,
            "completion": f"<answer>{to_row(rec, r)['answer']}</answer>",
        }
        for r in range(4)
    ]
    graded = grade(recs, run)
    assert all(g["correct"] for g in graded)
    assert {g["chosen"] for g in graded} == {rec["answer_index"]}


def test_batches_never_pair_questions_that_reveal_each_other():
    menus = load_menus(sample_corpus_path())
    records = [record(q) for q in cloze_questions(menus)]
    batches = make_batches(records, size=6)
    assert sorted(r["id"] for b in batches for r in b) == sorted(
        r["id"] for r in records
    )
    for batch in batches:
        for a in batch:
            for b in batch:
                if a is b:
                    continue
                assert b["info"]["menu_id"] not in a["related_menu_ids"]
                assert a["info"]["target"].lower() not in b["menu_text"].lower()


def test_answers_written_per_batch_are_collected_and_scored(question_set, tmp_path):
    run_dir = tmp_path / "run"
    paths = write_batches(
        str(question_set), str(run_dir), 5, rotation=1, limit=None, seed=0
    )
    recs = {r["id"]: r for r in load_question_set(question_set)}
    manifest = json.loads((run_dir / "manifest.json").read_text())
    ids = manifest["batches"][paths[0].name]
    # The first batch answers everything right; the rest are never answered.
    text = "".join(
        f"### {i}\nfits\n<answer>{to_row(recs[i], 1)['answer']}</answer>\n" for i in ids
    )
    (run_dir / paths[0].name.replace("batch-", "answers-")).write_text(text)
    assert "answer_index" not in paths[0].read_text()

    out = tmp_path / "run.jsonl"
    assert collect(str(run_dir), str(out)) == {
        "answered": len(ids),
        "missing": len(recs) - len(ids),
    }
    text = report(str(question_set), [str(out)], ["run"])
    assert f"| run | {len(ids)} of {len(recs)} | 100.0% |" in text
