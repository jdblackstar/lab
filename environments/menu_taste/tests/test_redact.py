import pytest
from menu_taste.ingest.redact import flags, redact_menu, scrub
from menu_taste.schema import Menu


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Seared scallops $18", "Seared scallops"),
        ("Beef tenderloin crostini $4.50 per piece", "Beef tenderloin crostini"),
        ("Plated dinner 125++", "Plated dinner"),
        ("Raw bar 32 per person", "Raw bar"),
        ("Burrata, peaches · 14.00", "Burrata, peaches"),
        ("Lobster (MP)", "Lobster"),
        ("Questions? events@example.com or (212) 555-0199", "Questions? or"),
    ],
)
def test_scrub_removes_prices_and_contacts(text, expected):
    assert scrub(text)[0] == expected


@pytest.mark.parametrize(
    "dish",
    [
        "72-hour short rib",
        "Five-spice duck breast",
        "1/2 dozen Kumamoto oysters",
        "Tomato salad, 3 ways",
        "Chocolate 70% torte",
        "Dry-aged 40 days ribeye",
    ],
)
def test_scrub_keeps_numbers_that_belong_to_dishes(dish):
    assert scrub(dish) == (dish, 0)


@pytest.mark.parametrize(
    "text",
    [
        "The Goldberg Wedding",
        "Sarah & James's wedding dinner",
        "In honor of Margaret",
        "Dinner for Mrs. Alvarez",
        "Jack's 40th birthday",
    ],
)
def test_client_details_are_flagged(text):
    assert flags(text)


def test_dish_names_are_not_flagged():
    for text in [
        "Beef Wellington",
        "Chicken Marbella",
        "Lobster Thermidor",
        "Spring Garden Wedding",
    ]:
        assert not flags(text), text


def test_redact_menu_cleans_every_text_field_and_records_warnings():
    menu = Menu.model_validate(
        {
            "menu_id": "m",
            "kind": "event",
            "service": "plated",
            "title": "The Goldberg Wedding",
            "notes": ["Call 212-555-0199 with changes"],
            "sections": [
                {
                    "course": "main",
                    "heading": "Entrées $85 per person",
                    "items": [
                        {
                            "name": "Halibut",
                            "description": "peas, morels $12",
                            "pairing": "Chablis $60",
                        }
                    ],
                }
            ],
        }
    )
    out = redact_menu(menu)
    item = out.sections[0].items[0]
    assert (out.sections[0].heading, item.description, item.pairing) == (
        "Entrées",
        "peas, morels",
        "Chablis",
    )
    assert out.notes == ["Call with changes"]
    assert any("family name" in w for w in out.warnings)
    assert menu.sections[0].heading == "Entrées $85 per person"  # input untouched


def test_item_whose_name_is_only_a_price_or_contact_is_dropped():
    menu = Menu.model_validate(
        {
            "menu_id": "m",
            "kind": "event",
            "service": "plated",
            "sections": [
                {
                    "course": "main",
                    "items": [
                        {"name": "Halibut"},
                        {"name": "$125"},
                        {"name": "john@example.com"},
                    ],
                }
            ],
        }
    )
    out = redact_menu(menu)
    assert [i.name for i in out.sections[0].items] == ["Halibut"]


def test_exact_dates_are_removed_not_just_flagged():
    text, n = scrub("Toast at dinner, June 14, 2025, champagne")
    assert "2025" not in text and "June 14" not in text and n == 1
