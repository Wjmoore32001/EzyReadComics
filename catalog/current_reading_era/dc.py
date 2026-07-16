from catalog.current_reading_era.shared import build_timeline


PUBLISHER_SLUG_ALIASES = {
    "dc",
    "dc comics",
    "dc-comics",
}
PUBLISHER_NAME_ALIASES = {
    "dc",
    "dc comics",
}
SORT_ORDER = 1


def build_publisher_timeline(runs):
    return build_timeline(runs)
