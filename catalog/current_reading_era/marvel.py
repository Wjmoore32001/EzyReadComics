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


def build_publisher_timeline(runs):
    return build_timeline(runs)
