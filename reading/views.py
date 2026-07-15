from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from catalog.models import (
    ComicIssue,
    ComicOneShot,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)
from reading.forms import (
    IssueProgressForm,
    OneShotProgressForm,
    RunProgressForm,
    VolumeProgressForm,
)
from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


UNFOLLOW_STATUS_VALUE = "__unfollow__"
MY_COMICS_INITIAL_RESULT_LIMIT = 10
MY_COMICS_LOAD_MORE_LIMIT = 10
MY_COMICS_OPTION_LIMIT = 10


def signup_required(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)

        next_url = get_safe_next_url(request, reverse("catalog:browse"))
        signup_url = f"{reverse('signup')}?{urlencode({'next': next_url})}"

        if is_ajax_request(request):
            return JsonResponse(
                {
                    "ok": False,
                    "auth_required": True,
                    "redirect_url": signup_url,
                },
                status=401,
            )

        return redirect(signup_url)

    return wrapped_view


@login_required
def my_comics(request):
    filters = get_my_comics_filters(request)
    followed_runs, volume_progress, issue_progress, one_shot_progress = get_filtered_my_comics_querysets(
        request.user,
        filters,
    )

    runs, has_more_runs = slice_with_has_more(
        followed_runs,
        limit=MY_COMICS_INITIAL_RESULT_LIMIT,
    )

    volumes_initially_loaded = False
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

    selected_publisher = get_selected_publisher(filters)
    selected_run = get_selected_run(filters)
    selected_issue = get_selected_issue(filters)
    selected_one_shot = get_selected_one_shot(filters)

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
        "run_status_choices": FollowedRun.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
        "one_shot_status_choices": OneShotProgress.STATUS_CHOICES,
        "status_filter_choices": FollowedRun.STATUS_CHOICES,
        "publisher_options": [],
        "run_options": [],
        "issue_options": [],
        "one_shot_options": [],
        "publisher_filter_options": [],
        "run_filter_options": [],
        "issue_filter_options": [],
        "one_shot_filter_options": [],
        "status_filter_options": build_my_comics_status_filter_options(filters),
        "all_publishers_url": build_my_comics_url(status=filters["status"]),
        "all_runs_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            status=filters["status"],
        ),
        "all_issues_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            run=filters["run_id"],
            status=filters["status"],
        ),
        "all_one_shots_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            status=filters["status"],
        ),
        "all_statuses_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            run=filters["run_id"],
            issue=filters["issue_id"],
            one_shot=filters["one_shot_id"],
        ),
        "clear_run_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            status=filters["status"],
        ),
        "clear_issue_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            run=filters["run_id"],
            status=filters["status"],
        ),
        "clear_one_shot_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            status=filters["status"],
        ),
        "clear_status_url": build_my_comics_url(
            publisher=filters["publisher_id"],
            run=filters["run_id"],
            issue=filters["issue_id"],
            one_shot=filters["one_shot_id"],
        ),
        "selected_publisher": selected_publisher,
        "selected_run": selected_run,
        "selected_issue": selected_issue,
        "selected_one_shot": selected_one_shot,
        "selected_publisher_id": filters["publisher_id"],
        "selected_run_id": filters["run_id"],
        "selected_issue_id": filters["issue_id"],
        "selected_one_shot_id": filters["one_shot_id"],
        "selected_status": filters["status"],
        "filters_active": my_comics_filters_active(filters),
        "unfollow_status_value": UNFOLLOW_STATUS_VALUE,
        "my_comics_initial_limit": MY_COMICS_INITIAL_RESULT_LIMIT,
        "my_comics_load_more_limit": MY_COMICS_LOAD_MORE_LIMIT,
        "my_comics_option_limit": MY_COMICS_OPTION_LIMIT,
    }

    return render(request, "reading/my_comics.html", context)


