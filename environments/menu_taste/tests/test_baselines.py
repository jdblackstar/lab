"""The no-taste baselines must catch a cue that gives the answer away. All data invented."""

import numpy as np
from menu_taste.baselines import FEATURES, cross_validated_choice_model, report
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
