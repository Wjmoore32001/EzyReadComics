from django.db.models import Prefetch
from django.shortcuts import render

from catalog.current_reading_era import (
    DEFAULT_PUBLISHER_HANDLER,
    get_handler_for_publisher,
    publisher_option_sort_key,
)
from catalog.models import ComicIssue, ComicPublisher, ComicRun


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
    timeline = {
        "rows": [],
        "column_count": 1,
        "run_count": 0,
        "issue_count": 0,
    }

    if selected_option is not None:
        selected_publisher = selected_option["publisher"]
        selected_handler = selected_option["handler"]

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
            ComicRun.objects.filter(
                publisher=selected_publisher,
                current_reading_era_entries__isnull=False,
            )
            .select_related("publisher")
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
        "timeline": timeline,
    }

    return render(request, "catalog/current_reading_era.html", context)