@login_required
@require_GET
def my_comics_items(request):
    item_kind = (request.GET.get("kind") or "").strip()
    offset = get_nonnegative_int_query_param(request, "offset")
    filters = get_my_comics_filters(request)
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
    selected_status = get_valid_status_filter(request.GET.get("status") or "")
    selected_publisher_id = get_int_query_param(request, "publisher")
    selected_run_id = get_int_query_param(request, "run")

    if option_kind == "publisher":
        tracked_publisher_ids = get_user_tracked_publisher_ids(request.user)
        option_rows, has_more = get_my_comics_option_page(
            get_my_comics_publisher_options(
                tracked_publisher_ids=tracked_publisher_ids,
                search_value=search_value,
            ),
            offset=option_offset,
        )
        options = [
            build_my_comics_publisher_json_option(
                publisher,
                selected_option_id=selected_option_id,
                selected_status=selected_status,
            )
            for publisher in option_rows
        ]
    elif option_kind == "run":
        tracked_run_ids = get_user_tracked_run_ids(request.user)
        option_rows, has_more = get_my_comics_option_page(
            get_my_comics_run_options(
                tracked_run_ids=tracked_run_ids,
                selected_publisher_id=selected_publisher_id,
                search_value=search_value,
            ),
            offset=option_offset,
        )
        options = [
            build_my_comics_run_json_option(
                run,
                selected_option_id=selected_option_id,
                selected_publisher_id=selected_publisher_id,
                selected_status=selected_status,
            )
            for run in option_rows
        ]
    elif option_kind == "issue":
        tracked_issue_ids = get_user_tracked_issue_ids(request.user)
        option_rows, has_more = get_my_comics_option_page(
            get_my_comics_issue_options(
                tracked_issue_ids=tracked_issue_ids,
                selected_publisher_id=selected_publisher_id,
                selected_run_id=selected_run_id,
                search_value=search_value,
            ),
            offset=option_offset,
        )
        options = [
            build_my_comics_issue_json_option(
                issue,
                selected_option_id=selected_option_id,
                selected_publisher_id=selected_publisher_id,
                selected_run_id=selected_run_id,
                selected_status=selected_status,
            )
            for issue in option_rows
        ]
    elif option_kind == "one_shot":
        tracked_one_shot_ids = get_user_tracked_one_shot_ids(request.user)
        option_rows, has_more = get_my_comics_option_page(
            get_my_comics_one_shot_options(
                tracked_one_shot_ids=tracked_one_shot_ids,
                selected_publisher_id=selected_publisher_id,
                search_value=search_value,
            ),
            offset=option_offset,
        )
        options = [
            build_my_comics_one_shot_json_option(
                one_shot,
                selected_option_id=selected_option_id,
                selected_publisher_id=selected_publisher_id,
                selected_status=selected_status,
            )
            for one_shot in option_rows
        ]
    elif option_kind == "status":
        option_rows, has_more = get_my_comics_option_page(
            get_my_comics_status_options(search_value),
            offset=option_offset,
        )
        options = [
            build_my_comics_status_json_option(
                option,
                filters={
                    "publisher_id": selected_publisher_id,
                    "run_id": selected_run_id,
                    "issue_id": get_int_query_param(request, "issue"),
                    "one_shot_id": get_int_query_param(request, "one_shot"),
                    "status": selected_status,
                },
            )
            for option in option_rows
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


@require_GET
@signup_required
def run_follow_options(request, run_id):
    run = get_object_or_404(ComicRun.objects.select_related("publisher"), id=run_id)

    issues = list(
        ComicIssue.objects.filter(
            run=run,
        ).order_by(
            "published_date",
            "issue_number",
        )
    )

    progress_by_issue_id = {
        progress.issue_id: progress
        for progress in IssueProgress.objects.filter(
            user=request.user,
            issue_id__in=[issue.id for issue in issues],
        )
    }

    return JsonResponse(
        {
            "ok": True,
            "run": {
                "id": run.id,
                "title": str(run),
            },
            "run_status_choices": build_status_choices(FollowedRun.STATUS_CHOICES),
            "issue_status_choices": build_status_choices(IssueProgress.STATUS_CHOICES),
            "issues": [
                build_run_follow_issue_option(issue, progress_by_issue_id.get(issue.id))
                for issue in issues
            ],
        }
    )


@require_POST
@signup_required
def follow_run(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)
    status = get_requested_status(request, FollowedRun.STATUS_PLANNED)
    apply_to_issues = request.POST.get("apply_to_issues") == "1"

    form = RunProgressForm({"status": status})

    if not form.is_valid():
        return invalid_tracking_status_response(
            request,
            error_message="Choose a valid reading status.",
            redirect_url=reverse("catalog:run_details", args=[run.id]),
        )

    status = form.cleaned_data["status"]

    try:
        issue_status_plan = build_run_issue_status_plan(
            request=request,
            run=run,
            default_status=status,
        )
    except ValueError as error:
        return invalid_tracking_status_response(
            request,
            error_message=str(error),
            redirect_url=reverse("catalog:run_details", args=[run.id]),
        )

    with transaction.atomic():
        followed_run, created = FollowedRun.objects.get_or_create(
            user=request.user,
            run=run,
            defaults={
                "status": status,
            },
        )

        if not created and followed_run.status != status:
            followed_run.status = status
            followed_run.save(update_fields=["status", "updated_at"])

        changed_issue_count = 0

        if apply_to_issues:
            changed_issue_count = apply_run_issue_status_plan(
                user=request.user,
                issue_status_plan=issue_status_plan,
            )

    status_label = get_status_label(FollowedRun.STATUS_CHOICES, status)

    if changed_issue_count:
        issue_label = "issue status" if changed_issue_count == 1 else "issue statuses"
        message = (
            f"{run} was added to My Comics as {status_label}, "
            f"and {changed_issue_count} {issue_label} were updated."
        )
    elif created:
        message = f"{run} was added to My Comics as {status_label}."
    else:
        message = f"{run} is already in My Comics and was saved as {status_label}."

    messages.success(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("catalog:run_details", args=[run.id]),
        payload={
            "message": message,
            "item_type": "run",
            "tracking": build_run_tracking_payload(request.user, run),
        },
    )


@require_POST
@signup_required
def set_run_status(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)
    requested_status = get_requested_status(request, FollowedRun.STATUS_PLANNED)

    if requested_status == UNFOLLOW_STATUS_VALUE:
        return unfollow_run_from_status_form(request, run)

    form = RunProgressForm({"status": requested_status})

    if not form.is_valid():
        return invalid_tracking_status_response(
            request,
            error_message="Choose a valid reading status.",
            redirect_url=reverse("catalog:run_details", args=[run.id]),
        )

    new_status = form.cleaned_data["status"]
    apply_to_issues = request.POST.get("apply_to_issues") == "1"

    try:
        issue_status_plan = build_run_issue_status_plan(
            request=request,
            run=run,
            default_status=new_status,
        )
    except ValueError as error:
        return invalid_tracking_status_response(
            request,
            error_message=str(error),
            redirect_url=reverse("catalog:run_details", args=[run.id]),
        )

    with transaction.atomic():
        followed_run, created = FollowedRun.objects.select_for_update().get_or_create(
            user=request.user,
            run=run,
            defaults={
                "status": new_status,
            },
        )

        previous_status = followed_run.status

        if not created and previous_status != new_status:
            followed_run.status = new_status
            followed_run.save(update_fields=["status", "updated_at"])

        changed_issue_count = 0

        if apply_to_issues:
            changed_issue_count = apply_run_issue_status_plan(
                user=request.user,
                issue_status_plan=issue_status_plan,
            )

    status_label = get_status_label(FollowedRun.STATUS_CHOICES, new_status)

    if changed_issue_count:
        issue_label = "issue status" if changed_issue_count == 1 else "issue statuses"
        message = (
            f"{run} was saved as {status_label}, "
            f"and {changed_issue_count} {issue_label} were updated."
        )
    else:
        message = f"Your status for {run} was saved as {status_label}."

    messages.success(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("reading:my_comics"),
        payload={
            "message": message,
            "item_type": "run",
            "tracking": build_run_tracking_payload(request.user, run),
        },
    )


@login_required
@require_POST
def unfollow_run(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)
    return unfollow_run_from_status_form(request, run)


def unfollow_run_from_status_form(request, run):
    remove_issues = request.POST.get("remove_issues") == "1"

    with transaction.atomic():
        deleted_count, _ = FollowedRun.objects.filter(
            user=request.user,
            run=run,
        ).delete()
        removed_issue_count = 0

        if remove_issues:
            removed_issue_count = remove_run_issue_statuses(
                user=request.user,
                run=run,
            )

    if deleted_count and removed_issue_count:
        issue_label = "issue status" if removed_issue_count == 1 else "issue statuses"
        message = f"{run} was unfollowed, and {removed_issue_count} {issue_label} were removed."
        messages.success(request, message)
    elif deleted_count:
        message = f"{run} was removed from your followed runs."
        messages.success(request, message)
    else:
        message = f"{run} was not in your followed runs."
        messages.info(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("reading:my_comics"),
        payload={
            "message": message,
            "item_type": "run",
            "tracking": build_run_tracking_payload(request.user, run),
        },
    )


@require_POST
@signup_required
def set_issue_status(request, issue_id):
    issue = get_object_or_404(
        ComicIssue.objects.select_related("run"),
        id=issue_id,
    )
    requested_status = get_requested_status(request, IssueProgress.STATUS_PLANNED)

    if requested_status == UNFOLLOW_STATUS_VALUE:
        return remove_issue_status_from_status_form(request, issue)

    form = IssueProgressForm({"status": requested_status})

    if not form.is_valid():
        return invalid_tracking_status_response(
            request,
            error_message="Choose a valid reading status.",
            redirect_url=reverse("catalog:issue_details", args=[issue.id]),
        )

    status = form.cleaned_data["status"]

    FollowedRun.objects.get_or_create(
        user=request.user,
        run=issue.run,
        defaults={
            "status": FollowedRun.STATUS_PLANNED,
        },
    )

    IssueProgress.objects.update_or_create(
        user=request.user,
        issue=issue,
        defaults={
            "status": status,
        },
    )

    run_read_offer = None

    if status == IssueProgress.STATUS_READ:
        run_read_offer = build_run_read_offer_if_complete(request.user, issue.run)

    message = f"Your status for {issue} was saved."
    messages.success(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("catalog:issue_details", args=[issue.id]),
        payload={
            "message": message,
            "item_type": "issue",
            "tracking": build_issue_tracking_payload(request.user, issue),
            "run_read_offer": run_read_offer,
        },
    )


@login_required
@require_POST
def remove_issue_status(request, issue_id):
    issue = get_object_or_404(ComicIssue.objects.select_related("run"), id=issue_id)
    return remove_issue_status_from_status_form(request, issue)


def remove_issue_status_from_status_form(request, issue):
    deleted_count, _ = IssueProgress.objects.filter(
        user=request.user,
        issue=issue,
    ).delete()

    if deleted_count:
        message = f"Your status for {issue} was removed."
        messages.success(request, message)
    else:
        message = f"{issue} did not have a saved status."
        messages.info(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("reading:my_comics"),
        payload={
            "message": message,
            "item_type": "issue",
            "tracking": build_issue_tracking_payload(request.user, issue),
        },
    )


@require_POST
@signup_required
def set_volume_status(request, volume_id):
    volume = get_object_or_404(
        ComicVolume.objects.select_related("run"),
        id=volume_id,
    )
    requested_status = get_requested_status(request, VolumeProgress.STATUS_PLANNED)

    if requested_status == UNFOLLOW_STATUS_VALUE:
        return remove_volume_status_from_status_form(request, volume)

    form = VolumeProgressForm({"status": requested_status})

    if not form.is_valid():
        return invalid_tracking_status_response(
            request,
            error_message="Choose a valid reading status.",
            redirect_url=reverse("catalog:volume_details", args=[volume.id]),
        )

    status = form.cleaned_data["status"]

    FollowedRun.objects.get_or_create(
        user=request.user,
        run=volume.run,
        defaults={
            "status": FollowedRun.STATUS_PLANNED,
        },
    )

    VolumeProgress.objects.update_or_create(
        user=request.user,
        volume=volume,
        defaults={
            "status": status,
        },
    )

    marked_issue_count = 0

    if status == VolumeProgress.STATUS_READ:
        volume_issue_links = ComicVolumeIssue.objects.select_related(
            "issue",
        ).filter(
            volume=volume,
        )

        for volume_issue_link in volume_issue_links:
            IssueProgress.objects.update_or_create(
                user=request.user,
                issue=volume_issue_link.issue,
                defaults={
                    "status": IssueProgress.STATUS_READ,
                },
            )
            marked_issue_count += 1

    if marked_issue_count:
        issue_label = "issue status" if marked_issue_count == 1 else "issue statuses"
        message = (
            f"Your status for {volume} was saved, "
            f"and {marked_issue_count} {issue_label} were marked as read."
        )
    else:
        message = f"Your status for {volume} was saved."

    messages.success(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("catalog:volume_details", args=[volume.id]),
        payload={
            "message": message,
            "item_type": "volume",
            "tracking": build_volume_tracking_payload(request.user, volume),
        },
    )


@login_required
@require_POST
def remove_volume_status(request, volume_id):
    volume = get_object_or_404(ComicVolume.objects.select_related("run"), id=volume_id)
    return remove_volume_status_from_status_form(request, volume)


def remove_volume_status_from_status_form(request, volume):
    deleted_count, _ = VolumeProgress.objects.filter(
        user=request.user,
        volume=volume,
    ).delete()

    if deleted_count:
        message = f"Your status for {volume} was removed."
        messages.success(request, message)
    else:
        message = f"{volume} did not have a saved status."
        messages.info(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("reading:my_comics"),
        payload={
            "message": message,
            "item_type": "volume",
            "tracking": build_volume_tracking_payload(request.user, volume),
        },
    )


@require_POST
@signup_required
def set_one_shot_status(request, one_shot_id):
    one_shot = get_object_or_404(
        ComicOneShot.objects.select_related("publisher"),
        id=one_shot_id,
    )
    requested_status = get_requested_status(request, OneShotProgress.STATUS_PLANNED)

    if requested_status == UNFOLLOW_STATUS_VALUE:
        return remove_one_shot_status_from_status_form(request, one_shot)

    form = OneShotProgressForm({"status": requested_status})

    if not form.is_valid():
        return invalid_tracking_status_response(
            request,
            error_message="Choose a valid reading status.",
            redirect_url=reverse("catalog:one_shot_details", args=[one_shot.id]),
        )

    status = form.cleaned_data["status"]

    OneShotProgress.objects.update_or_create(
        user=request.user,
        one_shot=one_shot,
        defaults={
            "status": status,
        },
    )

    message = f"Your status for {one_shot} was saved."
    messages.success(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("catalog:one_shot_details", args=[one_shot.id]),
        payload={
            "message": message,
            "item_type": "one_shot",
            "tracking": build_one_shot_tracking_payload(request.user, one_shot),
        },
    )


@login_required
@require_POST
def remove_one_shot_status(request, one_shot_id):
    one_shot = get_object_or_404(
        ComicOneShot.objects.select_related("publisher"),
        id=one_shot_id,
    )
    return remove_one_shot_status_from_status_form(request, one_shot)


def remove_one_shot_status_from_status_form(request, one_shot):
    deleted_count, _ = OneShotProgress.objects.filter(
        user=request.user,
        one_shot=one_shot,
    ).delete()

    if deleted_count:
        message = f"Your status for {one_shot} was removed."
        messages.success(request, message)
    else:
        message = f"{one_shot} did not have a saved status."
        messages.info(request, message)

    return tracking_response(
        request,
        ok=True,
        redirect_url=reverse("reading:my_comics"),
        payload={
            "message": message,
            "item_type": "one_shot",
            "tracking": build_one_shot_tracking_payload(request.user, one_shot),
        },
    )


def get_my_comics_filters(request):
    return {
        "publisher_id": get_int_query_param(request, "publisher"),
        "run_id": get_int_query_param(request, "run"),
        "issue_id": get_int_query_param(request, "issue"),
        "one_shot_id": get_int_query_param(request, "one_shot"),
        "status": get_valid_status_filter(request.GET.get("status") or ""),
    }


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

    return apply_my_comics_filters(
        followed_runs=followed_runs,
        volume_progress=volume_progress,
        issue_progress=issue_progress,
        one_shot_progress=one_shot_progress,
        filters=filters,
    )


def get_selected_publisher(filters):
    if not filters["publisher_id"]:
        return None

    return ComicPublisher.objects.filter(id=filters["publisher_id"]).first()


def get_selected_run(filters):
    if not filters["run_id"]:
        return None

    return ComicRun.objects.select_related("publisher").filter(id=filters["run_id"]).first()


def get_selected_issue(filters):
    if not filters["issue_id"]:
        return None

    return ComicIssue.objects.select_related("run", "run__publisher").filter(
        id=filters["issue_id"],
    ).first()


def get_selected_one_shot(filters):
    if not filters["one_shot_id"]:
        return None

    return ComicOneShot.objects.select_related("publisher").filter(
        id=filters["one_shot_id"],
    ).first()


def get_valid_status_filter(status):
    valid_statuses = {value for value, _label in FollowedRun.STATUS_CHOICES}

    if status not in valid_statuses:
        return ""

    return status


def apply_my_comics_filters(
    *,
    followed_runs,
    volume_progress,
    issue_progress,
    one_shot_progress,
    filters,
):
    publisher_id = filters["publisher_id"]
    run_id = filters["run_id"]
    issue_id = filters["issue_id"]
    one_shot_id = filters["one_shot_id"]
    status = filters["status"]

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
    elif run_id:
        followed_runs = followed_runs.filter(run_id=run_id)
        volume_progress = volume_progress.filter(volume__run_id=run_id)
        issue_progress = issue_progress.filter(issue__run_id=run_id)
        one_shot_progress = one_shot_progress.none()

    if issue_id:
        followed_runs = followed_runs.filter(run__issues__id=issue_id).distinct()
        volume_progress = volume_progress.filter(
            volume__volume_issues__issue_id=issue_id,
        ).distinct()
        issue_progress = issue_progress.filter(issue_id=issue_id)
        one_shot_progress = one_shot_progress.none()

    if status:
        followed_runs = followed_runs.filter(status=status)
        volume_progress = volume_progress.filter(status=status)
        issue_progress = issue_progress.filter(status=status)
        one_shot_progress = one_shot_progress.filter(status=status)

    return followed_runs, volume_progress, issue_progress, one_shot_progress


def my_comics_filters_active(filters):
    return bool(
        filters["publisher_id"]
        or filters["run_id"]
        or filters["issue_id"]
        or filters["one_shot_id"]
        or filters["status"]
    )


def slice_with_has_more(queryset, *, limit, offset=0):
    items = list(queryset[offset : offset + limit + 1])
    return items[:limit], len(items) > limit


def get_user_tracked_publisher_ids(user):
    publisher_ids = set(
        FollowedRun.objects.filter(
            user=user,
        ).values_list(
            "run__publisher_id",
            flat=True,
        )
    )

    publisher_ids.update(
        IssueProgress.objects.filter(
            user=user,
        ).values_list(
            "issue__run__publisher_id",
            flat=True,
        )
    )

    publisher_ids.update(
        VolumeProgress.objects.filter(
            user=user,
        ).values_list(
            "volume__publisher_id",
            flat=True,
        )
    )

    publisher_ids.update(
        OneShotProgress.objects.filter(
            user=user,
        ).values_list(
            "one_shot__publisher_id",
            flat=True,
        )
    )

    return [publisher_id for publisher_id in publisher_ids if publisher_id]


def get_user_tracked_run_ids(user):
    run_ids = set(
        FollowedRun.objects.filter(
            user=user,
        ).values_list(
            "run_id",
            flat=True,
        )
    )

    run_ids.update(
        IssueProgress.objects.filter(
            user=user,
        ).values_list(
            "issue__run_id",
            flat=True,
        )
    )

    run_ids.update(
        VolumeProgress.objects.filter(
            user=user,
        ).values_list(
            "volume__run_id",
            flat=True,
        )
    )

    return list(run_ids)


def get_user_tracked_issue_ids(user):
    issue_ids = set(
        IssueProgress.objects.filter(
            user=user,
        ).values_list(
            "issue_id",
            flat=True,
        )
    )

    followed_run_ids = FollowedRun.objects.filter(
        user=user,
    ).values_list(
        "run_id",
        flat=True,
    )

    issue_ids.update(
        ComicIssue.objects.filter(
            run_id__in=followed_run_ids,
        ).values_list(
            "id",
            flat=True,
        )
    )

    followed_volume_ids = VolumeProgress.objects.filter(
        user=user,
    ).values_list(
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


def get_user_tracked_one_shot_ids(user):
    return list(
        OneShotProgress.objects.filter(
            user=user,
        ).values_list(
            "one_shot_id",
            flat=True,
        )
    )


def get_my_comics_option_page(queryset, *, offset=0):
    items = list(queryset[offset : offset + MY_COMICS_OPTION_LIMIT + 1])
    return items[:MY_COMICS_OPTION_LIMIT], len(items) > MY_COMICS_OPTION_LIMIT


def get_my_comics_publisher_options(*, tracked_publisher_ids, search_value):
    publishers = ComicPublisher.objects.filter(
        id__in=tracked_publisher_ids,
    ).distinct()

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
        publishers = publishers.order_by(
            "name",
        )

    return publishers


def get_my_comics_run_options(*, tracked_run_ids, selected_publisher_id, search_value):
    runs = ComicRun.objects.filter(
        id__in=tracked_run_ids,
    ).select_related(
        "publisher",
    )

    if selected_publisher_id:
        runs = runs.filter(publisher_id=selected_publisher_id)

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


def get_my_comics_issue_options(
    *,
    tracked_issue_ids,
    selected_publisher_id,
    selected_run_id,
    search_value,
):
    issues = ComicIssue.objects.filter(
        id__in=tracked_issue_ids,
    ).select_related(
        "run",
        "run__publisher",
    )

    if selected_publisher_id:
        issues = issues.filter(run__publisher_id=selected_publisher_id)

    if selected_run_id:
        issues = issues.filter(run_id=selected_run_id)

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


def get_my_comics_one_shot_options(*, tracked_one_shot_ids, selected_publisher_id, search_value):
    one_shots = ComicOneShot.objects.filter(
        id__in=tracked_one_shot_ids,
    ).select_related(
        "publisher",
    )

    if selected_publisher_id:
        one_shots = one_shots.filter(publisher_id=selected_publisher_id)

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


def get_my_comics_status_options(search_value):
    options = [
        {
            "value": value,
            "label": label,
        }
        for value, label in FollowedRun.STATUS_CHOICES
    ]

    if not search_value:
        return options

    search_value = search_value.casefold()

    return [
        option
        for option in options
        if search_value in option["label"].casefold()
    ]


def build_my_comics_url(**params):
    clean_params = {
        key: value
        for key, value in params.items()
        if value not in [None, ""]
    }

    base_url = reverse("reading:my_comics")

    if not clean_params:
        return base_url

    return f"{base_url}?{urlencode(clean_params)}"


def build_my_comics_status_filter_options(filters):
    return [
        {
            "value": value,
            "label": label,
            "url": build_my_comics_url(
                publisher=filters["publisher_id"],
                run=filters["run_id"],
                issue=filters["issue_id"],
                one_shot=filters["one_shot_id"],
                status=value,
            ),
        }
        for value, label in FollowedRun.STATUS_CHOICES
    ]


def build_my_comics_publisher_json_option(
    publisher,
    *,
    selected_option_id,
    selected_status,
):
    return {
        "id": publisher.id,
        "url": build_my_comics_url(
            publisher=publisher.id,
            status=selected_status,
        ),
        "label": publisher.name,
        "meta": "",
        "search_label": publisher.name,
        "active": publisher.id == selected_option_id,
    }


def build_my_comics_run_json_option(
    run,
    *,
    selected_option_id,
    selected_publisher_id,
    selected_status,
):
    year = run.start_year or "Unknown year"

    return {
        "id": run.id,
        "url": build_my_comics_url(
            publisher=selected_publisher_id,
            run=run.id,
            status=selected_status,
        ),
        "label": f"{year} — {run.title}",
        "meta": run.publisher.name,
        "search_label": f"{run.title} {run.start_year} {run.publisher.name}",
        "active": run.id == selected_option_id,
    }


def build_my_comics_issue_json_option(
    issue,
    *,
    selected_option_id,
    selected_publisher_id,
    selected_run_id,
    selected_status,
):
    return {
        "id": issue.id,
        "url": build_my_comics_url(
            publisher=selected_publisher_id,
            run=selected_run_id,
            issue=issue.id,
            status=selected_status,
        ),
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


def build_my_comics_one_shot_json_option(
    one_shot,
    *,
    selected_option_id,
    selected_publisher_id,
    selected_status,
):
    return {
        "id": one_shot.id,
        "url": build_my_comics_url(
            publisher=selected_publisher_id,
            one_shot=one_shot.id,
            status=selected_status,
        ),
        "label": one_shot.title,
        "meta": (
            f"{one_shot.publisher.name}"
            f" · {format_date_or_unknown(one_shot.published_date)}"
        ),
        "search_label": f"{one_shot.title} {one_shot.start_year} {one_shot.publisher.name}",
        "active": one_shot.id == selected_option_id,
    }


def build_my_comics_status_json_option(option, *, filters):
    return {
        "id": option["value"],
        "url": build_my_comics_url(
            publisher=filters["publisher_id"],
            run=filters["run_id"],
            issue=filters["issue_id"],
            one_shot=filters["one_shot_id"],
            status=option["value"],
        ),
        "label": option["label"],
        "meta": "",
        "search_label": option["label"],
        "active": option["value"] == filters["status"],
    }


def build_my_comics_run_row_item(progress):
    run = progress.run

    return {
        "kind": "runs",
        "row_url": reverse("catalog:run_details", args=[run.id]),
        "aria_label": f"Open run details for {run}",
        "run": str(run),
        "publisher": run.publisher.name,
        "status": progress.status,
        "status_label": progress.get_status_display(),
        "issue_count": str(run.issue_count) if run.issue_count else "Unknown",
        "issue_count_muted": not bool(run.issue_count),
        "action_url": reverse("reading:set_run_status", args=[run.id]),
        "current_status": progress.status,
        "catalog_issue_count": progress.catalog_issue_count,
        "tracked_issue_count": progress.tracked_issue_count,
        "status_choices": build_status_choices(FollowedRun.STATUS_CHOICES),
    }


def build_my_comics_volume_row_item(progress):
    volume = progress.volume

    return {
        "kind": "volumes",
        "row_url": reverse("catalog:volume_details", args=[volume.id]),
        "aria_label": f"Open volume details for {volume}",
        "volume": str(volume),
        "run": str(volume.run),
        "run_url": reverse("catalog:run_details", args=[volume.run.id]),
        "release_date": format_date_or_unknown(volume.release_date),
        "release_date_muted": not bool(volume.release_date),
        "status": progress.status,
        "status_label": progress.get_status_display(),
        "action_url": reverse("reading:set_volume_status", args=[volume.id]),
        "current_status": progress.status,
        "status_choices": build_status_choices(VolumeProgress.STATUS_CHOICES),
    }


def build_my_comics_issue_row_item(progress):
    issue = progress.issue

    return {
        "kind": "issues",
        "row_url": reverse("catalog:issue_details", args=[issue.id]),
        "aria_label": f"Open issue details for issue {issue.issue_number}",
        "issue": f"#{issue.issue_number}",
        "run": str(issue.run),
        "run_url": reverse("catalog:run_details", args=[issue.run.id]),
        "published_date": format_date_or_unknown(issue.published_date),
        "published_date_muted": not bool(issue.published_date),
        "status": progress.status,
        "status_label": progress.get_status_display(),
        "action_url": reverse("reading:set_issue_status", args=[issue.id]),
        "current_status": progress.status,
        "status_choices": build_status_choices(IssueProgress.STATUS_CHOICES),
    }


def build_my_comics_one_shot_row_item(progress):
    one_shot = progress.one_shot

    return {
        "kind": "one_shots",
        "row_url": reverse("catalog:one_shot_details", args=[one_shot.id]),
        "aria_label": f"Open one-shot details for {one_shot.title}",
        "title": one_shot.title,
        "publisher": one_shot.publisher.name,
        "published_date": format_date_or_unknown(one_shot.published_date),
        "published_date_muted": not bool(one_shot.published_date),
        "status": progress.status,
        "status_label": progress.get_status_display(),
        "action_url": reverse("reading:set_one_shot_status", args=[one_shot.id]),
        "current_status": progress.status,
        "status_choices": build_status_choices(OneShotProgress.STATUS_CHOICES),
    }


def build_status_choices(status_choices):
    return [
        {
            "value": value,
            "label": label,
        }
        for value, label in status_choices
    ]


def get_requested_status(request, default_status):
    return request.POST.get("status") or default_status


def get_status_post_data(request, default_status):
    data = request.POST.copy()

    if not data.get("status"):
        data["status"] = default_status

    return data


def get_status_label(status_choices, status):
    return dict(status_choices).get(status, status)


def build_run_issue_status_plan(*, request, run, default_status):
    if request.POST.get("apply_to_issues") != "1":
        return []

    issues = list(
        ComicIssue.objects.filter(
            run=run,
        ).order_by(
            "published_date",
            "issue_number",
        )
    )

    if request.POST.get("issue_status_mode") == "individual":
        return build_individual_run_issue_status_plan(
            request=request,
            issues=issues,
            default_status=default_status,
        )

    issue_status = request.POST.get("issue_status") or default_status
    issue_status = validate_issue_status(issue_status)

    return [
        {
            "issue": issue,
            "status": issue_status,
        }
        for issue in issues
    ]


def build_individual_run_issue_status_plan(*, request, issues, default_status):
    issue_status_plan = []

    for issue in issues:
        issue_status = request.POST.get(f"issue_status_{issue.id}") or default_status
        issue_status = validate_issue_status(issue_status)

        issue_status_plan.append(
            {
                "issue": issue,
                "status": issue_status,
            }
        )

    return issue_status_plan


def validate_issue_status(status):
    form = IssueProgressForm({"status": status})

    if not form.is_valid():
        raise ValueError("Choose a valid issue reading status.")

    return form.cleaned_data["status"]


def apply_run_issue_status_plan(*, user, issue_status_plan):
    changed_issue_count = 0

    for issue_status in issue_status_plan:
        IssueProgress.objects.update_or_create(
            user=user,
            issue=issue_status["issue"],
            defaults={
                "status": issue_status["status"],
            },
        )
        changed_issue_count += 1

    return changed_issue_count


def set_all_run_issues_status(*, user, run, status):
    changed_issue_count = 0

    issues = ComicIssue.objects.filter(
        run=run,
    ).order_by(
        "published_date",
        "issue_number",
    )

    for issue in issues:
        IssueProgress.objects.update_or_create(
            user=user,
            issue=issue,
            defaults={
                "status": status,
            },
        )
        changed_issue_count += 1

    return changed_issue_count


def update_existing_run_issue_statuses(*, user, run, status):
    return IssueProgress.objects.filter(
        user=user,
        issue__run=run,
    ).update(
        status=status,
        updated_at=timezone.now(),
    )


def remove_run_issue_statuses(*, user, run):
    deleted_count, _ = IssueProgress.objects.filter(
        user=user,
        issue__run=run,
    ).delete()

    return deleted_count


def build_run_read_offer_if_complete(user, run):
    catalog_issue_count = ComicIssue.objects.filter(run=run).count()

    if catalog_issue_count == 0:
        return None

    read_issue_count = IssueProgress.objects.filter(
        user=user,
        issue__run=run,
        status=IssueProgress.STATUS_READ,
    ).values(
        "issue_id",
    ).distinct().count()

    if read_issue_count != catalog_issue_count:
        return None

    followed_run = FollowedRun.objects.filter(
        user=user,
        run=run,
    ).first()

    if not followed_run or followed_run.status == FollowedRun.STATUS_READ:
        return None

    return {
        "run_id": run.id,
        "run_title": str(run),
        "action_url": reverse("reading:set_run_status", args=[run.id]),
        "message": f"All issues in {run} are marked read. Mark the run as read too?",
    }


def build_run_tracking_payload(user, run):
    followed_run = FollowedRun.objects.filter(
        user=user,
        run=run,
    ).first()

    counts = get_run_issue_counts(user, run)

    return {
        "item_type": "run",
        "action_url": reverse("reading:set_run_status", args=[run.id]),
        "unfollow_url": reverse("reading:unfollow_run", args=[run.id]),
        "tracked": bool(followed_run),
        "status": followed_run.status if followed_run else "",
        "status_label": followed_run.get_status_display() if followed_run else "",
        "status_choices": build_status_choices(FollowedRun.STATUS_CHOICES),
        "catalog_issue_count": counts["catalog_issue_count"],
        "tracked_issue_count": counts["tracked_issue_count"],
        "read_issue_count": counts["read_issue_count"],
    }


def build_issue_tracking_payload(user, issue):
    issue_progress = IssueProgress.objects.filter(
        user=user,
        issue=issue,
    ).first()

    return {
        "item_type": "issue",
        "action_url": reverse("reading:set_issue_status", args=[issue.id]),
        "unfollow_url": reverse("reading:remove_issue_status", args=[issue.id]),
        "tracked": bool(issue_progress),
        "status": issue_progress.status if issue_progress else "",
        "status_label": issue_progress.get_status_display() if issue_progress else "",
        "status_choices": build_status_choices(IssueProgress.STATUS_CHOICES),
    }


def build_volume_tracking_payload(user, volume):
    volume_progress = VolumeProgress.objects.filter(
        user=user,
        volume=volume,
    ).first()

    return {
        "item_type": "volume",
        "action_url": reverse("reading:set_volume_status", args=[volume.id]),
        "unfollow_url": reverse("reading:remove_volume_status", args=[volume.id]),
        "tracked": bool(volume_progress),
        "status": volume_progress.status if volume_progress else "",
        "status_label": volume_progress.get_status_display() if volume_progress else "",
        "status_choices": build_status_choices(VolumeProgress.STATUS_CHOICES),
    }


def build_one_shot_tracking_payload(user, one_shot):
    one_shot_progress = OneShotProgress.objects.filter(
        user=user,
        one_shot=one_shot,
    ).first()

    return {
        "item_type": "one_shot",
        "action_url": reverse("reading:set_one_shot_status", args=[one_shot.id]),
        "unfollow_url": reverse("reading:remove_one_shot_status", args=[one_shot.id]),
        "tracked": bool(one_shot_progress),
        "status": one_shot_progress.status if one_shot_progress else "",
        "status_label": one_shot_progress.get_status_display() if one_shot_progress else "",
        "status_choices": build_status_choices(OneShotProgress.STATUS_CHOICES),
    }


def get_run_issue_counts(user, run):
    catalog_issue_count = ComicIssue.objects.filter(
        run=run,
    ).count()

    tracked_issue_count = IssueProgress.objects.filter(
        user=user,
        issue__run=run,
    ).values(
        "issue_id",
    ).distinct().count()

    read_issue_count = IssueProgress.objects.filter(
        user=user,
        issue__run=run,
        status=IssueProgress.STATUS_READ,
    ).values(
        "issue_id",
    ).distinct().count()

    return {
        "catalog_issue_count": catalog_issue_count,
        "tracked_issue_count": tracked_issue_count,
        "read_issue_count": read_issue_count,
    }


def build_run_follow_issue_option(issue, issue_progress):
    return {
        "id": issue.id,
        "label": f"#{issue.issue_number}",
        "meta": format_date_or_unknown(issue.published_date),
        "status": issue_progress.status if issue_progress else "",
    }


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


def format_date_or_unknown(value):
    if not value:
        return "Unknown"

    return value.strftime("%Y-%m-%d")


def invalid_tracking_status_response(request, *, error_message, redirect_url):
    messages.error(request, error_message)

    return tracking_response(
        request,
        ok=False,
        redirect_url=redirect_url,
        payload={
            "error": error_message,
        },
    )


def is_ajax_request(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def tracking_response(request, *, ok, redirect_url, payload):
    if is_ajax_request(request):
        response_payload = {
            "ok": ok,
            **payload,
        }

        return JsonResponse(response_payload)

    return redirect(get_safe_next_url(request, redirect_url))


def get_safe_next_url(request, fallback_url):
    next_url = request.POST.get("next") or request.GET.get("next")

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    return fallback_url
