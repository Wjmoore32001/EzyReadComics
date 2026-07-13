import re

from catalog.marvel.text import (
    clean_text,
    issue_number_sort_key,
    normalize_title,
)
from catalog.marvel.writer import find_existing_run, get_or_create_marvel_publisher
from catalog.models import (
    ComicOneShot,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
    ComicVolumeOneShot,
    ComicVolumeRun,
)


def catalog_run_title(title):
    title = clean_text(title)

    if normalize_title(title) == "amazing spider man":
        return "THE AMAZING SPIDER-MAN"

    return title


def get_or_create_collection_run(*, publisher, run_title, start_year, dry_run, totals):
    run_title = catalog_run_title(run_title)
    start_year = clean_text(start_year)

    existing = find_existing_run(
        title=run_title,
        start_year=start_year,
    )

    if existing:
        return existing

    totals["runs_created"] += 1

    if dry_run:
        return PreviewObject(
            title=run_title,
            start_year=start_year,
        )

    return ComicRun.objects.create(
        publisher=publisher,
        title=run_title,
        start_year=start_year,
        status=ComicRun.STATUS_UNKNOWN,
    )


def get_or_create_volume(
    *,
    publisher,
    primary_run,
    collection,
    detail,
    run_link,
    one_shots,
    dry_run,
    totals,
):
    official_source_key = clean_text(collection.get("marvel_collection_id"))
    official_source_url = clean_text(collection.get("detail_url"))

    existing = find_existing_volume(
        publisher=publisher,
        title=collection["title"],
        release_date=collection.get("published_date"),
        official_source_key=official_source_key,
    )

    first_issue = first_issue_number(run_link["issue_numbers"])
    last_issue = last_issue_number(run_link["issue_numbers"])
    issue_count = collected_item_count(detail=detail, one_shots=one_shots)
    description = clean_text(detail.get("description"))

    if existing:
        changed = volume_needs_update(
            volume=existing,
            primary_run=primary_run,
            release_date=collection.get("published_date"),
            first_issue=first_issue,
            last_issue=last_issue,
            issue_count=issue_count,
            description=description,
            official_source_key=official_source_key,
            official_source_url=official_source_url,
        )

        if changed:
            totals["volumes_updated"] += 1

            if not dry_run:
                if not is_preview(primary_run):
                    existing.run = primary_run

                existing.release_date = collection.get("published_date")
                existing.first_issue_number = first_issue
                existing.last_issue_number = last_issue
                existing.issue_count = issue_count

                if official_source_key:
                    existing.official_source_key = official_source_key

                if official_source_url:
                    existing.official_source_url = official_source_url

                if description and not existing.description:
                    existing.description = description

                existing.save()

        return existing

    totals["volumes_created"] += 1

    if dry_run:
        return PreviewObject(
            title=collection["title"],
            official_source_key=official_source_key,
            official_source_url=official_source_url,
        )

    return ComicVolume.objects.create(
        publisher=publisher,
        run=primary_run,
        title=collection["title"],
        volume_number=extract_volume_number(collection["title"]),
        official_source_key=official_source_key,
        official_source_url=official_source_url,
        first_issue_number=first_issue,
        last_issue_number=last_issue,
        release_date=collection.get("published_date"),
        issue_count=issue_count,
        description=description,
    )


def find_existing_volume(*, publisher, title, release_date, official_source_key=""):
    if is_preview(publisher):
        return None

    official_source_key = clean_text(official_source_key)

    if official_source_key:
        existing = (
            ComicVolume.objects.filter(
                publisher=publisher,
                official_source_key=official_source_key,
            )
            .order_by("id")
            .first()
        )

        if existing:
            return existing

    queryset = ComicVolume.objects.filter(
        publisher=publisher,
        title__iexact=title,
    )

    if release_date:
        match = queryset.filter(release_date=release_date).order_by("id").first()

        if match:
            return match

    return queryset.order_by("id").first()


def volume_needs_update(
    *,
    volume,
    primary_run,
    release_date,
    first_issue,
    last_issue,
    issue_count,
    description,
    official_source_key,
    official_source_url,
):
    if not is_preview(primary_run) and volume.run_id != primary_run.id:
        return True

    if release_date and volume.release_date != release_date:
        return True

    if volume.first_issue_number != first_issue:
        return True

    if volume.last_issue_number != last_issue:
        return True

    if issue_count is not None and volume.issue_count != issue_count:
        return True

    if official_source_key and volume.official_source_key != official_source_key:
        return True

    if official_source_url and volume.official_source_url != official_source_url:
        return True

    if description and not volume.description:
        return True

    return False


def collected_item_count(*, detail, one_shots):
    issue_total = 0

    for run_link in detail.get("run_links", []) or []:
        issue_total += len(run_link.get("issue_numbers") or [])

    return issue_total + len(one_shots)


