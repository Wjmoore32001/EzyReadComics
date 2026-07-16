from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from catalog.listing import (
    LISTING_INITIAL_RESULT_LIMIT,
    LISTING_LOAD_MORE_LIMIT,
    LISTING_OPTION_LIMIT,
    build_filter_context,
    build_issue_option,
    build_one_shot_option,
    build_publisher_option,
    build_query_url,
    build_run_option,
    build_volume_option,
    get_int_query_param,
    get_issue_options,
    get_nonnegative_int_query_param,
    get_one_shot_options,
    get_option_page,
    get_publisher_options,
    get_run_options,
    get_volume_options,
    slice_with_has_more,
)
from catalog.models import ComicIssue, ComicOneShot, ComicPublisher, ComicRun, ComicVolume
from catalog.presentation import (
    attach_issue_credit_display,
    attach_issue_tracking,
    attach_one_shot_tracking,
    attach_run_tracking,
    attach_volume_tracking,
    build_issue_row_item,
    build_one_shot_row_item,
    build_run_row_item,
    build_volume_row_item,
    issue_credit_prefetch,
    one_shot_credit_prefetch,
)
from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


BROWSE_INITIAL_RESULT_LIMIT = LISTING_INITIAL_RESULT_LIMIT
BROWSE_LOAD_MORE_LIMIT = LISTING_LOAD_MORE_LIMIT
BROWSE_OPTION_LIMIT = LISTING_OPTION_LIMIT


def browse(request):
    (
        selected_publisher,
        selected_run,
        selected_issue,
        selected_volume,
        selected_one_shot,
    ) = resolve_browse_selection(
        publisher_id=get_int_query_param(request, "publisher"),
        run_id=get_int_query_param(request, "run"),
        issue_id=get_int_query_param(request, "issue"),
        volume_id=get_int_query_param(request, "volume"),
        one_shot_id=get_int_query_param(request, "one_shot"),
    )

    runs_queryset, volumes_queryset, issues_queryset, one_shots_queryset = get_browse_querysets(
        selected_publisher=selected_publisher,
        selected_run=selected_run,
        selected_issue=selected_issue,
        selected_volume=selected_volume,
        selected_one_shot=selected_one_shot,
    )

    volumes_initially_loaded = bool(selected_volume)
    issues_initially_loaded = bool(selected_issue)
    one_shots_initially_loaded = bool(selected_one_shot)

    runs, has_more_runs = slice_with_has_more(
        runs_queryset,
        limit=BROWSE_INITIAL_RESULT_LIMIT,
    )
    volumes = []
    issues = []
    one_shots = []
    has_more_volumes = True
    has_more_issues = True
    has_more_one_shots = True

    if volumes_initially_loaded:
        volumes, has_more_volumes = slice_with_has_more(
            volumes_queryset,
            limit=BROWSE_INITIAL_RESULT_LIMIT,
        )

    if issues_initially_loaded:
        issues, has_more_issues = slice_with_has_more(
            issues_queryset,
            limit=BROWSE_INITIAL_RESULT_LIMIT,
        )

    if one_shots_initially_loaded:
        one_shots, has_more_one_shots = slice_with_has_more(
            one_shots_queryset,
            limit=BROWSE_INITIAL_RESULT_LIMIT,
        )

    attach_issue_credit_display(issues)
    attach_run_tracking(request, runs)
    attach_volume_tracking(request, volumes)
    attach_issue_tracking(request, issues)
    attach_one_shot_tracking(request, one_shots)

    context = {
        "runs": runs,
        "volumes": volumes,
        "issues": issues,
        "one_shots": one_shots,
        "has_more_runs": has_more_runs,
        "has_more_volumes": has_more_volumes,
        "has_more_issues": has_more_issues,
        "has_more_one_shots": has_more_one_shots,
        "runs_initially_loaded": True,
        "volumes_initially_loaded": volumes_initially_loaded,
        "issues_initially_loaded": issues_initially_loaded,
        "one_shots_initially_loaded": one_shots_initially_loaded,
        "listing_items_url": reverse("catalog:browse_items"),
        "run_status_choices": FollowedRun.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
        "one_shot_status_choices": OneShotProgress.STATUS_CHOICES,
        **build_filter_context(
            base_url=reverse("catalog:browse"),
            options_url=reverse("catalog:browse_options"),
            id_prefix="browse",
            selected_publisher=selected_publisher,
            selected_run=selected_run,
            selected_issue=selected_issue,
            selected_volume=selected_volume,
            selected_one_shot=selected_one_shot,
        ),
    }

    return render(request, "catalog/browse.html", context)


