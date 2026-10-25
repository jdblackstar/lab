"""Canonical menu format.

Every source document (PDF, photo, Word file, spreadsheet, email) is normalized into
``Menu`` records. The format describes what was served and how, never what it cost or
who it was for: prices and client details have no fields here, and the ingest pipeline
scrubs them from free text.

A menu is an ordered list of sections. Each section says what role it plays in the
meal (``course``) and how it reaches guests (``service``), so one record can describe a
plated dinner, a family-style supper, a buffet, a cocktail reception of passed and
displayed hors d'oeuvres, stations, and the bar, or any mix of those.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MenuKind(str, Enum):
    """Whether the document is a composed menu or a list of options."""

    event = "event"  # what was served (or planned) for one event
    sample = "sample"  # a fully composed showcase menu, not tied to an event
    package = "package"  # a priced/tiered offering ("Gold package") with fixed contents
    catalog = "catalog"  # options to choose from ("select 3 of the following")
    unknown = "unknown"


class ServiceStyle(str, Enum):
    plated = "plated"  # individually plated, served to seated guests
    family_style = "family_style"  # shared platters passed at the table
    buffet = "buffet"  # guests serve themselves from a line
    stations = "stations"  # attended or themed stations
    passed = "passed"  # butler-passed bites
    display = "display"  # stationary displays (cheese, crudités, raw bar)
    reception = "reception"  # cocktail-style event with no seated meal
    drop_off = "drop_off"  # delivered, boxed, or set-and-leave
    mixed = "mixed"  # menu-level only: sections use different styles
    unknown = "unknown"


class Course(str, Enum):
    hors_doeuvres = "hors_doeuvres"
    raw_bar = "raw_bar"
    display = "display"  # cheese, charcuterie, crudités, mezze boards
    bread = "bread"
    soup = "soup"
    salad = "salad"
    appetizer = "appetizer"  # plated first course
    pasta = "pasta"
    intermezzo = "intermezzo"
    main = "main"
    side = "side"
    cheese = "cheese"  # a cheese course within the meal
    dessert = "dessert"
    late_night = "late_night"
    kids = "kids"
    cocktail = "cocktail"
    wine = "wine"
    beer = "beer"
    spirits = "spirits"
    non_alcoholic = "non_alcoholic"
    coffee_tea = "coffee_tea"
    bar_service = "bar_service"  # a bar package described as a whole
    other = "other"


DRINK_COURSES = frozenset(
    {
        Course.cocktail,
        Course.wine,
        Course.beer,
        Course.spirits,
        Course.non_alcoholic,
        Course.coffee_tea,
        Course.bar_service,
    }
)
FOOD_COURSES = frozenset(c for c in Course if c not in DRINK_COURSES)


class Dietary(str, Enum):
    vegetarian = "vegetarian"
    vegan = "vegan"
    gluten_free = "gluten_free"
    dairy_free = "dairy_free"
    nut_free = "nut_free"
    contains_nuts = "contains_nuts"
    pescatarian = "pescatarian"
    shellfish = "shellfish"
    kosher = "kosher"
    halal = "halal"
    raw = "raw"


class ItemRole(str, Enum):
    standard = "standard"
    dietary_alternate = "dietary_alternate"  # "vegetarian guests will receive..."
    kids = "kids"
    upgrade = "upgrade"  # optional add-on


class SelectionMode(str, Enum):
    all = "all"  # every item is served
    guest_choice = "guest_choice"  # each guest picks one (e.g. entrée choice)
    host_choice = "host_choice"  # the client picks some of these when booking


class GuestCountBand(str, Enum):
    under_25 = "under_25"
    from_25_to_75 = "25_to_75"
    from_75_to_150 = "75_to_150"
    from_150_to_300 = "150_to_300"
    over_300 = "over_300"
    unknown = "unknown"


class EventType(str, Enum):
    wedding = "wedding"
    rehearsal_dinner = "rehearsal_dinner"
    corporate = "corporate"
    gala = "gala"
    holiday_party = "holiday_party"
    celebration = "celebration"  # birthday, anniversary, graduation
    memorial = "memorial"
    cocktail_party = "cocktail_party"
    private_dinner = "private_dinner"
    other = "other"
    unknown = "unknown"


class MealPeriod(str, Enum):
    breakfast = "breakfast"
    brunch = "brunch"
    lunch = "lunch"
    afternoon = "afternoon"
    cocktail_hour = "cocktail_hour"
    dinner = "dinner"
    late_night = "late_night"
    unknown = "unknown"


class Season(str, Enum):
    winter = "winter"
    spring = "spring"
    summer = "summer"
    fall = "fall"
    unknown = "unknown"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Item(_Model):
    name: str = Field(description="Dish or drink name, verbatim from the source.")
    description: str | None = Field(
        default=None,
        description="Ingredients/preparation text, verbatim, with prices removed.",
    )
    dietary: list[Dietary] = Field(default_factory=list)
    role: ItemRole = ItemRole.standard
    pairing: str | None = Field(
        default=None, description="A drink paired with this item, if listed."
    )


class Section(_Model):
    course: Course
    heading: str | None = Field(
        default=None, description="The section heading as written, if any."
    )
    service: ServiceStyle | None = Field(
        default=None,
        description="How this section is served, when it differs from or refines the menu's style.",
    )
    selection: SelectionMode = SelectionMode.all
    select_count: int | None = Field(
        default=None, description="For host_choice: how many items the client picks."
    )
    items: list[Item]


class EventContext(_Model):
    event_type: EventType = EventType.unknown
    meal_period: MealPeriod = MealPeriod.unknown
    month: int | None = Field(default=None, description="1-12, if known.")
    season: Season = Season.unknown
    guest_count: GuestCountBand = GuestCountBand.unknown


class MenuBody(_Model):
    """The part of a menu that an extractor fills in from a source document."""

    kind: MenuKind
    title: str | None = Field(
        default=None,
        description="A generic title such as 'Autumn Wedding Dinner'. Never a client or person name.",
    )
    service: ServiceStyle
    event: EventContext = Field(default_factory=EventContext)
    sections: list[Section]
    notes: list[str] = Field(
        default_factory=list,
        description="Service or kitchen notes worth keeping (e.g. 'all breads baked in house').",
    )


class SourceRef(_Model):
    sha256: str
    media_type: str
    index_in_source: int = 0
    extractor: str | None = None


class Menu(MenuBody):
    menu_id: str
    caterer: str | None = Field(
        default=None,
        description="An opaque label for the business that wrote the menu ('c1', not "
        "its name). Menus without one count as one caterer.",
    )
    source: SourceRef | None = None
    warnings: list[str] = Field(default_factory=list)

    def items(self):
        for section in self.sections:
            yield from section.items
