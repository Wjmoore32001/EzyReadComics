from django.db.models import Count, F, Max

from .models import ComicIssue, ComicVolume


def get_publishers():
    return (
        ComicVolume.objects.exclude(publisher__isnull=True)
        .exclude(publisher="")
        .order_by("publisher")
        .values_list("publisher", flat=True)
        .distinct()
    )


def get_run_queryset():
    return ComicVolume.objects.annotate(
        stored_issue_count=Count("issues"),
        latest_store_date=Max("issues__store_date"),
    )


def get_all_runs():
    return get_run_queryset().order_by(
        F("start_year").desc(nulls_last=True),
        "publisher",
        "name",
        "id",
    )


def get_runs_for_publisher(publisher):
    if not publisher:
        return ComicVolume.objects.none()

    return (
        get_run_queryset()
        .filter(publisher=publisher)
        .order_by(
            F("start_year").desc(nulls_last=True),
            "name",
            "id",
        )
    )


def get_run_by_id(run_id):
    if not run_id:
        return None

    return get_run_queryset().filter(id=run_id).first()


def get_issues_for_run(run):
    if not run:
        return ComicIssue.objects.none()

    return (
        ComicIssue.objects.select_related("volume")
        .filter(volume=run)
        .order_by(
            F("store_date").asc(nulls_last=True),
            F("cover_date").asc(nulls_last=True),
            "issue_number",
            "id",
        )
    )


def get_issue_for_run(run, issue_id):
    if not run or not issue_id:
        return None

    return get_issues_for_run(run).filter(id=issue_id).first()