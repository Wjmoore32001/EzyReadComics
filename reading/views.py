from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalog.models import ComicIssue, ComicRun, ComicVolume, ComicVolumeIssue
from reading.forms import IssueProgressForm, RunProgressForm, VolumeProgressForm
from reading.models import FollowedRun, IssueProgress, VolumeProgress


def signup_required(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)

        next_url = get_safe_next_url(request, reverse("catalog:browse"))
        signup_url = f"{reverse('signup')}?{urlencode({'next': next_url})}"

        return redirect(signup_url)

    return wrapped_view


@login_required
def my_comics(request):
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

    context = {
        "followed_runs": followed_runs,
        "volume_progress": volume_progress,
        "issue_progress": issue_progress,
        "run_status_choices": FollowedRun.STATUS_CHOICES,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
    }

    return render(request, "reading/my_comics.html", context)


@require_POST
@signup_required
def follow_run(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)

    followed_run, created = FollowedRun.objects.get_or_create(
        user=request.user,
        run=run,
        defaults={
            "status": FollowedRun.STATUS_PLANNED,
        },
    )

    if created:
        messages.success(request, f"{run} was added to My Comics.")
    else:
        messages.info(request, f"{run} is already in My Comics.")

    return redirect(get_safe_next_url(request, reverse("catalog:run_details", args=[run.id])))


@require_POST
@signup_required
def set_run_status(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)

    form = RunProgressForm(get_status_post_data(request, FollowedRun.STATUS_PLANNED))

    if not form.is_valid():
        messages.error(request, "Choose a valid reading status.")
        return redirect(get_safe_next_url(request, reverse("catalog:run_details", args=[run.id])))

    new_status = form.cleaned_data["status"]
    apply_to_issues = request.POST.get("apply_to_issues") == "1"

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

        if new_status == FollowedRun.STATUS_READ and apply_to_issues:
            changed_issue_count = set_all_run_issues_status(
                user=request.user,
                run=run,
                status=IssueProgress.STATUS_READ,
            )
        elif (
            not created
            and previous_status == FollowedRun.STATUS_READ
            and new_status != FollowedRun.STATUS_READ
            and apply_to_issues
        ):
            changed_issue_count = update_existing_run_issue_statuses(
                user=request.user,
                run=run,
                status=new_status,
            )
        elif apply_to_issues:
            changed_issue_count = set_all_run_issues_status(
                user=request.user,
                run=run,
                status=new_status,
            )

    status_label = get_status_label(FollowedRun.STATUS_CHOICES, new_status)

    if changed_issue_count:
        issue_label = "issue status" if changed_issue_count == 1 else "issue statuses"
        messages.success(
            request,
            f"{run} was saved as {status_label}, and {changed_issue_count} {issue_label} were updated.",
        )
    else:
        messages.success(request, f"Your status for {run} was saved as {status_label}.")

    return redirect(get_safe_next_url(request, reverse("catalog:run_details", args=[run.id])))


@login_required
@require_POST
def unfollow_run(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)
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
        messages.success(
            request,
            f"{run} was unfollowed, and {removed_issue_count} {issue_label} were removed.",
        )
    elif deleted_count:
        messages.success(request, f"{run} was removed from your followed runs.")
    else:
        messages.info(request, f"{run} was not in your followed runs.")

    return redirect(get_safe_next_url(request, reverse("reading:my_comics")))


@require_POST
@signup_required
def set_issue_status(request, issue_id):
    issue = get_object_or_404(
        ComicIssue.objects.select_related("run"),
        id=issue_id,
    )

    form = IssueProgressForm(get_status_post_data(request, IssueProgress.STATUS_PLANNED))

    if not form.is_valid():
        messages.error(request, "Choose a valid reading status.")
        return redirect(get_safe_next_url(request, reverse("catalog:issue_details", args=[issue.id])))

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
            "status": form.cleaned_data["status"],
        },
    )

    messages.success(request, f"Your status for {issue} was saved.")

    return redirect(get_safe_next_url(request, reverse("catalog:issue_details", args=[issue.id])))


@login_required
@require_POST
def remove_issue_status(request, issue_id):
    issue = get_object_or_404(ComicIssue, id=issue_id)

    deleted_count, _ = IssueProgress.objects.filter(
        user=request.user,
        issue=issue,
    ).delete()

    if deleted_count:
        messages.success(request, f"Your status for {issue} was removed.")
    else:
        messages.info(request, f"{issue} did not have a saved status.")

    return redirect(get_safe_next_url(request, reverse("reading:my_comics")))


@require_POST
@signup_required
def set_volume_status(request, volume_id):
    volume = get_object_or_404(
        ComicVolume.objects.select_related("run"),
        id=volume_id,
    )

    form = VolumeProgressForm(get_status_post_data(request, VolumeProgress.STATUS_PLANNED))

    if not form.is_valid():
        messages.error(request, "Choose a valid reading status.")
        return redirect(get_safe_next_url(request, reverse("catalog:volume_details", args=[volume.id])))

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
        messages.success(
            request,
            f"Your status for {volume} was saved, and {marked_issue_count} {issue_label} were marked as read.",
        )
    else:
        messages.success(request, f"Your status for {volume} was saved.")

    return redirect(get_safe_next_url(request, reverse("catalog:volume_details", args=[volume.id])))


@login_required
@require_POST
def remove_volume_status(request, volume_id):
    volume = get_object_or_404(ComicVolume, id=volume_id)

    deleted_count, _ = VolumeProgress.objects.filter(
        user=request.user,
        volume=volume,
    ).delete()

    if deleted_count:
        messages.success(request, f"Your status for {volume} was removed.")
    else:
        messages.info(request, f"{volume} did not have a saved status.")

    return redirect(get_safe_next_url(request, reverse("reading:my_comics")))


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


def get_status_post_data(request, default_status):
    data = request.POST.copy()

    if not data.get("status"):
        data["status"] = default_status

    return data


def get_status_label(status_choices, status):
    return dict(status_choices).get(status, status)


def get_safe_next_url(request, fallback_url):
    next_url = request.POST.get("next") or request.GET.get("next")

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    return fallback_url