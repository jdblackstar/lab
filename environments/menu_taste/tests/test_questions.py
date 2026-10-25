"""Frozen question sets, rotation, batching, and reading answers. All data invented."""

import json

import pytest
from menu_taste.cloze import LETTERS, cloze_questions
from menu_taste.corpus import load_menus, sample_corpus_path
from menu_taste.questions import (
    build,
    collect,
    load_question_set,
    make_batches,
    record,
    to_row,
    write_batches,
    write_sheet,
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


def test_a_person_answers_a_sampled_sheet_in_place_and_is_scored_like_a_run(
    question_set, tmp_path
):
    recs = {r["id"]: r for r in load_question_set(question_set)}
    sheet, n = write_sheet(str(question_set), str(tmp_path / "chef"), 5, rotation=1)
    again, _ = write_sheet(str(question_set), str(tmp_path / "again"), 5, rotation=1)
    assert n == 5 and sheet.read_text() == again.read_text()  # seeded
    ids = json.loads((sheet.parent / "manifest.json").read_text())["batches"][
        "sheet.md"
    ]
    sampled = [recs[i] for i in ids]
    for a in sampled:  # no question gives another away
        for b in sampled:
            if a is not b:
                assert b["info"]["menu_id"] not in a["related_menu_ids"]
                assert a["info"]["target"].lower() not in b["menu_text"].lower()
    text = sheet.read_text()
    assert "answer_index" not in text and text.count("<answer></answer>") == 2 * n

    # The person fills in the blanks: right on the first two, wrong after.
    for k, qid in enumerate(ids):
        right = to_row(recs[qid], 1)["answer"]
        letter = right if k < 2 else "ABCD"[("ABCD".index(right) + 1) % 4]
        before, after = text.split(f"### {qid}\n", 1)
        after = after.replace(
            "Your answer: <answer></answer>",
            f"Your answer: <answer>{letter}</answer>",
            1,
        )
        text = before + f"### {qid}\n" + after
    sheet.write_text(text)
    human = tmp_path / "human.jsonl"
    collect(str(sheet.parent), str(human))
    model = tmp_path / "model.jsonl"
    model.write_text(
        "".join(
            json.dumps(
                {
                    "id": i,
                    "rotation": 0,
                    "completion": f"<answer>{to_row(r, 0)['answer']}</answer>",
                }
            )
            + "\n"
            for i, r in recs.items()
        )
    )
    out = report(str(question_set), [str(human), str(model)], ["chef", "model"])
    assert f"| chef | 5 of {len(recs)} | 40.0% |" in out
    assert "| chef | model | 5 | 40% | -60.0% (" in out


def test_questions_every_run_got_wrong_the_same_way_are_written_out(
    question_set, tmp_path
):
    recs = load_question_set(question_set)
    k = len(recs[0]["options"])

    def run(name, pick):
        path = tmp_path / f"{name}.jsonl"
        rows = [
            {
                "id": r["id"],
                "rotation": 0,
                "completion": f"<answer>{LETTERS[pick(i, r)]}</answer>",
            }
            for i, r in enumerate(recs)
        ]
        path.write_text("".join(json.dumps(x) + "\n" for x in rows))
        return str(path)

    wrong = lambda r: (r["answer_index"] + 1) % k  # noqa: E731
    # Both runs pick the same wrong dish on questions 0-2; on 3 they're wrong with
    # different dishes; the rest b gets right.
    a = run("a", lambda i, r: wrong(r) if i < 4 else r["answer_index"])
    b = run(
        "b",
        lambda i, r: (
            wrong(r)
            if i < 3
            else (r["answer_index"] + 2) % k
            if i == 3
            else r["answer_index"]
        ),
    )
    sheet = tmp_path / "adjudicate.md"
    out = report(str(question_set), [a, b], agreed_wrong_out=str(sheet))
    assert f"same wrong dish on 3 of the {len(recs)} questions" in out
    text = sheet.read_text()
    assert text.count("\nVerdict:\n") == 3
    for r in recs[:3]:
        assert (
            f"{LETTERS[r['answer_index']]}. {r['options'][r['answer_index']]} (key: served)"
            in text
        )
        assert f"{LETTERS[wrong(r)]}. {r['options'][wrong(r)]} (all runs chose)" in text
    assert recs[3]["id"] not in text
