from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalog.models import ComicIssue, ComicRun, ComicVolume, ComicVolumeIssue
from reading.forms import IssueProgressForm, VolumeProgressForm
from reading.models import FollowedRun, IssueProgress, VolumeProgress


@login_required
def my_comics(request):
    followed_runs = FollowedRun.objects.filter(
        user=request.user,
    ).select_related(
        "run",
        "run__publisher",
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
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
    }

    return render(request, "reading/my_comics.html", context)


@login_required
@require_POST
def follow_run(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)

    followed_run, created = FollowedRun.objects.get_or_create(
        user=request.user,
        run=run,
    )

    if created:
        messages.success(request, f"{run} was added to My Comics.")
    else:
        messages.info(request, f"{run} is already in My Comics.")

    return redirect(get_safe_next_url(request, reverse("catalog:run_details", args=[run.id])))


@login_required
@require_POST
def unfollow_run(request, run_id):
    run = get_object_or_404(ComicRun, id=run_id)

    deleted_count, _ = FollowedRun.objects.filter(
        user=request.user,
        run=run,
    ).delete()

    if deleted_count:
        messages.success(request, f"{run} was removed from your followed runs.")
    else:
        messages.info(request, f"{run} was not in your followed runs.")

    return redirect(get_safe_next_url(request, reverse("reading:my_comics")))


@login_required
@require_POST
def set_issue_status(request, issue_id):
    issue = get_object_or_404(
        ComicIssue.objects.select_related("run"),
        id=issue_id,
    )

    form = IssueProgressForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Choose a valid reading status.")
        return redirect(get_safe_next_url(request, reverse("catalog:issue_details", args=[issue.id])))

    FollowedRun.objects.get_or_create(
        user=request.user,
        run=issue.run,
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


@login_required
@require_POST
def set_volume_status(request, volume_id):
    volume = get_object_or_404(
        ComicVolume.objects.select_related("run"),
        id=volume_id,
    )

    form = VolumeProgressForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Choose a valid reading status.")
        return redirect(get_safe_next_url(request, reverse("catalog:volume_details", args=[volume.id])))

    status = form.cleaned_data["status"]

    FollowedRun.objects.get_or_create(
        user=request.user,
        run=volume.run,
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
        messages.success(
            request,
            f"Your status for {volume} was saved, and {marked_issue_count} issue status was marked as read.",
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


def get_safe_next_url(request, fallback_url):
    next_url = request.POST.get("next") or request.GET.get("next")

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    return fallback_url