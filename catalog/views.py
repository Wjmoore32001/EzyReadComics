from urllib.parse import urlencode

from django.db.models import Case, Count, IntegerField, Prefetch, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicOneShot,
    ComicOneShotCredit,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)
from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


BROWSE_INITIAL_RESULT_LIMIT = 10
BROWSE_LOAD_MORE_LIMIT = 10
BROWSE_OPTION_LIMIT = 10


def home(request):
    context = {
        "publisher_count": ComicPublisher.objects.count(),
        "run_count": ComicRun.objects.count(),
        "issue_count": ComicIssue.objects.count(),
        "volume_count": ComicVolume.objects.count(),
        "one_shot_count": ComicOneShot.objects.count(),
        "recent_runs": ComicRun.objects.select_related("publisher").order_by(
            "-updated_at",
            "publisher__name",
            "title",
        )[:5],
        "recent_issues": ComicIssue.objects.select_related(
            "run",
            "run__publisher",
        ).prefetch_related(
            issue_credit_prefetch(),
        ).order_by(
            "-updated_at",
            "run__publisher__name",
            "run__title",
            "issue_number",
        )[:5],
    }

    attach_issue_credit_display(context["recent_issues"])

    return render(request, "catalog/home.html", context)


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

    selected_publisher_id = selected_publisher.id if selected_publisher else None
    selected_run_id = selected_run.id if selected_run else None
    selected_issue_id = selected_issue.id if selected_issue else None
    selected_volume_id = selected_volume.id if selected_volume else None
    selected_one_shot_id = selected_one_shot.id if selected_one_shot else None

    publishers = []
    run_options = []
    issue_options = []
    volume_options = []
    one_shot_options = []

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
    issue_list = []
    one_shot_list = []
    has_more_volumes = True
    has_more_issues = True
    has_more_one_shots = True

    if volumes_initially_loaded:
        volumes, has_more_volumes = slice_with_has_more(
            volumes_queryset,
            limit=BROWSE_INITIAL_RESULT_LIMIT,
        )

    if issues_initially_loaded:
        issue_list, has_more_issues = slice_with_has_more(
            issues_queryset,
            limit=BROWSE_INITIAL_RESULT_LIMIT,
        )

    if one_shots_initially_loaded:
        one_shot_list, has_more_one_shots = slice_with_has_more(
            one_shots_queryset,
            limit=BROWSE_INITIAL_RESULT_LIMIT,
        )

    attach_issue_credit_display(issue_list)
    attach_run_tracking(request, runs)
    attach_volume_tracking(request, volumes)
    attach_issue_tracking(request, issue_list)
    attach_one_shot_tracking(request, one_shot_list)

    selected_items = build_selected_items(
        selected_publisher=selected_publisher,
        selected_run=selected_run,
        selected_issue=selected_issue,
        selected_volume=selected_volume,
        selected_one_shot=selected_one_shot,
    )

    context = {
        "publishers": publishers,
        "run_options": run_options,
        "issue_options": issue_options,
        "volume_options": volume_options,
        "one_shot_options": one_shot_options,
        "runs": runs,
        "volumes": volumes,
        "issues": issue_list,
        "one_shots": one_shot_list,
        "has_more_runs": has_more_runs,
        "has_more_volumes": has_more_volumes,
        "has_more_issues": has_more_issues,
        "has_more_one_shots": has_more_one_shots,
        "runs_initially_loaded": True,
        "volumes_initially_loaded": volumes_initially_loaded,
        "issues_initially_loaded": issues_initially_loaded,
        "one_shots_initially_loaded": one_shots_initially_loaded,
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
        "selected_items": selected_items,
        "browse_initial_limit": BROWSE_INITIAL_RESULT_LIMIT,
        "browse_load_more_limit": BROWSE_LOAD_MORE_LIMIT,
        "browse_option_limit": BROWSE_OPTION_LIMIT,
        "run_status_choices": FollowedRun.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
        "one_shot_status_choices": OneShotProgress.STATUS_CHOICES,
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
            get_publisher_options(search_value),
            offset=option_offset,
        )
        options = [
            build_publisher_option(publisher, selected_option_id)
            for publisher in option_rows
        ]
    elif option_kind == "run":
        option_rows, has_more = get_option_page(
            get_run_options(
                search_value,
                publisher_id=selected_publisher_id,
            ),
            offset=option_offset,
        )
        options = [
            build_run_option(run, selected_option_id)
            for run in option_rows
        ]
    elif option_kind == "issue":
        option_rows, has_more = get_option_page(
            get_issue_options(
                search_value,
                publisher_id=selected_publisher_id,
                run_id=selected_run_id,
            ),
            offset=option_offset,
        )
        options = [
            build_issue_option(issue, selected_option_id)
            for issue in option_rows
        ]
    elif option_kind == "volume":
        option_rows, has_more = get_option_page(
            get_volume_options(
                search_value,
                publisher_id=selected_publisher_id,
                run_id=selected_run_id,
            ),
            offset=option_offset,
        )
        options = [
            build_volume_option(volume, selected_option_id)
            for volume in option_rows
        ]
    elif option_kind == "one_shot":
        option_rows, has_more = get_option_page(
            get_one_shot_options(
                search_value,
                publisher_id=selected_publisher_id,
            ),
            offset=option_offset,
        )
        options = [
            build_one_shot_option(one_shot, selected_option_id)
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


def run_details(request, pk):
    run = get_object_or_404(
        ComicRun.objects.select_related("publisher").prefetch_related(
            "volumes",
        ),
        pk=pk,
    )

    issues = list(
        run.issues.select_related(
            "run",
            "run__publisher",
        ).prefetch_related(
            issue_credit_prefetch(),
        ).order_by(
            "published_date",
            "issue_number",
        )
    )
    attach_issue_credit_display(issues)
    attach_issue_tracking(request, issues)

    volumes = list(
        run.volumes.select_related("publisher", "run").order_by(
            "volume_number",
            "release_date",
            "title",
        )
    )
    default_credits, all_credits = get_unique_run_issue_credits(run)

    attach_run_tracking(request, [run])

    context = {
        "run": run,
        "issues": issues,
        "volumes": volumes,
        "default_credits": default_credits,
        "all_credits": all_credits,
        "current_run_progress": run.user_tracking,
        "run_status_choices": FollowedRun.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
    }

    return render(request, "catalog/run_details.html", context)


def issue_details(request, pk):
    issue = get_object_or_404(
        ComicIssue.objects.select_related("run", "run__publisher").prefetch_related(
            issue_credit_prefetch(),
            "collected_in__volume",
        ),
        pk=pk,
    )
    attach_issue_credit_display([issue])

    parent_run_issues = list(
        issue.run.issues.select_related(
            "run",
            "run__publisher",
        ).prefetch_related(
            issue_credit_prefetch(),
        ).order_by(
            "published_date",
            "issue_number",
        )
    )
    attach_issue_credit_display(parent_run_issues)
    attach_issue_tracking(request, parent_run_issues)

    collected_in = ComicVolumeIssue.objects.select_related(
        "volume",
        "volume__run",
        "volume__publisher",
    ).filter(
        issue=issue,
    ).order_by(
        "volume__volume_number",
        "volume__release_date",
        "volume__title",
    )

    default_credits = issue.credits.select_related("person", "role").filter(
        role__show_by_default=True,
    )
    all_credits = issue.credits.select_related("person", "role")

    attach_issue_tracking(request, [issue])
    attach_run_tracking(request, [issue.run])

    context = {
        "issue": issue,
        "parent_run_issues": parent_run_issues,
        "collected_in": collected_in,
        "default_credits": default_credits,
        "all_credits": all_credits,
        "current_issue_progress": issue.user_tracking,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "is_following_run": bool(issue.run.user_tracking),
    }

    return render(request, "catalog/issue_details.html", context)


def volume_details(request, pk):
    volume = get_object_or_404(
        ComicVolume.objects.select_related("publisher", "run").prefetch_related(
            "credits__person",
            "credits__role",
        ),
        pk=pk,
    )

    volume_run_links = list(
        volume.volume_runs.select_related(
            "run",
            "run__publisher",
        ).order_by(
            "item_order",
            "run__title",
            "run__start_year",
        )
    )

    volume_issues = list(
        ComicVolumeIssue.objects.select_related(
            "issue",
            "issue__run",
            "issue__run__publisher",
        ).prefetch_related(
            Prefetch(
                "issue__credits",
                queryset=ComicIssueCredit.objects.select_related("person", "role"),
            )
        ).filter(
            volume=volume,
        ).order_by(
            "issue_order",
            "issue__published_date",
            "issue__issue_number",
        )
    )

    issues = [volume_issue.issue for volume_issue in volume_issues]
    attach_issue_credit_display(issues)
    attach_issue_tracking(request, issues)

    volume_issue_groups = build_volume_issue_groups(
        volume_issues=volume_issues,
        volume_run_links=volume_run_links,
    )

    default_credits = volume.credits.select_related("person", "role").filter(
        role__show_by_default=True,
    )
    all_credits = volume.credits.select_related("person", "role")

    attach_volume_tracking(request, [volume])

    context = {
        "volume": volume,
        "volume_issues": volume_issues,
        "volume_issue_groups": volume_issue_groups,
        "issues": issues,
        "default_credits": default_credits,
        "all_credits": all_credits,
        "current_volume_progress": volume.user_tracking,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
    }

    return render(request, "catalog/volume_details.html", context)


def one_shot_details(request, pk):
    one_shot = get_object_or_404(
        ComicOneShot.objects.select_related("publisher").prefetch_related(
            "credits__person",
            "credits__role",
        ),
        pk=pk,
    )

    attach_one_shot_tracking(request, [one_shot])

    default_credits = one_shot.credits.select_related("person", "role").filter(
        role__show_by_default=True,
    )
    all_credits = one_shot.credits.select_related("person", "role")

    context = {
        "one_shot": one_shot,
        "default_credits": default_credits,
        "all_credits": all_credits,
        "current_one_shot_progress": one_shot.user_tracking,
        "one_shot_status_choices": OneShotProgress.STATUS_CHOICES,
    }

    return render(request, "catalog/one_shot_details.html", context)


def build_volume_issue_groups(*, volume_issues, volume_run_links):
    groups = []
    groups_by_run_id = {}

    def get_or_create_group(run, issue_numbers_text=""):
        if not run:
            return None

        group = groups_by_run_id.get(run.id)

        if group is None:
            group = {
                "run": run,
                "issue_numbers_text": issue_numbers_text,
                "volume_issues": [],
            }
            groups_by_run_id[run.id] = group
            groups.append(group)
        elif issue_numbers_text and not group["issue_numbers_text"]:
            group["issue_numbers_text"] = issue_numbers_text

        return group

    for volume_run_link in volume_run_links:
        get_or_create_group(
            volume_run_link.run,
            issue_numbers_text=volume_run_link.issue_numbers_text,
        )

    for volume_issue in volume_issues:
        group = get_or_create_group(volume_issue.issue.run)

        if group is not None:
            group["volume_issues"].append(volume_issue)

    return groups


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
        selected_run = selected_volume.run
        selected_publisher = selected_volume.publisher
    elif run_id:
        selected_run = get_object_or_404(
            ComicRun.objects.select_related("publisher"),
            id=run_id,
        )
        selected_publisher = selected_run.publisher
    elif publisher_id:
        selected_publisher = get_object_or_404(
            ComicPublisher,
            id=publisher_id,
        )

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
        "-run__start_year",
        "-release_date",
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
    )

    if selected_one_shot:
        runs = runs.none()
        volumes = volumes.none()
        issues = issues.none()
        one_shots = one_shots.filter(id=selected_one_shot.id)
    elif selected_issue:
        runs = runs.filter(id=selected_issue.run_id)
        volumes = volumes.filter(volume_issues__issue=selected_issue).distinct()
        issues = issues.filter(id=selected_issue.id)
        one_shots = one_shots.none()
    elif selected_volume:
        runs = runs.filter(id=selected_volume.run_id)
        volumes = volumes.filter(id=selected_volume.id)
        issues = issues.filter(collected_in__volume=selected_volume).distinct()
        one_shots = one_shots.none()
    elif selected_run:
        runs = runs.filter(id=selected_run.id)
        volumes = volumes.filter(run=selected_run)
        issues = issues.filter(run=selected_run)
        one_shots = one_shots.none()
    elif selected_publisher:
        runs = runs.filter(publisher=selected_publisher)
        volumes = volumes.filter(publisher=selected_publisher)
        issues = issues.filter(run__publisher=selected_publisher)
        one_shots = one_shots.filter(publisher=selected_publisher)

    return runs, volumes, issues, one_shots


