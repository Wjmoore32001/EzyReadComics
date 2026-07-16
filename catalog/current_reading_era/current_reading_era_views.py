import re

from django.db.models import Prefetch
from django.shortcuts import render
from django.utils import timezone

from catalog.current_reading_era import (
    DEFAULT_PUBLISHER_HANDLER,
    get_handler_for_publisher,
    publisher_option_sort_key,
)
from catalog.models import ComicIssue, ComicPublisher, ComicRun


START_YEAR_PATTERN = re.compile(r"^\d{4}$")


def current_reading_era(request):
    publisher_options = []

    for publisher in ComicPublisher.objects.all().order_by("name", "id"):
        handler = get_handler_for_publisher(publisher)

        if handler is None:
            continue

        publisher_options.append(
            {
                "publisher": publisher,
                "handler": handler,
            }
        )

    publisher_options.sort(key=publisher_option_sort_key)

    requested_publisher_slug = request.GET.get("publisher", "").strip()
    selected_option = None

    if requested_publisher_slug:
        selected_option = next(
            (
                option
                for option in publisher_options
                if option["publisher"].slug == requested_publisher_slug
            ),
            None,
        )

    if selected_option is None:
        selected_option = next(
            (
                option
                for option in publisher_options
                if option["handler"] is DEFAULT_PUBLISHER_HANDLER
            ),
            publisher_options[0] if publisher_options else None,
        )

    selected_publisher = None
    selected_start_year = None
    start_year_options = []

    show_non_marvel_universe_filter = False
    show_non_marvel_universe_titles = False
    non_marvel_universe_filter_label = ""
    non_marvel_universe_filter_help = ""

    timeline = {
        "rows": [],
        "column_count": 1,
        "run_count": 0,
        "issue_count": 0,
    }

    if selected_option is not None:
        selected_publisher = selected_option["publisher"]
        selected_handler = selected_option["handler"]

        show_non_marvel_universe_filter = getattr(
            selected_handler,
            "SUPPORTS_NON_MARVEL_UNIVERSE_FILTER",
            False,
        )
        show_non_marvel_universe_titles = (
            show_non_marvel_universe_filter
            and request.GET.get("show_non_marvel_universe") == "1"
        )
        non_marvel_universe_filter_label = getattr(
            selected_handler,
            "NON_MARVEL_UNIVERSE_FILTER_LABEL",
            "",
        )
        non_marvel_universe_filter_help = getattr(
            selected_handler,
            "NON_MARVEL_UNIVERSE_FILTER_HELP",
            "",
        )

        visible_runs_queryset = ComicRun.objects.filter(
            publisher=selected_publisher,
            current_reading_era_entries__isnull=False,
        )

        if (
            show_non_marvel_universe_filter
            and not show_non_marvel_universe_titles
        ):
            visible_runs_queryset = visible_runs_queryset.exclude(
                selected_handler.non_marvel_universe_run_query()
            )

        start_year_options = build_start_year_options(visible_runs_queryset)
        selected_start_year = get_selected_start_year(
            request.GET.get("start_year", ""),
            start_year_options,
        )

        if selected_start_year is not None:
            current_year = timezone.localdate().year
            included_start_years = [
                str(year)
                for year in range(selected_start_year, current_year + 1)
            ]
            visible_runs_queryset = visible_runs_queryset.filter(
                start_year__in=included_start_years
            )

        timeline_issue_queryset = (
            ComicIssue.objects.filter(
                is_released=True,
                published_date__isnull=False,
            )
            .select_related("run", "run__publisher")
            .order_by(
                "published_date",
                "issue_number",
                "id",
            )
        )

        runs = list(
            visible_runs_queryset.select_related("publisher")
            .prefetch_related(
                Prefetch(
                    "issues",
                    queryset=timeline_issue_queryset,
                    to_attr="current_era_timeline_issues",
                )
            )
            .distinct()
        )

        timeline = selected_handler.build_publisher_timeline(runs)

    context = {
        "publisher_options": publisher_options,
        "selected_publisher": selected_publisher,
        "selected_start_year": selected_start_year,
        "start_year_options": start_year_options,
        "show_non_marvel_universe_filter": show_non_marvel_universe_filter,
        "show_non_marvel_universe_titles": show_non_marvel_universe_titles,
        "non_marvel_universe_filter_label": non_marvel_universe_filter_label,
        "non_marvel_universe_filter_help": non_marvel_universe_filter_help,
        "timeline": timeline,
    }

    return render(request, "catalog/current_reading_era.html", context)


def build_start_year_options(run_queryset):
    current_year = timezone.localdate().year
    valid_years = []

    raw_start_years = (
        run_queryset.exclude(start_year="")
        .values_list("start_year", flat=True)
        .distinct()
    )

    for raw_start_year in raw_start_years:
        normalized_year = str(raw_start_year or "").strip()

        if not START_YEAR_PATTERN.fullmatch(normalized_year):
            continue

        year = int(normalized_year)

        if year <= current_year:
            valid_years.append(year)

    oldest_year = min(valid_years, default=current_year)

    return list(range(current_year, oldest_year - 1, -1))


def get_selected_start_year(raw_value, start_year_options):
    normalized_value = str(raw_value or "").strip()

    if not START_YEAR_PATTERN.fullmatch(normalized_value):
        return None

    selected_year = int(normalized_value)

    if selected_year not in start_year_options:
        return None

    return selected_year
