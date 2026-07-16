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

SUPPORTS_NON_MARVEL_UNIVERSE_FILTER = True
NON_MARVEL_UNIVERSE_FILTER_LABEL = "Show non-Marvel-universe titles"
NON_MARVEL_UNIVERSE_FILTER_HELP = (
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


def non_marvel_universe_run_query():
    query = Q()

    for title_prefix in NON_MARVEL_UNIVERSE_TITLE_PREFIXES:
        query |= Q(title__istartswith=title_prefix)

    return query


def build_publisher_timeline(runs):
    return build_timeline(runs)
