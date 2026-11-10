"""Spreadsheet rows of (title, description) pairs with headers inline. All data invented."""

from menu_taste.ingest.grid import (
    import_grid,
    load_scrub_terms,
    parse_dietary,
    parse_row,
)
from menu_taste.schema import (
    Course,
    Dietary,
    ItemRole,
    MenuKind,
    SelectionMode,
    ServiceStyle,
)


def _row(*cells):
    pairs = [(c, "") if isinstance(c, str) else c for c in cells]
    return pairs + [("", "")] * (20 - len(pairs))


def _sections(menu):
    return [(s.course, [i.name for i in s.items]) for s in menu.sections]


def test_headers_split_the_row_into_courses_with_service_and_choice():
    menu, _ = parse_row(
        _row(
            "PASSED HORS D'OEUVRES",
            ("Duck Rillettes (DF)", "cherry mostarda"),
            "Beet Tartare (VG/GF)",
            "SALAD COURSE: Frisée Salad (V)",
            "PLATED CHOICE OF ENTREES",
            ("Halibut (GF)", "leeks"),
            "Pork Chop",
            "VEGETARIAN OPTION",
            "Squash Risotto (V)",
            "Sourdough Bread, Local Bakery",
            "Dessert Bar",
            "Apricot Linzer Bar (GF)",
        ),
        menu_id="m",
    )
    assert _sections(menu) == [
        (Course.hors_doeuvres, ["Duck Rillettes", "Beet Tartare"]),
        (Course.salad, ["Frisée Salad"]),
        (Course.main, ["Halibut", "Pork Chop"]),
        (Course.main, ["Squash Risotto"]),
        (Course.dessert, ["Apricot Linzer Bar"]),
        (Course.bread, ["Sourdough Bread, Local Bakery"]),
    ]
    passed, _, entrees, veg, dessert, bread = menu.sections
    assert (
        passed.service is ServiceStyle.passed
        and passed.items[0].description == "cherry mostarda"
    )
    assert passed.items[1].dietary == [Dietary.vegan, Dietary.gluten_free]
    assert (
        entrees.selection is SelectionMode.guest_choice
        and entrees.service is ServiceStyle.plated
    )
    assert veg.items[0].role is ItemRole.dietary_alternate
    assert (
        bread.items[0].role is ItemRole.standard
    )  # not an alternate just because it came after one
    assert dessert.service is ServiceStyle.stations
    assert menu.kind is MenuKind.event and menu.service is ServiceStyle.plated


def test_things_the_caterer_did_not_serve_are_left_out():
    menu, _ = parse_row(
        _row(
            "FAMILY STYLE MAIN COURSE",
            "Grilled Hanger Steak",
            ("Pasta Alla Norma (extra side not priced in, tasting only)", ""),
            ("Wedding Cake", "Provided by client; cut and served by us"),
            "VENDOR MEALS",
            "Turkey Sandwich",
            "LATE NIGHT SNACK",
            ("Late night bites", "selection tbd"),
            "Staff Meal",
            ("Cheese Display", "Provided by Jordan Example"),
            ("Late Night Tacos", "client to source tortillas"),
            "++",
        ),
        menu_id="m",
    )
    assert [i.name for i in menu.items()] == ["Grilled Hanger Steak"]
    assert menu.event.event_type.value == "wedding"
    assert menu.service is ServiceStyle.family_style


def test_choose_n_over_a_longer_list_is_a_proposal_but_over_n_dishes_is_the_choice():
    chosen, _ = parse_row(
        _row(
            ("SMALL BITES", "Choose 2."),
            "Gougeres",
            "Oysters",
            "MAIN COURSE",
            "Roast Chicken",
        ),
        menu_id="a",
    )
    offered, _ = parse_row(
        _row(
            ("SMALL BITES", "Choose 2."),
            "Gougeres",
            "Oysters",
            "Arancini",
            "MAIN COURSE",
            "Roast Chicken",
        ),
        menu_id="b",
    )
    assert chosen.kind is MenuKind.event
    assert offered.kind is MenuKind.catalog
    assert offered.sections[0].selection is SelectionMode.host_choice
    assert offered.sections[0].select_count == 2


def test_dish_names_that_contain_header_words_stay_dishes():
    menu, _ = parse_row(
        _row(
            "Breakfast Kolaches",
            "Walnut Pie Bar",
            "Speck Flat Bread",
            "Late Night Snack",
            "Fries",
        ),
        menu_id="m",
    )
    by_course = {s.course: [i.name for i in s.items] for s in menu.sections}
    assert by_course[Course.late_night] == ["Fries"]
    assert by_course[Course.dessert] == ["Walnut Pie Bar"]
    assert sorted(by_course[Course.other]) == [
        "Breakfast Kolaches",
        "Speck Flat Bread",
    ]


def test_sides_listed_with_entrees_become_their_own_course():
    menu, _ = parse_row(
        _row(
            "FAMILY STYLE MAIN COURSE",
            "Roast Chicken",
            "Potato Pavé",
            "Grilled Salmon",
        ),
        menu_id="m",
    )
    assert _sections(menu) == [
        (Course.main, ["Roast Chicken", "Grilled Salmon"]),
        (Course.side, ["Potato Pavé"]),
    ]


def test_parse_dietary_only_strips_tag_groups():
    assert parse_dietary("Chocolate Tart (GF/VG)") == (
        "Chocolate Tart",
        [Dietary.gluten_free, Dietary.vegan],
    )
    assert parse_dietary("Eggplant (AF)") == ("Eggplant", [])
    assert parse_dietary("Clams (Manila)") == ("Clams (Manila)", [])


