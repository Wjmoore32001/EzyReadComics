from django.db.models import Q

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

OPTIONAL_HIDDEN_RUN_FILTER_PARAMETER = "show_action_detective_comics"
OPTIONAL_HIDDEN_RUN_FILTER_LABEL = "Show Action Comics and Detective Comics"
OPTIONAL_HIDDEN_RUN_FILTER_HELP = (
    "Includes the long-running Action Comics and Detective Comics series "
    "alongside the main Superman and Batman runs."
)


def hidden_by_default_run_query():
    return (
        Q(title__iexact="Action Comics")
        | Q(title__iexact="Detective Comics")
    )


def build_publisher_timeline(runs):
    return build_timeline(runs)
