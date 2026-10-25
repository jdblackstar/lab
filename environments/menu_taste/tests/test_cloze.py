from menu_taste.cloze import LETTERS, build_cloze_items, dish_tokens, same_dish
from menu_taste.corpus import load_menus, sample_corpus_path
from menu_taste.schema import Menu


def _sample():
    return load_menus(sample_corpus_path())


def _menu(menu_id, dishes_by_course, kind="event"):
    return Menu.model_validate(
        {
            "menu_id": menu_id,
            "kind": kind,
            "service": "plated",
            "sections": [
                {
                    "course": course,
                    "items": [
                        d if isinstance(d, dict) else {"name": d} for d in dishes
                    ],
                }
                for course, dishes in dishes_by_course.items()
            ],
        }
    )


def test_answer_letter_points_at_the_removed_dish():
    rows = build_cloze_items(_sample())
    assert rows
    for row in rows:
        info = row["info"]
        assert info["options"][LETTERS.index(row["answer"])] == info["target"]
        assert "[MISSING DISH]" in row["question"]
        # The removed dish must not still appear in the rendered menu.
        menu_part = row["question"].split("<menu>")[1].split("</menu>")[0]
        assert f"- {info['target']}" not in menu_part


def test_distractors_come_from_other_menus_and_differ_from_every_dish_on_the_menu():
    menus = {m.menu_id: m for m in _sample()}
    for row in build_cloze_items(list(menus.values())):
        info = row["info"]
        target_menu = menus[info["menu_id"]]
        assert info["menu_id"] not in info["distractor_menu_ids"]
        menu_dishes = [dish_tokens(i.name) for i in target_menu.items()]
        for name in info["options"]:
            if name == info["target"]:
                continue
            assert not any(same_dish(dish_tokens(name), t) for t in menu_dishes), name


def test_catalogs_are_neither_questions_nor_distractor_sources():
    menus = _sample()
    catalog_ids = {m.menu_id for m in menus if m.kind.value == "catalog"}
    assert catalog_ids
    for row in build_cloze_items(menus):
        assert row["info"]["menu_id"] not in catalog_ids
        assert not catalog_ids & set(row["info"]["distractor_menu_ids"])


def test_versions_of_the_same_menu_do_not_supply_distractors():
    # "original" and "revised" share most dishes; the revision swaps one dessert.
    original = _menu(
        "original",
        {
            "main": ["Roast duck", "Seared scallops", "Braised lamb"],
            "dessert": ["Plum tart"],
        },
    )
    revised = _menu(
        "revised",
        {
            "main": ["Roast duck", "Seared scallops", "Braised lamb"],
            "dessert": ["Fig galette"],
        },
    )
    others = [
        _menu(f"other{i}", {"main": [m], "dessert": [d]})
        for i, (m, d) in enumerate(
            [
                ("Pork chop", "Lemon posset"),
                ("Trout", "Chocolate mousse"),
                ("Ribeye", "Rice pudding"),
            ]
        )
    ]
    rows = build_cloze_items([original, revised, *others], num_options=4)
    for row in rows:
        if row["info"]["menu_id"] == "original":
            assert "revised" not in row["info"]["distractor_menu_ids"]
    assert any(
        r["info"]["menu_id"] == "original" and r["info"]["course"] == "dessert"
        for r in rows
    )


def test_skips_slots_without_enough_distractors():
    menus = [_menu("a", {"main": ["Roast duck"]}), _menu("b", {"main": ["Trout"]})]
    assert build_cloze_items(menus, num_options=3, min_menu_items=1) == []
    assert len(build_cloze_items(menus, num_options=2, min_menu_items=1)) == 2


def test_small_menus_are_not_asked_about_but_still_supply_wrong_options():
    big = _menu(
        "big",
        {"main": ["Roast duck", "Seared scallops"], "dessert": ["Plum tart", "Sorbet"]},
    )
    small = [
        _menu(f"s{i}", {"dessert": [d]})
        for i, d in enumerate(["Lemon posset", "Rice pudding", "Baklava"])
    ]
    rows = build_cloze_items([big, *small], num_options=4, min_menu_items=4)
    assert {r["info"]["menu_id"] for r in rows} == {"big"}
    assert any(
        set(r["info"]["distractor_menu_ids"]) == {"s0", "s1", "s2"} for r in rows
    )


def test_max_menus_limits_which_menus_are_asked_about():
    menus = _sample()
    rows = build_cloze_items(menus, max_menus=3, seed=5)
    assert len({r["info"]["menu_id"] for r in rows}) == 3
    assert rows == build_cloze_items(menus, max_menus=3, seed=5)


