"""The no-taste baselines must catch a cue that gives the answer away. All data invented."""

import numpy as np
from menu_taste.baselines import (
    BEST,
    FEATURES,
    bar,
    cross_validated_choice_model,
    report,
    report_numbers,
)
from menu_taste.cloze import cloze_questions
from menu_taste.corpus import load_menus, sample_corpus_path


def test_choice_model_finds_a_planted_cue_only_on_held_out_menus():
    rng = np.random.default_rng(0)
    n, k = 400, 4
    X = rng.normal(size=(n, k, len(FEATURES)))
    y = rng.integers(0, k, size=n)
    groups = [f"m{i // 4}" for i in range(n)]

    pred, _ = cross_validated_choice_model(X, y, groups)
    assert (pred == y).mean() < 0.35  # noise: about chance

    X[np.arange(n), y, FEATURES.index("popularity")] += (
        2.0  # the answer is the common dish
    )
    pred, weights = cross_validated_choice_model(X, y, groups)
    assert (pred == y).mean() > 0.6
    assert np.argmax(np.abs(weights)) == FEATURES.index("popularity")


def test_report_runs_on_the_sample_corpus():
    menus = load_menus(sample_corpus_path())
    text = report(cloze_questions(menus), menus)
    assert "most words shared with the menu" in text
    assert "best combination of all cues" in text


def test_one_menu_has_no_held_out_combination_score():
    menus = load_menus(sample_corpus_path())
    first = menus[0].menu_id
    questions = [q for q in cloze_questions(menus) if q.menu.menu_id == first]
    assert questions
    assert BEST not in report_numbers(questions, menus)
    assert f"| {BEST} | unavailable" in report(questions, menus)


def test_the_bar_is_the_higher_of_the_best_cue_and_the_combination():
    def row(accuracy):
        return {"accuracy": accuracy, "low": 0.0, "high": 1.0}

    numbers = {
        "random guess": row(0.40),  # luck, not a cue
        "most words shared with the menu": row(0.30),
        "most common dish in the corpus": row(0.33),
        BEST: row(0.26),
    }
    assert bar(numbers) == ["most common dish in the corpus", BEST]
    numbers[BEST] = row(0.45)
    assert bar(numbers) == [BEST, "most common dish in the corpus"]