def slice_with_has_more(queryset, *, limit, offset=0):
    items = list(queryset[offset : offset + limit])
    return items, len(items) == limit


def get_option_page(queryset, *, offset=0):
    return slice_with_has_more(
        queryset,
        limit=BROWSE_OPTION_LIMIT,
        offset=offset,
    )


def get_publisher_options(search_value):
    publishers = ComicPublisher.objects.all()

    if search_value:
        publishers = publishers.filter(
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
    else:
        publishers = publishers.order_by("name")

    return publishers


def get_run_options(search_value, *, publisher_id=None):
    runs = ComicRun.objects.select_related("publisher")

    if publisher_id:
        runs = runs.filter(publisher_id=publisher_id)

    if search_value:
        runs = runs.filter(
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
    else:
        runs = runs.order_by(
            "-start_year",
            "-first_issue_date",
            "publisher__name",
            "title",
        )

    return runs


def get_issue_options(search_value, *, publisher_id=None, run_id=None):
    issues = ComicIssue.objects.select_related(
        "run",
        "run__publisher",
    )

    if publisher_id:
        issues = issues.filter(run__publisher_id=publisher_id)

    if run_id:
        issues = issues.filter(run_id=run_id)

    if search_value:
        issues = issues.filter(
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
    else:
        issues = issues.order_by(
            "-run__start_year",
            "-published_date",
            "run__title",
            "issue_number",
        )

    return issues


def get_volume_options(search_value, *, publisher_id=None, run_id=None):
    volumes = ComicVolume.objects.select_related(
        "publisher",
        "run",
    )

    if publisher_id:
        volumes = volumes.filter(publisher_id=publisher_id)

    if run_id:
        volumes = volumes.filter(run_id=run_id)

    if search_value:
        volumes = volumes.filter(
            Q(title__icontains=search_value)
            | Q(run__title__icontains=search_value)
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
        ).order_by(
            "search_rank",
            "-run__start_year",
            "-release_date",
            "run__title",
            "volume_number",
            "title",
        )
    else:
        volumes = volumes.order_by(
            "-run__start_year",
            "-release_date",
            "run__title",
            "volume_number",
            "title",
        )

    return volumes


def get_one_shot_options(search_value, *, publisher_id=None):
    one_shots = ComicOneShot.objects.select_related("publisher")

    if publisher_id:
        one_shots = one_shots.filter(publisher_id=publisher_id)

    if search_value:
        one_shots = one_shots.filter(
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
        )
    else:
        one_shots = one_shots.order_by(
            "-published_date",
            "-start_year",
            "publisher__name",
            "title",
        )

    return one_shots


def build_publisher_option(publisher, selected_option_id):
    return {
        "id": publisher.id,
        "url": browse_url_with_params(publisher=publisher.id),
        "label": publisher.name,
        "meta": "",
        "search_label": publisher.name,
        "active": publisher.id == selected_option_id,
    }


def build_run_option(run, selected_option_id):
    year = run.start_year or "Unknown year"
    issue_count = f"{run.issue_count} issues" if run.issue_count else "issue count unknown"

    return {
        "id": run.id,
        "url": browse_url_with_params(run=run.id),
        "label": f"{year} — {run.title}",
        "meta": f"{run.publisher.name} · {issue_count}",
        "search_label": f"{run.title} {run.start_year} {run.publisher.name}",
        "active": run.id == selected_option_id,
    }


def build_issue_option(issue, selected_option_id):
    return {
        "id": issue.id,
        "url": browse_url_with_params(issue=issue.id),
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


def build_volume_option(volume, selected_option_id):
    meta_parts = [
        volume.publisher.name,
        str(volume.run),
    ]

    if volume.issue_count:
        meta_parts.append(f"{volume.issue_count} issues")

    return {
        "id": volume.id,
        "url": browse_url_with_params(volume=volume.id),
        "label": str(volume),
        "meta": " · ".join(meta_parts),
        "search_label": (
            f"{volume.title} {volume.run.title} "
            f"{volume.volume_number} {volume.publisher.name}"
        ),
        "active": volume.id == selected_option_id,
    }


def build_one_shot_option(one_shot, selected_option_id):
    meta_parts = [
        one_shot.publisher.name,
        format_date_or_unknown(one_shot.published_date),
    ]

    return {
        "id": one_shot.id,
        "url": browse_url_with_params(one_shot=one_shot.id),
        "label": one_shot.title,
        "meta": " · ".join(meta_parts),
        "search_label": f"{one_shot.title} {one_shot.start_year} {one_shot.publisher.name}",
        "active": one_shot.id == selected_option_id,
    }


def build_run_row_item(run):
    return {
        "row_url": reverse("catalog:run_details", args=[run.id]),
        "aria_label": f"Open run details for {run}",
        "year": run.start_year or "Unknown",
        "year_muted": not bool(run.start_year),
        "title": run.title,
        "publisher": run.publisher.name,
        "status": run.get_status_display(),
        "issue_count": str(run.issue_count) if run.issue_count else "Unknown",
        "issue_count_muted": not bool(run.issue_count),
        "first_issue_date": format_date_or_unknown(run.first_issue_date),
        "first_issue_date_muted": not bool(run.first_issue_date),
        "last_issue_date": format_date_or_unknown(run.last_issue_date),
        "last_issue_date_muted": not bool(run.last_issue_date),
        "tracking": build_tracking_data(
            item_type="run",
            action_url=reverse("reading:set_run_status", args=[run.id]),
            progress=run.user_tracking,
            status_choices=FollowedRun.STATUS_CHOICES,
            catalog_issue_count=run.catalog_issue_count,
            tracked_issue_count=run.tracked_issue_count,
        ),
    }


def build_volume_row_item(volume):
    has_issue_range = bool(volume.first_issue_number or volume.last_issue_number)

    return {
        "row_url": reverse("catalog:volume_details", args=[volume.id]),
        "aria_label": f"Open volume details for {volume}",
        "volume": str(volume),
        "run": str(volume.run),
        "publisher": volume.publisher.name,
        "issue_range": (
            f"#{volume.first_issue_number or '?'}–{volume.last_issue_number or '?'}"
            if has_issue_range
            else "Unknown"
        ),
        "issue_range_muted": not has_issue_range,
        "issue_count": str(volume.issue_count) if volume.issue_count else "Unknown",
        "issue_count_muted": not bool(volume.issue_count),
        "release_date": format_date_or_unknown(volume.release_date),
        "release_date_muted": not bool(volume.release_date),
        "tracking": build_tracking_data(
            item_type="volume",
            action_url=reverse("reading:set_volume_status", args=[volume.id]),
            progress=volume.user_tracking,
            status_choices=VolumeProgress.STATUS_CHOICES,
        ),
    }


def build_issue_row_item(issue):
    return {
        "row_url": reverse("catalog:issue_details", args=[issue.id]),
        "aria_label": f"Open issue details for issue {issue.issue_number}",
        "year": issue.run.start_year or "Unknown",
        "year_muted": not bool(issue.run.start_year),
        "run": issue.run.title,
        "issue": f"#{issue.issue_number}",
        "published_date": format_date_or_unknown(issue.published_date),
        "published_date_muted": not bool(issue.published_date),
        "writer": issue.display_writers or "Unknown",
        "writer_muted": not bool(issue.display_writers),
        "tracking": build_tracking_data(
            item_type="issue",
            action_url=reverse("reading:set_issue_status", args=[issue.id]),
            progress=issue.user_tracking,
            status_choices=IssueProgress.STATUS_CHOICES,
        ),
    }


def build_one_shot_row_item(one_shot):
    return {
        "row_url": reverse("catalog:one_shot_details", args=[one_shot.id]),
        "aria_label": f"Open one-shot details for {one_shot.title}",
        "title": one_shot.title,
        "publisher": one_shot.publisher.name,
        "published_date": format_date_or_unknown(one_shot.published_date),
        "published_date_muted": not bool(one_shot.published_date),
        "start_year": one_shot.start_year or "Unknown",
        "start_year_muted": not bool(one_shot.start_year),
        "tracking": build_tracking_data(
            item_type="one_shot",
            action_url=reverse("reading:set_one_shot_status", args=[one_shot.id]),
            progress=one_shot.user_tracking,
            status_choices=OneShotProgress.STATUS_CHOICES,
        ),
    }


def build_tracking_data(
    *,
    item_type,
    action_url,
    progress,
    status_choices,
    catalog_issue_count=0,
    tracked_issue_count=0,
):
    return {
        "item_type": item_type,
        "action_url": action_url,
        "tracked": bool(progress),
        "status": progress.status if progress else "",
        "status_choices": build_status_choices(status_choices),
        "catalog_issue_count": catalog_issue_count,
        "tracked_issue_count": tracked_issue_count,
    }


def build_status_choices(status_choices):
    return [
        {
            "value": value,
            "label": label,
        }
        for value, label in status_choices
    ]


def attach_run_tracking(request, runs):
    run_ids = [run.id for run in runs]

    if not run_ids:
        return

    catalog_issue_counts = {
        row["run_id"]: row["issue_total"]
        for row in ComicIssue.objects.filter(
            run_id__in=run_ids,
        )
        .values("run_id")
        .annotate(issue_total=Count("id"))
    }

    progress_by_run_id = {}
    tracked_issue_counts = {}

    if request.user.is_authenticated:
        progress_by_run_id = {
            progress.run_id: progress
            for progress in FollowedRun.objects.filter(
                user=request.user,
                run_id__in=run_ids,
            )
        }

        tracked_issue_counts = {
            row["issue__run_id"]: row["issue_total"]
            for row in IssueProgress.objects.filter(
                user=request.user,
                issue__run_id__in=run_ids,
            )
            .values("issue__run_id")
            .annotate(issue_total=Count("issue_id", distinct=True))
        }

    for run in runs:
        run.user_tracking = progress_by_run_id.get(run.id)
        run.catalog_issue_count = catalog_issue_counts.get(run.id, 0)
        run.tracked_issue_count = tracked_issue_counts.get(run.id, 0)


def attach_issue_tracking(request, issues):
    issue_ids = [issue.id for issue in issues]

    if not request.user.is_authenticated or not issue_ids:
        for issue in issues:
            issue.user_tracking = None
        return

    progress_by_issue_id = {
        progress.issue_id: progress
        for progress in IssueProgress.objects.filter(
            user=request.user,
            issue_id__in=issue_ids,
        )
    }

    for issue in issues:
        issue.user_tracking = progress_by_issue_id.get(issue.id)


def attach_volume_tracking(request, volumes):
    volume_ids = [volume.id for volume in volumes]

    if not request.user.is_authenticated or not volume_ids:
        for volume in volumes:
            volume.user_tracking = None
        return

    progress_by_volume_id = {
        progress.volume_id: progress
        for progress in VolumeProgress.objects.filter(
            user=request.user,
            volume_id__in=volume_ids,
        )
    }

    for volume in volumes:
        volume.user_tracking = progress_by_volume_id.get(volume.id)


def attach_one_shot_tracking(request, one_shots):
    one_shot_ids = [one_shot.id for one_shot in one_shots]

    if not request.user.is_authenticated or not one_shot_ids:
        for one_shot in one_shots:
            one_shot.user_tracking = None
        return

    progress_by_one_shot_id = {
        progress.one_shot_id: progress
        for progress in OneShotProgress.objects.filter(
            user=request.user,
            one_shot_id__in=one_shot_ids,
        )
    }

    for one_shot in one_shots:
        one_shot.user_tracking = progress_by_one_shot_id.get(one_shot.id)


def format_date_or_unknown(value):
    if not value:
        return "Unknown"

    return value.strftime("%Y-%m-%d")


def browse_url_with_params(**params):
    cleaned_params = {
        key: value
        for key, value in params.items()
        if value not in [None, ""]
    }

    if not cleaned_params:
        return reverse("catalog:browse")

    return f"{reverse('catalog:browse')}?{urlencode(cleaned_params)}"


def issue_credit_prefetch():
    return Prefetch(
        "credits",
        queryset=ComicIssueCredit.objects.select_related("person", "role").order_by(
            "role__display_order",
            "credit_order",
            "person__name",
        ),
    )


def one_shot_credit_prefetch():
    return Prefetch(
        "credits",
        queryset=ComicOneShotCredit.objects.select_related("person", "role").order_by(
            "role__display_order",
            "credit_order",
            "person__name",
        ),
    )


def get_unique_run_issue_credits(run):
    credits = ComicIssueCredit.objects.select_related(
        "person",
        "role",
    ).filter(
        issue__run=run,
    ).order_by(
        "role__display_order",
        "credit_order",
        "person__name",
        "issue__published_date",
        "issue__issue_number",
        "issue__id",
    )

    unique_credits = []
    seen_credit_keys = set()

    for credit in credits:
        credit_key = (credit.role_id, credit.person_id)

        if credit_key in seen_credit_keys:
            continue

        seen_credit_keys.add(credit_key)
        unique_credits.append(credit)

    default_credits = [
        credit
        for credit in unique_credits
        if credit.role.show_by_default
    ]

    return default_credits, unique_credits


def attach_issue_credit_display(issues):
    for issue in issues:
        writer_names = []
        penciller_names = []

        for credit in issue.credits.all():
            role_name = credit.role.name.casefold()

            if role_name == "writer":
                writer_names.append(credit.person.name)
            elif role_name == "penciller":
                penciller_names.append(credit.person.name)

        issue.display_writers = ", ".join(writer_names)
        issue.display_pencillers = ", ".join(penciller_names)


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
