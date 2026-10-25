"""Frozen question sets, rotation, and reading answers. All data invented."""

import json

import pytest
from menu_taste.corpus import sample_corpus_path
from menu_taste.questions import build, load_question_set, main, to_row
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


def test_build_cli_passes_corpus_settings_and_records_them(tmp_path):
    out = tmp_path / "desserts.jsonl"
    argv = ["build", str(sample_corpus_path()), "-o", str(out)]
    main([*argv, "--courses", "dessert", "--num-options", "3", "--max-per-dish", "0"])
    recs = load_question_set(out)
    assert recs and {r["info"]["course"] for r in recs} == {"dessert"}
    assert {len(r["options"]) for r in recs} == {3}
    params = json.loads(out.with_name("desserts.meta.json").read_text())["params"]
    assert params["courses"] == ["dessert"] and params["max_per_dish"] is None


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


def test_an_empty_run_reports_zero_answered(question_set, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    n = len(load_question_set(question_set))
    assert f"| empty | 0 of {n} | – | – | 0 |" in report(
        str(question_set), [str(empty)]
    )


@pytest.mark.parametrize("labels", [["a"], ["a", "a"]])
def test_labels_must_be_unique_and_one_per_run(question_set, tmp_path, labels):
    run = tmp_path / "run.jsonl"
    run.write_text("")
    with pytest.raises(ValueError, match="one unique label per run"):
        report(str(question_set), [str(run), str(run)], labels)
