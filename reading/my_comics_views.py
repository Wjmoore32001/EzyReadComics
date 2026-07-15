from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

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
from catalog.models import (
    ComicIssue,
    ComicOneShot,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)
from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress
from reading.views import (
    UNFOLLOW_STATUS_VALUE,
    build_my_comics_issue_row_item,
    build_my_comics_one_shot_row_item,
    build_my_comics_run_row_item,
    build_my_comics_volume_row_item,
)


MY_COMICS_INITIAL_RESULT_LIMIT = LISTING_INITIAL_RESULT_LIMIT
MY_COMICS_LOAD_MORE_LIMIT = LISTING_LOAD_MORE_LIMIT
MY_COMICS_OPTION_LIMIT = LISTING_OPTION_LIMIT


@login_required
def my_comics(request):
    filters, selection = resolve_my_comics_filters(request)
    followed_runs, volume_progress, issue_progress, one_shot_progress = get_filtered_my_comics_querysets(
        request.user,
        filters,
    )

    runs, has_more_runs = slice_with_has_more(
        followed_runs,
        limit=MY_COMICS_INITIAL_RESULT_LIMIT,
    )

    volumes_initially_loaded = bool(filters["volume_id"])
    issues_initially_loaded = bool(filters["issue_id"])
    one_shots_initially_loaded = bool(filters["one_shot_id"])

    volumes = []
    issues = []
    one_shots = []
    has_more_volumes = True
    has_more_issues = True
    has_more_one_shots = True

    if volumes_initially_loaded:
        volumes, has_more_volumes = slice_with_has_more(
            volume_progress,
            limit=MY_COMICS_INITIAL_RESULT_LIMIT,
        )

    if issues_initially_loaded:
        issues, has_more_issues = slice_with_has_more(
            issue_progress,
            limit=MY_COMICS_INITIAL_RESULT_LIMIT,
        )

    if one_shots_initially_loaded:
        one_shots, has_more_one_shots = slice_with_has_more(
            one_shot_progress,
            limit=MY_COMICS_INITIAL_RESULT_LIMIT,
        )

    context = {
        "followed_runs": runs,
        "volume_progress": volumes,
        "issue_progress": issues,
        "one_shot_progress": one_shots,
        "has_more_runs": has_more_runs,
        "has_more_volumes": has_more_volumes,
        "has_more_issues": has_more_issues,
        "has_more_one_shots": has_more_one_shots,
        "runs_initially_loaded": True,
        "volumes_initially_loaded": volumes_initially_loaded,
        "issues_initially_loaded": issues_initially_loaded,
        "one_shots_initially_loaded": one_shots_initially_loaded,
        "listing_items_url": reverse("reading:my_comics_items"),
        "run_status_choices": FollowedRun.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
        "one_shot_status_choices": OneShotProgress.STATUS_CHOICES,
        "unfollow_status_value": UNFOLLOW_STATUS_VALUE,
        **build_filter_context(
            base_url=reverse("reading:my_comics"),
            options_url=reverse("reading:my_comics_options"),
            id_prefix="my-comics",
            selected_publisher=selection["publisher"],
            selected_run=selection["run"],
            selected_issue=selection["issue"],
            selected_volume=selection["volume"],
            selected_one_shot=selection["one_shot"],
        ),
    }

    return render(request, "reading/my_comics.html", context)