def browse_options(request):
    option_kind = (request.GET.get("kind") or "").strip()
    search_value = (request.GET.get("q") or "").strip()
    option_offset = get_nonnegative_int_query_param(request, "offset")
    selected_option_id = get_int_query_param(request, "selected")
    selected_publisher_id = get_int_query_param(request, "publisher")
    selected_run_id = get_int_query_param(request, "run")

    if option_kind == "publisher":
        option_rows, has_more = get_option_page(
            get_publisher_options(ComicPublisher.objects.all(), search_value),
            offset=option_offset,
        )
        options = [
            build_publisher_option(
                publisher,
                url=browse_url_with_params(publisher=publisher.id),
                selected_option_id=selected_option_id,
            )
            for publisher in option_rows
        ]
    elif option_kind == "run":
        option_rows, has_more = get_option_page(
            get_run_options(
                ComicRun.objects.all(),
                search_value,
                publisher_id=selected_publisher_id,
            ),
            offset=option_offset,
        )
        options = [
            build_run_option(
                run,
                url=browse_url_with_params(run=run.id),
                selected_option_id=selected_option_id,
            )
            for run in option_rows
        ]
    elif option_kind == "issue":
        option_rows, has_more = get_option_page(
            get_issue_options(
                ComicIssue.objects.all(),
                search_value,
                publisher_id=selected_publisher_id,
                run_id=selected_run_id,
            ),
            offset=option_offset,
        )
        options = [
            build_issue_option(
                issue,
                url=browse_url_with_params(issue=issue.id),
                selected_option_id=selected_option_id,
            )
            for issue in option_rows
        ]
    elif option_kind == "volume":
        option_rows, has_more = get_option_page(
            get_volume_options(
                ComicVolume.objects.all(),
                search_value,
                publisher_id=selected_publisher_id,
                run_id=selected_run_id,
            ),
            offset=option_offset,
        )
        options = [
            build_volume_option(
                volume,
                url=browse_url_with_params(volume=volume.id),
                selected_option_id=selected_option_id,
            )
            for volume in option_rows
        ]
    elif option_kind == "one_shot":
        option_rows, has_more = get_option_page(
            get_one_shot_options(
                ComicOneShot.objects.all(),
                search_value,
                publisher_id=selected_publisher_id,
            ),
            offset=option_offset,
        )
        options = [
            build_one_shot_option(
                one_shot,
                url=browse_url_with_params(one_shot=one_shot.id),
                selected_option_id=selected_option_id,
            )
            for one_shot in option_rows
        ]
    else:
        return JsonResponse(
            {
                "options": [],
                "has_more": False,
                "next_offset": option_offset,
            },
            status=400,
        )

    return JsonResponse(
        {
            "options": options,
            "has_more": has_more,
            "next_offset": option_offset + len(option_rows),
        }
    )


def browse_items(request):
    item_kind = (request.GET.get("kind") or "").strip()
    offset = get_nonnegative_int_query_param(request, "offset")

    (
        selected_publisher,
        selected_run,
        selected_issue,
        selected_volume,
        selected_one_shot,
    ) = resolve_browse_selection(
        publisher_id=get_int_query_param(request, "publisher"),
        run_id=get_int_query_param(request, "run"),
        issue_id=get_int_query_param(request, "issue"),
        volume_id=get_int_query_param(request, "volume"),
        one_shot_id=get_int_query_param(request, "one_shot"),
    )

    runs_queryset, volumes_queryset, issues_queryset, one_shots_queryset = get_browse_querysets(
        selected_publisher=selected_publisher,
        selected_run=selected_run,
        selected_issue=selected_issue,
        selected_volume=selected_volume,
        selected_one_shot=selected_one_shot,
    )

    if item_kind == "runs":
        rows, has_more = slice_with_has_more(
            runs_queryset,
            limit=BROWSE_LOAD_MORE_LIMIT,
            offset=offset,
        )
        attach_run_tracking(request, rows)
        items = [build_run_row_item(run) for run in rows]
    elif item_kind == "volumes":
        rows, has_more = slice_with_has_more(
            volumes_queryset,
            limit=BROWSE_LOAD_MORE_LIMIT,
            offset=offset,
        )
        attach_volume_tracking(request, rows)
        items = [build_volume_row_item(volume) for volume in rows]
    elif item_kind == "issues":
        rows, has_more = slice_with_has_more(
            issues_queryset,
            limit=BROWSE_LOAD_MORE_LIMIT,
            offset=offset,
        )
        attach_issue_credit_display(rows)
        attach_issue_tracking(request, rows)
        items = [build_issue_row_item(issue) for issue in rows]
    elif item_kind == "one_shots":
        rows, has_more = slice_with_has_more(
            one_shots_queryset,
            limit=BROWSE_LOAD_MORE_LIMIT,
            offset=offset,
        )
        attach_one_shot_tracking(request, rows)
        items = [build_one_shot_row_item(one_shot) for one_shot in rows]
    else:
        return JsonResponse({"items": [], "has_more": False}, status=400)

    return JsonResponse(
        {
            "items": items,
            "has_more": has_more,
        }
    )