def create_or_update_volume_run(*, volume, run, run_link, item_order, dry_run, totals):
    if is_preview(volume) or is_preview(run):
        totals["volume_runs_created"] += 1
        return

    issue_numbers_text = compact_issue_numbers(run_link["issue_numbers"])
    first_issue = first_issue_number(run_link["issue_numbers"])
    last_issue = last_issue_number(run_link["issue_numbers"])

    existing = ComicVolumeRun.objects.filter(volume=volume, run=run).first()

    if existing:
        changed = (
            existing.issue_numbers_text != issue_numbers_text
            or existing.first_issue_number != first_issue
            or existing.last_issue_number != last_issue
            or existing.item_order != item_order
        )

        if changed:
            totals["volume_runs_updated"] += 1

            if not dry_run:
                existing.issue_numbers_text = issue_numbers_text
                existing.first_issue_number = first_issue
                existing.last_issue_number = last_issue
                existing.item_order = item_order
                existing.save()

        return

    totals["volume_runs_created"] += 1

    if dry_run:
        return

    ComicVolumeRun.objects.create(
        volume=volume,
        run=run,
        first_issue_number=first_issue,
        last_issue_number=last_issue,
        issue_numbers_text=issue_numbers_text,
        item_order=item_order,
    )


def create_volume_issue(*, volume, issue, issue_order, dry_run, totals):
    if issue is None:
        return

    if is_preview(volume) or is_preview(issue):
        totals["volume_issues_created"] += 1
        return

    existing = ComicVolumeIssue.objects.filter(volume=volume, issue=issue).first()

    if existing:
        if not dry_run and existing.issue_order != issue_order:
            existing.issue_order = issue_order
            existing.save(update_fields=["issue_order"])
        return

    totals["volume_issues_created"] += 1

    if dry_run:
        return

    ComicVolumeIssue.objects.create(
        volume=volume,
        issue=issue,
        issue_order=issue_order,
    )


def get_or_create_one_shot(*, publisher, one_shot_data, dry_run, totals):
    if is_preview(publisher):
        totals["one_shots_created"] += 1
        return PreviewObject(title=one_shot_data["title"])

    existing = (
        ComicOneShot.objects.filter(
            publisher=publisher,
            title__iexact=one_shot_data["title"],
            start_year=one_shot_data["start_year"],
        )
        .order_by("id")
        .first()
    )

    if existing:
        changed = False

        official_source_key = clean_text(one_shot_data.get("marvel_issue_id"))
        official_source_url = clean_text(one_shot_data.get("marvel_issue_url"))

        if official_source_key and existing.official_source_key != official_source_key:
            existing.official_source_key = official_source_key
            changed = True

        if official_source_url and existing.official_source_url != official_source_url:
            existing.official_source_url = official_source_url
            changed = True

        if changed and not dry_run:
            existing.save()

        return existing

    totals["one_shots_created"] += 1

    if dry_run:
        return PreviewObject(title=one_shot_data["title"])

    return ComicOneShot.objects.create(
        publisher=publisher,
        title=one_shot_data["title"],
        start_year=one_shot_data["start_year"],
        official_source_key=clean_text(one_shot_data.get("marvel_issue_id")),
        official_source_url=clean_text(one_shot_data.get("marvel_issue_url")),
    )


def create_volume_one_shot(*, volume, one_shot, item_order, dry_run, totals):
    if is_preview(volume) or is_preview(one_shot):
        totals["volume_one_shots_created"] += 1
        return

    existing = ComicVolumeOneShot.objects.filter(
        volume=volume,
        one_shot=one_shot,
    ).first()

    if existing:
        if not dry_run and existing.item_order != item_order:
            existing.item_order = item_order
            existing.save(update_fields=["item_order"])
        return

    totals["volume_one_shots_created"] += 1

    if dry_run:
        return

    ComicVolumeOneShot.objects.create(
        volume=volume,
        one_shot=one_shot,
        item_order=item_order,
    )


def compact_issue_numbers(issue_numbers):
    values = sorted(issue_numbers, key=issue_number_sort_key)
    numeric = []

    for value in values:
        if not str(value).isdigit():
            return ",".join(clean_text(item) for item in values)

        numeric.append(int(value))

    if not numeric:
        return ""

    parts = []
    start = numeric[0]
    previous = numeric[0]

    for value in numeric[1:]:
        if value == previous + 1:
            previous = value
            continue

        parts.append(format_range(start, previous))
        start = value
        previous = value

    parts.append(format_range(start, previous))
    return ",".join(parts)


def format_range(start, end):
    if start == end:
        return str(start)

    return f"{start}-{end}"


def first_issue_number(issue_numbers):
    if not issue_numbers:
        return ""

    return clean_text(sorted(issue_numbers, key=issue_number_sort_key)[0])


def last_issue_number(issue_numbers):
    if not issue_numbers:
        return ""

    return clean_text(sorted(issue_numbers, key=issue_number_sort_key)[-1])


def extract_volume_number(title):
    title = clean_text(title)
    marker = "VOL."

    if marker not in title.upper():
        return ""

    after_marker = title.upper().split(marker, 1)[1].strip()
    value = after_marker.split(" ", 1)[0].strip(" :,-")

    return value if value.isdigit() else ""


class PreviewObject:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.id = None
        self.pk = None


def is_preview(value):
    return isinstance(value, PreviewObject)