@login_required
@require_GET
def my_comics_items(request):
    item_kind = (request.GET.get("kind") or "").strip()
    offset = get_nonnegative_int_query_param(request, "offset")
    filters, _selection = resolve_my_comics_filters(request)
    followed_runs, volume_progress, issue_progress, one_shot_progress = get_filtered_my_comics_querysets(
        request.user,
        filters,
    )

    if item_kind == "runs":
        rows, has_more = slice_with_has_more(
            followed_runs,
            limit=MY_COMICS_LOAD_MORE_LIMIT,
            offset=offset,
        )
        items = [build_my_comics_run_row_item(row) for row in rows]
    elif item_kind == "volumes":
        rows, has_more = slice_with_has_more(
            volume_progress,
            limit=MY_COMICS_LOAD_MORE_LIMIT,
            offset=offset,
        )
        items = [build_my_comics_volume_row_item(row) for row in rows]
    elif item_kind == "issues":
        rows, has_more = slice_with_has_more(
            issue_progress,
            limit=MY_COMICS_LOAD_MORE_LIMIT,
            offset=offset,
        )
        items = [build_my_comics_issue_row_item(row) for row in rows]
    elif item_kind == "one_shots":
        rows, has_more = slice_with_has_more(
            one_shot_progress,
            limit=MY_COMICS_LOAD_MORE_LIMIT,
            offset=offset,
        )
        items = [build_my_comics_one_shot_row_item(row) for row in rows]
    else:
        return JsonResponse({"items": [], "has_more": False}, status=400)

    return JsonResponse(
        {
            "items": items,
            "has_more": has_more,
        }
    )


