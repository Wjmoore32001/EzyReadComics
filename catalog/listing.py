from urllib.parse import urlencode

from django.db.models import Case, IntegerField, Q, Value, When


LISTING_INITIAL_RESULT_LIMIT = 10
LISTING_LOAD_MORE_LIMIT = 10
LISTING_OPTION_LIMIT = 10


def get_int_query_param(request, name):
    raw_value = request.GET.get(name)

    if raw_value in [None, ""]:
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def get_nonnegative_int_query_param(request, name):
    raw_value = request.GET.get(name)

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 0

    return max(value, 0)


def slice_with_has_more(queryset, *, limit, offset=0):
    items = list(queryset[offset : offset + limit + 1])
    return items[:limit], len(items) > limit


def get_option_page(queryset, *, offset=0, limit=LISTING_OPTION_LIMIT):
    return slice_with_has_more(
        queryset,
        limit=limit,
        offset=offset,
    )


def get_publisher_options(queryset, search_value):
    queryset = queryset.distinct()

    if search_value:
        return queryset.filter(
            name__icontains=search_value,
        ).annotate(
            search_rank=Case(
                When(name__iexact=search_value, then=Value(0)),
                When(name__istartswith=search_value, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by(
            "search_rank",
            "name",
        )

    return queryset.order_by("name")


def get_run_options(queryset, search_value, *, publisher_id=None):
    queryset = queryset.select_related("publisher")

    if publisher_id:
        queryset = queryset.filter(publisher_id=publisher_id)

    if search_value:
        return queryset.filter(
            Q(title__icontains=search_value)
            | Q(start_year__icontains=search_value)
            | Q(publisher__name__icontains=search_value)
        ).annotate(
            search_rank=Case(
                When(title__iexact=search_value, then=Value(0)),
                When(title__istartswith=search_value, then=Value(1)),
                When(publisher__name__istartswith=search_value, then=Value(2)),
                When(title__icontains=search_value, then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            )
        ).order_by(
            "search_rank",
            "-start_year",
            "-first_issue_date",
            "publisher__name",
            "title",
        )

    return queryset.order_by(
        "-start_year",
        "-first_issue_date",
        "publisher__name",
        "title",
    )


def get_issue_options(queryset, search_value, *, publisher_id=None, run_id=None):
    queryset = queryset.select_related(
        "run",
        "run__publisher",
    )

    if publisher_id:
        queryset = queryset.filter(run__publisher_id=publisher_id)

    if run_id:
        queryset = queryset.filter(run_id=run_id)

    if search_value:
        return queryset.filter(
            Q(issue_number__icontains=search_value)
            | Q(run__title__icontains=search_value)
            | Q(run__start_year__icontains=search_value)
            | Q(run__publisher__name__icontains=search_value)
        ).annotate(
            search_rank=Case(
                When(issue_number__iexact=search_value, then=Value(0)),
                When(issue_number__istartswith=search_value, then=Value(1)),
                When(run__title__iexact=search_value, then=Value(2)),
                When(run__title__istartswith=search_value, then=Value(3)),
                When(run__title__icontains=search_value, then=Value(4)),
                default=Value(5),
                output_field=IntegerField(),
            )
        ).order_by(
            "search_rank",
            "-run__start_year",
            "-published_date",
            "run__title",
            "issue_number",
        )

    return queryset.order_by(
        "-run__start_year",
        "-published_date",
        "run__title",
        "issue_number",
    )


def get_volume_options(queryset, search_value, *, publisher_id=None, run_id=None):
    queryset = queryset.select_related(
        "publisher",
        "run",
    )

    if publisher_id:
        queryset = queryset.filter(publisher_id=publisher_id)

    if run_id:
        queryset = queryset.filter(
            Q(run_id=run_id)
            | Q(volume_runs__run_id=run_id)
            | Q(volume_issues__issue__run_id=run_id)
        ).distinct()

    if search_value:
        return queryset.filter(
            Q(title__icontains=search_value)
            | Q(run__title__icontains=search_value)
            | Q(volume_runs__run__title__icontains=search_value)
            | Q(volume_issues__issue__run__title__icontains=search_value)
            | Q(volume_number__icontains=search_value)
            | Q(publisher__name__icontains=search_value)
        ).annotate(
            search_rank=Case(
                When(title__iexact=search_value, then=Value(0)),
                When(run__title__iexact=search_value, then=Value(1)),
                When(title__istartswith=search_value, then=Value(2)),
                When(run__title__istartswith=search_value, then=Value(3)),
                When(title__icontains=search_value, then=Value(4)),
                When(run__title__icontains=search_value, then=Value(5)),
                default=Value(6),
                output_field=IntegerField(),
            )
        ).distinct().order_by(
            "search_rank",
            "-release_date",
            "-run__start_year",
            "run__title",
            "volume_number",
            "title",
        )

    return queryset.order_by(
        "-release_date",
        "-run__start_year",
        "run__title",
        "volume_number",
        "title",
    )


def get_one_shot_options(queryset, search_value, *, publisher_id=None):
    queryset = queryset.select_related("publisher")

    if publisher_id:
        queryset = queryset.filter(publisher_id=publisher_id)

    if search_value:
        return queryset.filter(
            Q(title__icontains=search_value)
            | Q(start_year__icontains=search_value)
            | Q(publisher__name__icontains=search_value)
        ).annotate(
            search_rank=Case(
                When(title__iexact=search_value, then=Value(0)),
                When(title__istartswith=search_value, then=Value(1)),
                When(publisher__name__istartswith=search_value, then=Value(2)),
                When(title__icontains=search_value, then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            )
        ).order_by(
            "search_rank",
            "-published_date",
            "-start_year",
            "publisher__name",
            "title",
            "id",
        )

    return queryset.order_by(
        "-published_date",
        "-start_year",
        "publisher__name",
        "title",
        "id",
    )


def build_query_url(base_url, **params):
    clean_params = {
        key: value
        for key, value in params.items()
        if value not in [None, ""]
    }

    if not clean_params:
        return base_url

    return f"{base_url}?{urlencode(clean_params)}"


def format_date_or_unknown(value):
    if not value:
        return "Unknown"

    return value.strftime("%Y-%m-%d")


def build_publisher_option(publisher, *, url, selected_option_id):
    return {
        "id": publisher.id,
        "url": url,
        "label": publisher.name,
        "meta": "",
        "search_label": publisher.name,
        "active": publisher.id == selected_option_id,
    }


def build_run_option(run, *, url, selected_option_id):
    year = run.start_year or "Unknown year"
    issue_count = f"{run.issue_count} issues" if run.issue_count else "issue count unknown"

    return {
        "id": run.id,
        "url": url,
        "label": f"{year} — {run.title}",
        "meta": f"{run.publisher.name} · {issue_count}",
        "search_label": f"{run.title} {run.start_year} {run.publisher.name}",
        "active": run.id == selected_option_id,
    }


def build_issue_option(issue, *, url, selected_option_id):
    return {
        "id": issue.id,
        "url": url,
        "label": f"{issue.run.title} #{issue.issue_number}",
        "meta": (
            f"{issue.run.publisher.name}"
            f" · {format_date_or_unknown(issue.published_date)}"
        ),
        "search_label": (
            f"{issue.run.title} {issue.run.start_year} "
            f"{issue.issue_number} {issue.run.publisher.name}"
        ),
        "active": issue.id == selected_option_id,
    }


def build_volume_option(volume, *, url, selected_option_id):
    primary_run = volume.run
    primary_run_text = str(primary_run) if primary_run else "No primary run"
    primary_run_title = primary_run.title if primary_run else ""

    meta_parts = [
        volume.publisher.name,
        primary_run_text,
    ]

    if volume.issue_count:
        meta_parts.append(f"{volume.issue_count} issues")

    return {
        "id": volume.id,
        "url": url,
        "label": str(volume),
        "meta": " · ".join(meta_parts),
        "search_label": (
            f"{volume.title} {primary_run_title} "
            f"{volume.volume_number} {volume.publisher.name}"
        ),
        "active": volume.id == selected_option_id,
    }


def build_one_shot_option(one_shot, *, url, selected_option_id):
    return {
        "id": one_shot.id,
        "url": url,
        "label": one_shot.title,
        "meta": (
            f"{one_shot.publisher.name}"
            f" · {format_date_or_unknown(one_shot.published_date)}"
        ),
        "search_label": (
            f"{one_shot.title} {one_shot.start_year} {one_shot.publisher.name}"
        ),
        "active": one_shot.id == selected_option_id,
    }


def build_selected_items(
    *,
    selected_publisher,
    selected_run,
    selected_issue,
    selected_volume,
    selected_one_shot,
):
    selected_items = []

    if selected_publisher:
        selected_items.append(
            {
                "label": "Publisher",
                "value": selected_publisher.name,
            }
        )

    if selected_run:
        selected_items.append(
            {
                "label": "Run",
                "value": str(selected_run),
            }
        )

    if selected_issue:
        selected_items.append(
            {
                "label": "Issue",
                "value": f"{selected_issue.run} #{selected_issue.issue_number}",
            }
        )

    if selected_volume:
        selected_items.append(
            {
                "label": "Volume",
                "value": str(selected_volume),
            }
        )

    if selected_one_shot:
        selected_items.append(
            {
                "label": "One-shot",
                "value": selected_one_shot.title,
            }
        )

    return selected_items


def build_filter_context(
    *,
    base_url,
    options_url,
    id_prefix,
    selected_publisher,
    selected_run,
    selected_issue,
    selected_volume,
    selected_one_shot,
):
    selected_publisher_id = selected_publisher.id if selected_publisher else None
    selected_run_id = selected_run.id if selected_run else None
    selected_issue_id = selected_issue.id if selected_issue else None
    selected_volume_id = selected_volume.id if selected_volume else None
    selected_one_shot_id = selected_one_shot.id if selected_one_shot else None

    return {
        "filter_base_url": base_url,
        "filter_options_url": options_url,
        "filter_id_prefix": id_prefix,
        "filters_active": any(
            [
                selected_publisher_id,
                selected_run_id,
                selected_issue_id,
                selected_volume_id,
                selected_one_shot_id,
            ]
        ),
        "selected_publisher": selected_publisher,
        "selected_run": selected_run,
        "selected_issue": selected_issue,
        "selected_volume": selected_volume,
        "selected_one_shot": selected_one_shot,
        "selected_publisher_id": selected_publisher_id,
        "selected_run_id": selected_run_id,
        "selected_issue_id": selected_issue_id,
        "selected_volume_id": selected_volume_id,
        "selected_one_shot_id": selected_one_shot_id,
        "selected_items": build_selected_items(
            selected_publisher=selected_publisher,
            selected_run=selected_run,
            selected_issue=selected_issue,
            selected_volume=selected_volume,
            selected_one_shot=selected_one_shot,
        ),
        "all_publishers_url": base_url,
        "all_runs_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
        ),
        "all_issues_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
            run=selected_run_id,
        ),
        "all_volumes_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
            run=selected_run_id,
        ),
        "all_one_shots_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
        ),
        "clear_run_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
        ),
        "clear_issue_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
            run=selected_run_id,
        ),
        "clear_volume_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
            run=selected_run_id,
        ),
        "clear_one_shot_url": build_query_url(
            base_url,
            publisher=selected_publisher_id,
        ),
    }