def test_seed_is_deterministic_and_changes_option_order():
    menus = _sample()
    a, b = build_cloze_items(menus, seed=1), build_cloze_items(menus, seed=1)
    assert a == b
    c = build_cloze_items(menus, seed=2)
    assert [r["answer"] for r in a] != [r["answer"] for r in c]


def test_drinks_only_when_requested():
    menus = _sample()
    drink = {
        "cocktail",
        "wine",
        "beer",
        "spirits",
        "non_alcoholic",
        "coffee_tea",
        "bar_service",
    }
    assert not any(r["info"]["course"] in drink for r in build_cloze_items(menus))
    assert any(
        r["info"]["course"] in drink
        for r in build_cloze_items(menus, include_drinks=True)
    )


def test_a_staple_on_many_menus_answers_at_most_max_per_dish_questions():
    others = [
        "Roast duck",
        "Seared trout",
        "Braised lamb",
        "Grilled quail",
        "Pork chop",
        "Lobster roll",
        "Short rib",
        "Halibut",
        "Chicken thigh",
        "Flank steak",
    ]
    menus = [
        _menu(
            f"m{i}",
            {"salad": ["Caesar salad"], "main": [others[2 * i], others[2 * i + 1]]},
        )
        for i in range(5)
    ]

    def asked(**kw):
        rows = build_cloze_items(menus, num_options=2, min_menu_items=3, **kw)
        return sum(r["info"]["target"] == "Caesar salad" for r in rows)

    assert asked(max_per_dish=None) == 0  # every other salad is the same dish
    menus += [
        _menu(f"s{i}", {"salad": [s]}) for i, s in enumerate(["Beet salad", "Wedge"])
    ]
    assert asked(max_per_dish=None) == 5
    assert asked(max_per_dish=2) == 2


def test_wrong_options_match_whether_the_answer_has_a_description():
    described = [
        {"name": n, "description": "with brown butter"}
        for n in ["Plum tart", "Fig galette", "Pear crisp", "Quince cake"]
    ]
    bare = ["Lemon posset", "Rice pudding", "Baklava", "Sorbet", "Panna cotta", "Flan"]
    target = _menu(
        "t",
        {
            "main": ["Roast duck", "Seared scallops", "Hanger steak"],
            "dessert": [described[0]],
        },
    )
    pool = [
        _menu(f"d{i}", {"dessert": [d]}) for i, d in enumerate(described[1:] + bare)
    ]

    def distractors(match_surface):
        rows = build_cloze_items(
            [target, *pool],
            courses=frozenset({"dessert"}),
            match_surface=match_surface,
            seed=3,
        )
        (row,) = [r for r in rows if r["info"]["menu_id"] == "t"]
        return set(row["info"]["options"]) - {"Plum tart"}

    assert distractors(True) == {"Fig galette", "Pear crisp", "Quince cake"}
    assert any(d in bare for d in distractors(False))


def test_wrong_options_come_only_from_the_menus_own_caterer():
    # Caterer "a" has just enough desserts for a question with three options; "b" has
    # plenty. Without the restriction, b's desserts would fill a's questions.
    def menus(caterer, dishes):
        out = []
        for i, (main, dessert) in enumerate(dishes):
            m = _menu(f"{caterer}{i}", {"main": [main], "dessert": [dessert]})
            out.append(m.model_copy(update={"caterer": caterer}))
        return out

    a = menus("a", [("Roast duck", "Plum tart"), ("Trout", "Fig galette")])
    a += menus("a", [("Ribeye", "Lemon posset")])
    b = menus(
        "b",
        [
            ("Pork chop", "Baklava"),
            ("Quail", "Sorbet"),
            ("Halibut", "Flan"),
            ("Short rib", "Panna cotta"),
        ],
    )
    caterer = {m.menu_id: m.caterer for m in a + b}
    rows = build_cloze_items(a + b, num_options=3, min_menu_items=2)
    assert {r["info"]["caterer"] for r in rows} == {"a", "b"}
    for row in rows:
        info = row["info"]
        assert {caterer[m] for m in info["distractor_menu_ids"]} == {info["caterer"]}
        assert "other menus by this menu's caterer." in row["question"]
    # Unlabeled menus are one caterer: the same corpus without labels mixes them.
    unlabeled = [m.model_copy(update={"caterer": None}) for m in a + b]
    mixed = build_cloze_items(unlabeled, num_options=3, min_menu_items=2)
    assert all("other menus by the same caterer." in r["question"] for r in mixed)
    assert any(
        {caterer[m] for m in r["info"]["distractor_menu_ids"]} == {"a", "b"}
        for r in mixed
    )
