"""Answering a question set in batches. All data invented."""

import json

from menu_taste.batches import collect, make_batches, write_batches
from menu_taste.cloze import cloze_questions
from menu_taste.corpus import load_menus, sample_corpus_path
from menu_taste.questions import build, load_question_set, record, to_row
from menu_taste.scoring import report


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


def test_answers_written_per_batch_are_collected_and_scored(tmp_path):
    question_set = tmp_path / "questions.jsonl"
    build(str(sample_corpus_path()), str(question_set))
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
