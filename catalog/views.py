from urllib.parse import urlencode

from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)
from reading.models import FollowedRun, IssueProgress, VolumeProgress


def home(request):
    context = {
        "publisher_count": ComicPublisher.objects.count(),
        "run_count": ComicRun.objects.count(),
        "issue_count": ComicIssue.objects.count(),
        "volume_count": ComicVolume.objects.count(),
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
    selected_publisher = None
    selected_run = None
    selected_volume = None

    selected_publisher_id = get_int_query_param(request, "publisher")
    selected_run_id = get_int_query_param(request, "run")
    selected_volume_id = get_int_query_param(request, "volume")

    if selected_volume_id:
        selected_volume = get_object_or_404(
            ComicVolume.objects.select_related("publisher", "run"),
            id=selected_volume_id,
        )
        selected_run = selected_volume.run
        selected_publisher = selected_volume.publisher
    elif selected_run_id:
        selected_run = get_object_or_404(
            ComicRun.objects.select_related("publisher"),
            id=selected_run_id,
        )
        selected_publisher = selected_run.publisher
    elif selected_publisher_id:
        selected_publisher = get_object_or_404(
            ComicPublisher,
            id=selected_publisher_id,
        )

    publishers = ComicPublisher.objects.annotate(
        run_total=Count("runs", distinct=True),
        volume_total=Count("volumes", distinct=True),
    ).order_by("name")

    run_options = ComicRun.objects.select_related("publisher").order_by(
        "publisher__name",
        "-start_year",
        "-first_issue_date",
        "title",
    )
    volume_options = ComicVolume.objects.select_related(
        "publisher",
        "run",
    ).order_by(
        "publisher__name",
        "-release_date",
        "run__title",
        "volume_number",
        "title",
    )

    if selected_publisher:
        run_options = run_options.filter(publisher=selected_publisher)
        volume_options = volume_options.filter(publisher=selected_publisher)

    if selected_run:
        volume_options = volume_options.filter(run=selected_run)

    runs = ComicRun.objects.select_related("publisher").order_by(
        "publisher__name",
        "-start_year",
        "-first_issue_date",
        "title",
    )
    volumes = ComicVolume.objects.select_related("publisher", "run").order_by(
        "publisher__name",
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
        "run__publisher__name",
        "-published_date",
        "run__title",
        "issue_number",
    )

    if selected_volume:
        runs = runs.filter(id=selected_volume.run_id)
        volumes = volumes.filter(id=selected_volume.id)
        issues = issues.filter(collected_in__volume=selected_volume).distinct()
    elif selected_run:
        runs = runs.filter(id=selected_run.id)
        volumes = volumes.filter(run=selected_run)
        issues = issues.filter(run=selected_run)
    elif selected_publisher:
        runs = runs.filter(publisher=selected_publisher)
        volumes = volumes.filter(publisher=selected_publisher)
        issues = issues.filter(run__publisher=selected_publisher)

    issue_list = list(issues)
    attach_issue_credit_display(issue_list)

    selected_items = build_selected_items(
        selected_publisher=selected_publisher,
        selected_run=selected_run,
        selected_volume=selected_volume,
    )

    context = {
        "publishers": publishers,
        "run_options": run_options,
        "volume_options": volume_options,
        "runs": runs,
        "volumes": volumes,
        "issues": issue_list,
        "selected_publisher": selected_publisher,
        "selected_run": selected_run,
        "selected_volume": selected_volume,
        "selected_publisher_id": selected_publisher.id if selected_publisher else None,
        "selected_run_id": selected_run.id if selected_run else None,
        "selected_volume_id": selected_volume.id if selected_volume else None,
        "selected_items": selected_items,
    }

    return render(request, "catalog/browse.html", context)


def run_details(request, pk):
    run = get_object_or_404(
        ComicRun.objects.select_related("publisher").prefetch_related(
            "credits__person",
            "credits__role",
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

    volumes = run.volumes.select_related("publisher", "run").order_by(
        "volume_number",
        "release_date",
        "title",
    )
    default_credits = run.credits.select_related("person", "role").filter(
        role__show_by_default=True,
    )
    all_credits = run.credits.select_related("person", "role")

    is_following_run = False

    if request.user.is_authenticated:
        is_following_run = FollowedRun.objects.filter(
            user=request.user,
            run=run,
        ).exists()

    context = {
        "run": run,
        "issues": issues,
        "volumes": volumes,
        "default_credits": default_credits,
        "all_credits": all_credits,
        "is_following_run": is_following_run,
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

    current_issue_progress = None
    is_following_run = False

    if request.user.is_authenticated:
        current_issue_progress = IssueProgress.objects.filter(
            user=request.user,
            issue=issue,
        ).first()
        is_following_run = FollowedRun.objects.filter(
            user=request.user,
            run=issue.run,
        ).exists()

    context = {
        "issue": issue,
        "collected_in": collected_in,
        "default_credits": default_credits,
        "all_credits": all_credits,
        "current_issue_progress": current_issue_progress,
        "issue_status_choices": IssueProgress.STATUS_CHOICES,
        "is_following_run": is_following_run,
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

    default_credits = volume.credits.select_related("person", "role").filter(
        role__show_by_default=True,
    )
    all_credits = volume.credits.select_related("person", "role")

    current_volume_progress = None

    if request.user.is_authenticated:
        current_volume_progress = VolumeProgress.objects.filter(
            user=request.user,
            volume=volume,
        ).first()

    context = {
        "volume": volume,
        "volume_issues": volume_issues,
        "issues": issues,
        "default_credits": default_credits,
        "all_credits": all_credits,
        "current_volume_progress": current_volume_progress,
        "volume_status_choices": VolumeProgress.STATUS_CHOICES,
    }

    return render(request, "catalog/volume_details.html", context)


def issue_credit_prefetch():
    return Prefetch(
        "credits",
        queryset=ComicIssueCredit.objects.select_related("person", "role").order_by(
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


def get_int_query_param(request, name):
    raw_value = request.GET.get(name)

    if raw_value in [None, ""]:
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def build_selected_items(*, selected_publisher, selected_run, selected_volume):
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

    if selected_volume:
        selected_items.append(
            {
                "label": "Volume",
                "value": str(selected_volume),
            }
        )

    return selected_items