def test_import_scrubs_listed_names_and_skips_duplicate_rows(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    row = [
        "SMALL BITES",
        "",
        "Smoked Sturgeon Rillette",
        "from Acme Smokehouse",
        "Country Bread, Acme Bakery",
        "",
    ]
    wb.active.append(row)
    wb.active.append(row)
    wb.active.append(["Catered by Acme Catering Co.", ""])
    path = tmp_path / "menus.xlsx"
    wb.save(path)
    scrub = tmp_path / "scrub.txt"
    scrub.write_text("# private\nAcme Catering Co.\nAcme Bakery\nAcme Smokehouse\n")

    menus, report = import_grid(path, scrub_file=scrub, pair_columns=3)
    assert report["exact duplicate rows skipped"] == 1
    text = " ".join(m.model_dump_json() for m in menus)
    assert "Acme" not in text
    first = menus[0]
    assert [(i.name, i.description) for i in first.items()] == [
        ("Smoked Sturgeon Rillette", None),
        ("Country Bread", None),
    ]
    assert len(load_scrub_terms(scrub)) == 3


def test_dishes_that_name_another_course_leave_an_entree_list_without_headers():
    menu, _ = parse_row(
        _row(
            "CHOICE OF ENTREE:",
            ("Roast Quail", "romesco (GF/DF)"),
            "Lentil Stew (VG)",
            "Market Greens Salad",
            "Oatmeal Cookies",
            "Shrimp Louie Salad",
        ),
        menu_id="m",
    )
    by_course = {s.course: [i.name for i in s.items] for s in menu.sections}
    assert by_course[Course.main] == [
        "Roast Quail",
        "Lentil Stew",
        "Shrimp Louie Salad",
    ]
    assert by_course[Course.salad] == ["Market Greens Salad"]
    assert by_course[Course.dessert] == ["Oatmeal Cookies"]
    chicken = menu.sections[0].items[0]
    assert (chicken.description, chicken.dietary) == (
        "romesco",
        [Dietary.gluten_free, Dietary.dairy_free],
    )


def test_a_plate_for_one_person_is_an_alternate():
    menu, _ = parse_row(
        _row(
            "MAIN COURSE",
            "Roast Chicken",
            "Seared Scallops (HOST ONLY)",
            "Grilled Trout",
        ),
        menu_id="m",
    )
    roles = {i.name: i.role for i in menu.items()}
    assert roles == {
        "Roast Chicken": ItemRole.standard,
        "Seared Scallops": ItemRole.dietary_alternate,
        "Grilled Trout": ItemRole.standard,
    }


def test_a_station_is_a_sub_header_inside_its_course():
    menu, _ = parse_row(
        _row(
            "PASSED HORS D'OEUVRES",
            "Gougeres",
            ("Dumpling Station", "pork, chive, and mushroom"),
            "Pork Dumpling",
            "Mushroom Dumpling",
            "DESSERT",
            "Plum Galette",
        ),
        menu_id="m",
    )
    assert _sections(menu) == [
        (Course.hors_doeuvres, ["Gougeres"]),
        (Course.hors_doeuvres, ["Pork Dumpling", "Mushroom Dumpling"]),
        (Course.dessert, ["Plum Galette"]),
    ]
    assert menu.sections[1].service is ServiceStyle.stations
    assert "Dumpling Station" not in [i.name for i in menu.items()]


def test_parse_dietary_reads_star_tags():
    assert parse_dietary("Citrus Herb Salad *GF") == (
        "Citrus Herb Salad",
        [Dietary.gluten_free],
    )


def test_a_station_with_nothing_listed_under_it_is_the_dish():
    menu, _ = parse_row(
        _row(
            "DESSERT",
            ("Gelato Station", "three flavors in mini glasses"),
            ("Gyro Station", "lamb and chicken gyros"),
            ("Included with the Gyro Station", "pita, tzatziki"),
            "Coffee and Tea Station",
        ),
        menu_id="m",
    )
    assert [i.name for i in menu.items()] == [
        "Gelato Station",
        "Gyro Station",
        "Coffee and Tea Station",
    ]


def test_import_reads_every_sheet_and_names_only_later_ones(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["SMALL BITES", "", "Deviled Eggs", "chive"])
    wb.create_sheet().append(["DESSERT", "", "Lemon Tart", "meringue"])
    path = tmp_path / "menus.xlsx"
    wb.save(path)

    menus, _ = import_grid(path, pair_columns=2)
    assert [m.menu_id.split("-", 1)[1] for m in menus] == ["r1", "s2-r1"]
    assert [next(m.items()).name for m in menus] == ["Deviled Eggs", "Lemon Tart"]


def test_boards_and_platters_under_a_passed_header_are_a_display():
    menu, _ = parse_row(
        _row(
            "PASSED CANAPES",
            ("Seared Scallop", "romesco"),
            ("Local Cheese Board (V)", "honeycomb, crackers"),
            "Gougeres",
            "Crudités Platter (VG/GF)",
            "PLATED DINNER",
            "Roast Chicken",
        ),
        menu_id="m",
    )
    assert _sections(menu) == [
        (Course.hors_doeuvres, ["Seared Scallop", "Gougeres"]),
        (Course.display, ["Local Cheese Board", "Crudités Platter"]),
        (Course.main, ["Roast Chicken"]),
    ]
    passed, display, _ = menu.sections
    assert passed.service is ServiceStyle.passed
    assert display.service is ServiceStyle.display
    assert display.items[0].dietary == [Dietary.vegetarian]
