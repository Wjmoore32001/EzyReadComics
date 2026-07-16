from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicOneShot,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)
from catalog.presentation import (
    attach_issue_credit_display,
    attach_issue_tracking,
    attach_one_shot_tracking,
    attach_run_tracking,
    attach_volume_tracking,
    issue_credit_prefetch,
)
from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


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


def run_details(request, pk):
    run = get_object_or_404(
        ComicRun.objects.select_related("publisher").prefetch_related("volumes"),
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

    default_credits, all_credits = get_unique_volume_credits(
        volume=volume,
        volume_issues=volume_issues,
        volume_run_links=volume_run_links,
    )

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


def get_unique_volume_credits(*, volume, volume_issues, volume_run_links):
    credits = list(volume.credits.all())
    explicit_issue_run_ids = set()

    for volume_issue in volume_issues:
        issue = volume_issue.issue
        explicit_issue_run_ids.add(issue.run_id)
        credits.extend(issue.credits.all())

    linked_run_ids = {
        volume_run_link.run_id
        for volume_run_link in volume_run_links
    }

    if volume.run_id:
        linked_run_ids.add(volume.run_id)

    fallback_run_ids = linked_run_ids - explicit_issue_run_ids

    if fallback_run_ids:
        credits.extend(
            ComicIssueCredit.objects.select_related(
                "person",
                "role",
            ).filter(
                issue__run_id__in=fallback_run_ids,
            )
        )

    credits.sort(key=credit_display_sort_key)

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


def credit_display_sort_key(credit):
    credit_order = credit.credit_order

    if credit_order is None:
        credit_order = 2**31

    return (
        credit.role.display_order,
        credit_order,
        credit.person.name.casefold(),
        credit.role.name.casefold(),
        credit.role_id,
        credit.person_id,
    )
