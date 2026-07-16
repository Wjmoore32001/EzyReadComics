from django.urls import reverse

from catalog.listing import format_date_or_unknown
from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


def build_status_choices(status_choices):
    return [
        {
            "value": value,
            "label": label,
        }
        for value, label in status_choices
    ]


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


def build_run_follow_issue_option(issue, issue_progress):
    return {
        "id": issue.id,
        "label": f"#{issue.issue_number}",
        "meta": format_date_or_unknown(issue.published_date),
        "status": issue_progress.status if issue_progress else "",
    }