def resolve_browse_selection(*, publisher_id, run_id, issue_id, volume_id, one_shot_id):
    selected_publisher = None
    selected_run = None
    selected_issue = None
    selected_volume = None
    selected_one_shot = None

    if one_shot_id:
        selected_one_shot = get_object_or_404(
            ComicOneShot.objects.select_related("publisher"),
            id=one_shot_id,
        )
        selected_publisher = selected_one_shot.publisher
    elif issue_id:
        selected_issue = get_object_or_404(
            ComicIssue.objects.select_related("run", "run__publisher"),
            id=issue_id,
        )
        selected_run = selected_issue.run
        selected_publisher = selected_issue.run.publisher
    elif volume_id:
        selected_volume = get_object_or_404(
            ComicVolume.objects.select_related("publisher", "run"),
            id=volume_id,
        )
        selected_publisher = selected_volume.publisher
    elif run_id:
        selected_run = get_object_or_404(
            ComicRun.objects.select_related("publisher"),
            id=run_id,
        )
        selected_publisher = selected_run.publisher
    elif publisher_id:
        selected_publisher = get_object_or_404(ComicPublisher, id=publisher_id)

    return selected_publisher, selected_run, selected_issue, selected_volume, selected_one_shot


def get_browse_querysets(
    *,
    selected_publisher,
    selected_run,
    selected_issue,
    selected_volume,
    selected_one_shot,
):
    runs = ComicRun.objects.select_related("publisher").order_by(
        "-start_year",
        "-first_issue_date",
        "publisher__name",
        "title",
    )
    volumes = ComicVolume.objects.select_related("publisher", "run").order_by(
        "-release_date",
        "-run__start_year",
        "run__title",
        "volume_number",
        "title",
    )
    issues = ComicIssue.objects.select_related(
        "run",
        "run__publisher",
    ).prefetch_related(
        issue_credit_prefetch(),
    ).order_by(
        "-run__start_year",
        "-published_date",
        "run__title",
        "issue_number",
    )
    one_shots = ComicOneShot.objects.select_related("publisher").prefetch_related(
        one_shot_credit_prefetch(),
    ).order_by(
        "-published_date",
        "-start_year",
        "publisher__name",
        "title",
        "id",
    )

    if selected_one_shot:
        runs = runs.none()
        volumes = volumes.filter(
            volume_one_shots__one_shot=selected_one_shot,
        ).distinct()
        issues = issues.none()
        one_shots = one_shots.filter(id=selected_one_shot.id)
    elif selected_issue:
        runs = runs.filter(id=selected_issue.run_id)
        volumes = volumes.filter(volume_issues__issue=selected_issue).distinct()
        issues = issues.filter(id=selected_issue.id)
        one_shots = one_shots.none()
    elif selected_volume:
        runs = runs.filter(
            Q(volumes=selected_volume)
            | Q(collected_volume_links__volume=selected_volume)
            | Q(issues__collected_in__volume=selected_volume)
        ).distinct()
        volumes = volumes.filter(id=selected_volume.id)
        issues = issues.filter(collected_in__volume=selected_volume).distinct()
        one_shots = one_shots.filter(collected_in__volume=selected_volume).distinct()
    elif selected_run:
        runs = runs.filter(id=selected_run.id)
        volumes = volumes.filter(
            Q(run=selected_run)
            | Q(volume_runs__run=selected_run)
            | Q(volume_issues__issue__run=selected_run)
        ).distinct()
        issues = issues.filter(run=selected_run)
        one_shots = one_shots.none()
    elif selected_publisher:
        runs = runs.filter(publisher=selected_publisher)
        volumes = volumes.filter(publisher=selected_publisher)
        issues = issues.filter(run__publisher=selected_publisher)
        one_shots = one_shots.filter(publisher=selected_publisher)

    return runs, volumes, issues, one_shots


def browse_url_with_params(**params):
    return build_query_url(reverse("catalog:browse"), **params)
