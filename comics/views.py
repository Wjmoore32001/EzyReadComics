from django.db.models import Count, F, Max
from django.shortcuts import render

from .models import ComicIssue, ComicVolume


def home(request):
    return render(request, "comics/home.html")


def get_publishers():
    return (
        ComicVolume.objects.exclude(publisher="")
        .order_by("publisher")
        .values_list("publisher", flat=True)
        .distinct()
    )


def issue_list(request):
    selected_publisher = request.GET.get("publisher", "")

    issues = ComicIssue.objects.select_related("volume")

    if selected_publisher:
        issues = issues.filter(volume__publisher=selected_publisher)

    issues = issues.order_by(
        F("store_date").desc(nulls_last=True),
        F("cover_date").desc(nulls_last=True),
        "volume__name",
        "issue_number",
    )

    context = {
        "issues": issues,
        "publishers": get_publishers(),
        "selected_publisher": selected_publisher,
    }

    return render(request, "comics/issues.html", context)


def volume_list(request):
    selected_publisher = request.GET.get("publisher", "")

    volumes = ComicVolume.objects.annotate(
        latest_store_date=Max("issues__store_date"),
        issue_count=Count("issues"),
    )

    if selected_publisher:
        volumes = volumes.filter(publisher=selected_publisher)

    volumes = volumes.order_by(
        F("latest_store_date").desc(nulls_last=True),
        "name",
    )

    context = {
        "volumes": volumes,
        "publishers": get_publishers(),
        "selected_publisher": selected_publisher,
    }

    return render(request, "comics/volumes.html", context)