@login_required
@require_GET
def my_comics_options(request):
    option_kind = (request.GET.get("kind") or "").strip()
    search_value = (request.GET.get("q") or "").strip()
    option_offset = get_nonnegative_int_query_param(request, "offset")
    selected_option_id = get_int_query_param(request, "selected")
    selected_publisher_id = get_int_query_param(request, "publisher")
    selected_run_id = get_int_query_param(request, "run")

    if option_kind == "publisher":
        option_rows, has_more = get_option_page(
            get_publisher_options(
                ComicPublisher.objects.filter(
                    id__in=get_user_tracked_publisher_ids(request.user),
                ),
                search_value,
            ),
            offset=option_offset,
        )
        options = [
            build_publisher_option(
                publisher,
                url=build_my_comics_url(publisher=publisher.id),
                selected_option_id=selected_option_id,
            )
            for publisher in option_rows
        ]
    elif option_kind == "run":
        option_rows, has_more = get_option_page(
            get_run_options(
                ComicRun.objects.filter(
                    id__in=get_user_tracked_run_ids(request.user),
                ),
                search_value,
                publisher_id=selected_publisher_id,
            ),
            offset=option_offset,
        )
        options = [
            build_run_option(
                run,
                url=build_my_comics_url(
                    publisher=selected_publisher_id,
                    run=run.id,
                ),
                selected_option_id=selected_option_id,
            )
            for run in option_rows
        ]
    elif option_kind == "issue":
        option_rows, has_more = get_option_page(
            get_issue_options(
                ComicIssue.objects.filter(
                    id__in=get_user_tracked_issue_ids(request.user),
                ),
                search_value,
                publisher_id=selected_publisher_id,
                run_id=selected_run_id,
            ),
            offset=option_offset,
        )
        options = [
            build_issue_option(
                issue,
                url=build_my_comics_url(
                    publisher=selected_publisher_id,
                    run=selected_run_id,
                    issue=issue.id,
                ),
                selected_option_id=selected_option_id,
            )
            for issue in option_rows
        ]
    elif option_kind == "volume":
        option_rows, has_more = get_option_page(
            get_volume_options(
                ComicVolume.objects.filter(
                    id__in=get_user_tracked_volume_ids(request.user),
                ),
                search_value,
                publisher_id=selected_publisher_id,
                run_id=selected_run_id,
            ),
            offset=option_offset,
        )
        options = [
            build_volume_option(
                volume,
                url=build_my_comics_url(
                    publisher=selected_publisher_id,
                    run=selected_run_id,
                    volume=volume.id,
                ),
                selected_option_id=selected_option_id,
            )
            for volume in option_rows
        ]
    elif option_kind == "one_shot":
        option_rows, has_more = get_option_page(
            get_one_shot_options(
                ComicOneShot.objects.filter(
                    id__in=get_user_tracked_one_shot_ids(request.user),
                ),
                search_value,
                publisher_id=selected_publisher_id,
            ),
            offset=option_offset,
        )
        options = [
            build_one_shot_option(
                one_shot,
                url=build_my_comics_url(
                    publisher=selected_publisher_id,
                    one_shot=one_shot.id,
                ),
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


def resolve_my_comics_filters(request):
    raw_filters = {
        "publisher_id": get_int_query_param(request, "publisher"),
        "run_id": get_int_query_param(request, "run"),
        "issue_id": get_int_query_param(request, "issue"),
        "volume_id": get_int_query_param(request, "volume"),
        "one_shot_id": get_int_query_param(request, "one_shot"),
    }

    publisher = None
    run = None
    issue = None
    volume = None
    one_shot = None

    if raw_filters["one_shot_id"]:
        one_shot = get_object_or_404(
            ComicOneShot.objects.select_related("publisher"),
            id=raw_filters["one_shot_id"],
        )
        publisher = one_shot.publisher
    elif raw_filters["issue_id"]:
        issue = get_object_or_404(
            ComicIssue.objects.select_related("run", "run__publisher"),
            id=raw_filters["issue_id"],
        )
        run = issue.run
        publisher = issue.run.publisher
    elif raw_filters["volume_id"]:
        volume = get_object_or_404(
            ComicVolume.objects.select_related("publisher", "run"),
            id=raw_filters["volume_id"],
        )
        run = volume.run
        publisher = volume.publisher
    elif raw_filters["run_id"]:
        run = get_object_or_404(
            ComicRun.objects.select_related("publisher"),
            id=raw_filters["run_id"],
        )
        publisher = run.publisher
    elif raw_filters["publisher_id"]:
        publisher = get_object_or_404(
            ComicPublisher,
            id=raw_filters["publisher_id"],
        )

    filters = {
        "publisher_id": publisher.id if publisher else None,
        "run_id": run.id if run else None,
        "issue_id": issue.id if issue else None,
        "volume_id": volume.id if volume else None,
        "one_shot_id": one_shot.id if one_shot else None,
    }
    selection = {
        "publisher": publisher,
        "run": run,
        "issue": issue,
        "volume": volume,
        "one_shot": one_shot,
    }

    return filters, selection


def get_filtered_my_comics_querysets(user, filters):
    followed_runs = FollowedRun.objects.filter(
        user=user,
    ).select_related(
        "run",
        "run__publisher",
    ).annotate(
        catalog_issue_count=Count(
            "run__issues",
            distinct=True,
        ),
        tracked_issue_count=Count(
            "run__issues__user_progress",
            filter=Q(run__issues__user_progress__user=user),
            distinct=True,
        ),
    ).order_by(
        "-followed_at",
        "run__publisher__name",
        "run__title",
    )

    volume_progress = VolumeProgress.objects.filter(
        user=user,
    ).select_related(
        "volume",
        "volume__run",
        "volume__publisher",
    ).order_by(
        "volume__publisher__name",
        "volume__run__title",
        "volume__volume_number",
        "volume__release_date",
        "volume__title",
    )

    issue_progress = IssueProgress.objects.filter(
        user=user,
    ).select_related(
        "issue",
        "issue__run",
        "issue__run__publisher",
    ).order_by(
        "issue__run__publisher__name",
        "issue__run__title",
        "issue__published_date",
        "issue__issue_number",
    )

    one_shot_progress = OneShotProgress.objects.filter(
        user=user,
    ).select_related(
        "one_shot",
        "one_shot__publisher",
    ).order_by(
        "one_shot__publisher__name",
        "one_shot__published_date",
        "one_shot__title",
    )

    publisher_id = filters["publisher_id"]
    run_id = filters["run_id"]
    issue_id = filters["issue_id"]
    volume_id = filters["volume_id"]
    one_shot_id = filters["one_shot_id"]

    if publisher_id:
        followed_runs = followed_runs.filter(run__publisher_id=publisher_id)
        volume_progress = volume_progress.filter(volume__publisher_id=publisher_id)
        issue_progress = issue_progress.filter(issue__run__publisher_id=publisher_id)
        one_shot_progress = one_shot_progress.filter(one_shot__publisher_id=publisher_id)

    if one_shot_id:
        followed_runs = followed_runs.none()
        volume_progress = volume_progress.none()
        issue_progress = issue_progress.none()
        one_shot_progress = one_shot_progress.filter(one_shot_id=one_shot_id)
    elif issue_id:
        followed_runs = followed_runs.filter(run__issues__id=issue_id).distinct()
        volume_progress = volume_progress.filter(
            volume__volume_issues__issue_id=issue_id,
        ).distinct()
        issue_progress = issue_progress.filter(issue_id=issue_id)
        one_shot_progress = one_shot_progress.none()
    elif volume_id:
        followed_runs = followed_runs.filter(run__volumes__id=volume_id).distinct()
        volume_progress = volume_progress.filter(volume_id=volume_id)
        issue_progress = issue_progress.filter(
            issue__collected_in__volume_id=volume_id,
        ).distinct()
        one_shot_progress = one_shot_progress.none()
    elif run_id:
        followed_runs = followed_runs.filter(run_id=run_id)
        volume_progress = volume_progress.filter(volume__run_id=run_id)
        issue_progress = issue_progress.filter(issue__run_id=run_id)
        one_shot_progress = one_shot_progress.none()

    return followed_runs, volume_progress, issue_progress, one_shot_progress



def get_user_tracked_publisher_ids(user):
    publisher_ids = set(
        FollowedRun.objects.filter(user=user).values_list(
            "run__publisher_id",
            flat=True,
        )
    )
    publisher_ids.update(
        IssueProgress.objects.filter(user=user).values_list(
            "issue__run__publisher_id",
            flat=True,
        )
    )
    publisher_ids.update(
        VolumeProgress.objects.filter(user=user).values_list(
            "volume__publisher_id",
            flat=True,
        )
    )
    publisher_ids.update(
        OneShotProgress.objects.filter(user=user).values_list(
            "one_shot__publisher_id",
            flat=True,
        )
    )
    return [publisher_id for publisher_id in publisher_ids if publisher_id]


def get_user_tracked_run_ids(user):
    run_ids = set(
        FollowedRun.objects.filter(user=user).values_list("run_id", flat=True)
    )
    run_ids.update(
        IssueProgress.objects.filter(user=user).values_list(
            "issue__run_id",
            flat=True,
        )
    )
    run_ids.update(
        VolumeProgress.objects.filter(user=user).values_list(
            "volume__run_id",
            flat=True,
        )
    )
    return [run_id for run_id in run_ids if run_id]


def get_user_tracked_issue_ids(user):
    issue_ids = set(
        IssueProgress.objects.filter(user=user).values_list("issue_id", flat=True)
    )

    followed_run_ids = FollowedRun.objects.filter(user=user).values_list(
        "run_id",
        flat=True,
    )
    issue_ids.update(
        ComicIssue.objects.filter(run_id__in=followed_run_ids).values_list(
            "id",
            flat=True,
        )
    )

    followed_volume_ids = VolumeProgress.objects.filter(user=user).values_list(
        "volume_id",
        flat=True,
    )
    issue_ids.update(
        ComicVolumeIssue.objects.filter(
            volume_id__in=followed_volume_ids,
        ).values_list(
            "issue_id",
            flat=True,
        )
    )

    return list(issue_ids)


def get_user_tracked_volume_ids(user):
    return list(
        VolumeProgress.objects.filter(user=user).values_list(
            "volume_id",
            flat=True,
        )
    )


def get_user_tracked_one_shot_ids(user):
    return list(
        OneShotProgress.objects.filter(user=user).values_list(
            "one_shot_id",
            flat=True,
        )
    )


def build_my_comics_url(**params):
    return build_query_url(reverse("reading:my_comics"), **params)
