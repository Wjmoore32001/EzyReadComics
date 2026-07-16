from django.db.models import Q

from catalog.current_reading_era.shared import build_timeline


PUBLISHER_SLUG_ALIASES = {
    "marvel",
    "marvel comics",
    "marvel-comics",
}
PUBLISHER_NAME_ALIASES = {
    "marvel",
    "marvel comics",
}
SORT_ORDER = 0

OPTIONAL_HIDDEN_RUN_FILTER_PARAMETER = "show_non_marvel_universe"
OPTIONAL_HIDDEN_RUN_FILTER_LABEL = "Show non-Marvel-universe titles"
OPTIONAL_HIDDEN_RUN_FILTER_HELP = (
    "Includes external franchise lines such as Star Wars, Alien, Predator, "
    "Godzilla, Planet of the Apes, and Ultraman."
)

NON_MARVEL_UNIVERSE_TITLE_PREFIXES = (
    "STAR WARS",
    "ALIEN",
    "ALIENS",
    "PREDATOR",
    "GODZILLA",
    "PLANET OF THE APES",
    "ULTRAMAN",
    "MARVEL & DISNEY",
    "MARVEL DISNEY",
    "DISNEY",
    "CONAN",
    "FORTNITE",
    "MARVEL X FORTNITE",
    "HALO",
    "WARHAMMER",
)


def hidden_by_default_run_query():
    query = Q()

    for title_prefix in NON_MARVEL_UNIVERSE_TITLE_PREFIXES:
        query |= Q(title__istartswith=title_prefix)

    return query


def build_publisher_timeline(runs):
    return build_timeline(runs)
