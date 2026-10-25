"""The no-taste baselines must catch a cue that gives the answer away. All data invented."""

import numpy as np
from menu_taste.baselines import (
    BEST,
    FEATURES,
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


def test_cooccurrence_ignores_the_menus_own_versions():
    from menu_taste.baselines import context, dish_cooccurrence
    from menu_taste.cloze import ClozeQuestion
    from menu_taste.schema import Menu

    def menu(menu_id, dishes):
        return Menu.model_validate(
            {
                "menu_id": menu_id,
                "kind": "event",
                "service": "plated",
                "sections": [
                    {"course": "main", "items": [{"name": d} for d in dishes]}
                ],
            }
        )

    target = menu("t", ["Roast duck", "Seared scallops", "Braised lamb"])
    version = menu("t2", ["Roast duck", "Seared scallops", "Pork chop"])
    other = menu("o", ["Grilled trout", "Seared scallops", "Short rib"])
    answer, wrong = target.sections[0].items[0], other.sections[0].items[0]
    cooc = dish_cooccurrence([target, version, other])

    def scores(related):
        q = ClozeQuestion(
            menu=target,
            section_idx=0,
            item_idx=0,
            options=(answer, wrong),
            option_menu_ids=("t", "o"),
            answer_index=0,
            related_menu_ids=related,
        )
        ctx = context(q)
        return cooc(answer, ctx), cooc(wrong, ctx)

    (answer_hits, _), (wrong_hits, _) = scores(("t", "t2"))
    assert answer_hits == 0 and wrong_hits > 0  # duck with scallops only in a version
    (answer_hits, _), _ = scores(("t",))
    assert answer_hits > 0
