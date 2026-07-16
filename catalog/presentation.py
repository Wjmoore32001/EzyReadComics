from django.db.models import Count, Prefetch
from django.urls import reverse

from catalog.listing import format_date_or_unknown
from catalog.models import ComicIssue, ComicIssueCredit, ComicOneShotCredit
from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


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


def attach_run_tracking(request, runs):
    run_ids = [run.id for run in runs]

    if not run_ids:
        return

    catalog_issue_counts = {
        row["run_id"]: row["issue_total"]
        for row in ComicIssue.objects.filter(run_id__in=run_ids)
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


def build_status_choices(status_choices):
    return [
        {
            "value": value,
            "label": label,
        }
        for value, label in status_choices
    ]


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
