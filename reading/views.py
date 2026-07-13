from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from catalog.models import ComicIssue, ComicPublisher, ComicRun, ComicVolume, ComicVolumeIssue
from reading.forms import IssueProgressForm, RunProgressForm, VolumeProgressForm
from reading.models import FollowedRun, IssueProgress, VolumeProgress


UNFOLLOW_STATUS_VALUE = "__unfollow__"


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

    followed_runs = FollowedRun.objects.filter(
        user=request.user,
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
            filter=Q(run__issues__user_progress__user=request.user),
            distinct=True,
        ),
    )

    volume_progress = VolumeProgress.objects.filter(
        user=request.user,
    ).select_related(
        "volume",
        "volume__run",
        "volume__publisher",
    )

    issue_progress = IssueProgress.objects.filter(
        user=request.user,
    ).select_related(
        "issue",
        "issue__run",
        "issue__run__publisher",
    )

    followed_runs, volume_progress, issue_progress = apply_my_comics_filters(
        followed_runs=followed_runs,
        volume_progress=volume_progress,
        issue_progress=issue_progress,
        filters=filters,
    )

    tracked_run_ids = get_user_tracked_run_ids(request.user)
    tracked_issue_ids = get_user_tracked_issue_ids(request.user)

    selected_publisher = (
        ComicPublisher.objects.filter(id=filters["publisher_id"]).first()
        if filters["publisher_id"]
        else None
    )
    selected_run = (
        ComicRun.objects.select_related("publisher").filter(id=filters["run_id"]).first()
        if filters["run_id"]
        else None
    )
    selected_issue = (
        ComicIssue.objects.select_related("run", "run__publisher")
        .filter(id=filters["issue_id"])
        .first()
        if filters["issue_id"]
        else None
    )

    publisher_options = get_my_comics_publisher_options(tracked_run_ids)
    run_options = get_my_comics_run_options(
        tracked_run_ids=tracked_run_ids,
        selected_publisher_id=filters["publisher_id"],
    )
    issue_options = get_my_comics_issue_options(
        tracked_issue_ids=tracked_issue_ids,
        selected_publisher_id=filters["publisher_id"],
        selected_run_id=filters["run_id"],
    )

    context = {
        "followed_runs": followed_runs,
        "volume_progress": volume_progress,
        "issue_progress": issue_progress,
        "run_status_choices": FollowedRun.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
        "status_filter_choices": FollowedRun.STATUS_CHOICES,
        "publisher_options": publisher_options,
        "run_options": run_options,
        "issue_options": issue_options,
        "selected_publisher": selected_publisher,
        "selected_run": selected_run,
        "selected_issue": selected_issue,
        "selected_publisher_id": filters["publisher_id"],
        "selected_run_id": filters["run_id"],
        "selected_issue_id": filters["issue_id"],
        "selected_status": filters["status"],
        "filters_active": my_comics_filters_active(filters),
        "unfollow_status_value": UNFOLLOW_STATUS_VALUE,
    }

    return render(request, "reading/my_comics.html", context)


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
        redirect_url=reverse("catalog:run_details", args=[run.id]),
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


def get_my_comics_filters(request):
    status = request.GET.get("status") or ""
    valid_statuses = {value for value, _label in FollowedRun.STATUS_CHOICES}

    if status not in valid_statuses:
        status = ""

    return {
        "publisher_id": get_int_query_param(request, "publisher"),
        "run_id": get_int_query_param(request, "run"),
        "issue_id": get_int_query_param(request, "issue"),
        "status": status,
    }


def apply_my_comics_filters(*, followed_runs, volume_progress, issue_progress, filters):
    publisher_id = filters["publisher_id"]
    run_id = filters["run_id"]
    issue_id = filters["issue_id"]
    status = filters["status"]

    if publisher_id:
        followed_runs = followed_runs.filter(run__publisher_id=publisher_id)
        volume_progress = volume_progress.filter(volume__publisher_id=publisher_id)
        issue_progress = issue_progress.filter(issue__run__publisher_id=publisher_id)

    if run_id:
        followed_runs = followed_runs.filter(run_id=run_id)
        volume_progress = volume_progress.filter(volume__run_id=run_id)
        issue_progress = issue_progress.filter(issue__run_id=run_id)

    if issue_id:
        followed_runs = followed_runs.filter(run__issues__id=issue_id).distinct()
        volume_progress = volume_progress.filter(
            volume__volume_issues__issue_id=issue_id,
        ).distinct()
        issue_progress = issue_progress.filter(issue_id=issue_id)

    if status:
        followed_runs = followed_runs.filter(status=status)
        volume_progress = volume_progress.filter(status=status)
        issue_progress = issue_progress.filter(status=status)

    return followed_runs, volume_progress, issue_progress


def my_comics_filters_active(filters):
    return bool(
        filters["publisher_id"]
        or filters["run_id"]
        or filters["issue_id"]
        or filters["status"]
    )


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


def get_my_comics_publisher_options(tracked_run_ids):
    return ComicPublisher.objects.filter(
        runs__id__in=tracked_run_ids,
    ).distinct().order_by(
        "name",
    )


def get_my_comics_run_options(*, tracked_run_ids, selected_publisher_id):
    runs = ComicRun.objects.filter(
        id__in=tracked_run_ids,
    ).select_related(
        "publisher",
    )

    if selected_publisher_id:
        runs = runs.filter(publisher_id=selected_publisher_id)

    return runs.order_by(
        "-start_year",
        "-first_issue_date",
        "publisher__name",
        "title",
    )


def get_my_comics_issue_options(*, tracked_issue_ids, selected_publisher_id, selected_run_id):
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

    return issues.order_by(
        "-run__start_year",
        "-published_date",
        "run__title",
        "issue_number",
    )


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


def get_int_query_param(request, name):
    raw_value = request.GET.get(name)

    if raw_value in [None, ""]:
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


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