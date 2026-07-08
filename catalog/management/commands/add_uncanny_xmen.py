from datetime import date
from html import unescape

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from requests.exceptions import RequestException

from catalog.models import (
    ComicIssue,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)
from comicvine.api.client import (
    ComicVineAPIError,
    create_comicvine_session,
    fetch_issues_page,
    fetch_volume_detail,
    fetch_volumes_page,
    get_comicvine_api_key,
)
from comicvine.api.fields import ISSUE_LIST_FIELDS, VOLUME_LIST_FIELDS
from comicvine.api.parsing import clean_text, parse_comicvine_date
from comicvine.models import ComicVineVolume


USER_AGENT = "EzyReadComics manual_add_uncanny_xmen_2024"

PUBLISHER_NAME = "Marvel"
PUBLISHER_SLUG = "marvel"

RUN_TITLE = "Uncanny X-Men"
RUN_START_YEAR = "2024"

DEFAULT_RUN_DESCRIPTION = (
    "The current ongoing Uncanny X-Men run from Marvel, beginning in 2024 as part of "
    "the From the Ashes era. Written by Gail Simone with art by David Marquez, this run "
    "follows Rogue, Gambit, Wolverine, Nightcrawler, Jubilee, and a new generation of mutants."
)

COLLECTED_VOLUME_NUMBER = "1"
COLLECTED_VOLUME_FALLBACK_TITLE = RUN_TITLE
COLLECTED_VOLUME_FIRST_ISSUE_NUMBER = "1"
COLLECTED_VOLUME_LAST_ISSUE_NUMBER = "6"
COLLECTED_VOLUME_ISSUE_NUMBERS = ["1", "2", "3", "4", "5", "6"]

COLLECTED_VOLUME_SEARCH_START_YEARS = ["2025", "2026"]


class Command(BaseCommand):
    help = (
        "Temporary catalog seeder for the current Uncanny X-Men run. "
        "Fetches issue data from Comic Vine and writes catalog run/issues/volume links."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            default=None,
            help=(
                "Optional plain Comic Vine volume ID for the current Uncanny X-Men run. "
                "If omitted, the command tries local ComicVineVolume rows first, then the API."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and summarize what would happen without writing to the database.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing catalog fields instead of only filling blanks.",
        )
        parser.add_argument(
            "--include-future",
            action="store_true",
            help=(
                "Include issues with future store dates. By default, only issues released "
                "through today are added."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]
        include_future = options["include_future"]
        requested_volume_id = options["comicvine_volume_id"]

        api_key = get_comicvine_api_key()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Manual Uncanny X-Men (2024) catalog seed"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")
        self.stdout.write(f"Overwrite existing fields: {'yes' if overwrite else 'no'}")
        self.stdout.write(f"Include future issues: {'yes' if include_future else 'no'}")

        try:
            with create_comicvine_session(USER_AGENT) as session:
                run_volume_id = resolve_current_run_volume_id(
                    session=session,
                    api_key=api_key,
                    requested_volume_id=requested_volume_id,
                )

                self.stdout.write(f"Comic Vine run volume ID: {run_volume_id}")

                run_volume = fetch_run_volume(
                    session=session,
                    api_key=api_key,
                    volume_id=run_volume_id,
                )

                remote_issues = fetch_run_issues(
                    session=session,
                    api_key=api_key,
                    volume_id=run_volume_id,
                    include_future=include_future,
                )

                collected_volume_data = fetch_collected_volume_data(
                    session=session,
                    api_key=api_key,
                )

        except (ComicVineAPIError, RequestException) as error:
            raise CommandError(f"Comic Vine/API/web error: {error}") from error

        if not remote_issues:
            raise CommandError("No Uncanny X-Men issues were returned from Comic Vine.")

        with transaction.atomic():
            result = seed_catalog(
                run_volume=run_volume,
                remote_issues=remote_issues,
                collected_volume_data=collected_volume_data,
                overwrite=overwrite,
                dry_run=dry_run,
            )

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Run complete."))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Catalog run: {result['run_label']}")
        self.stdout.write(f"Issues returned from Comic Vine: {len(remote_issues)}")
        self.stdout.write(f"Highest issue number added/updated: {result['highest_issue_number']}")
        self.stdout.write(f"Volume 1 title: {result['volume_title']}")
        self.stdout.write("")
        self.stdout.write("Created")
        self.stdout.write("-" * 60)
        print_counts(self, result["created"])
        self.stdout.write("")
        self.stdout.write("Updated")
        self.stdout.write("-" * 60)
        print_counts(self, result["updated"])
        self.stdout.write("")
        self.stdout.write("Skipped")
        self.stdout.write("-" * 60)
        print_counts(self, result["skipped"])


def resolve_current_run_volume_id(*, session, api_key, requested_volume_id):
    if requested_volume_id:
        return requested_volume_id

    local_matches = list(
        ComicVineVolume.objects.filter(
            publisher__iexact=PUBLISHER_NAME,
            name__iexact=RUN_TITLE,
            start_year=RUN_START_YEAR,
        ).order_by("comicvine_id")
    )

    if len(local_matches) == 1:
        return local_matches[0].comicvine_id

    remote_matches = fetch_current_run_volume_candidates(
        session=session,
        api_key=api_key,
    )

    if len(remote_matches) == 1:
        return int(remote_matches[0]["id"])

    if not remote_matches:
        raise ComicVineAPIError(
            "Could not find one current Uncanny X-Men volume on Comic Vine. "
            "Run again with --comicvine-volume-id."
        )

    candidate_lines = [
        format_remote_volume_candidate(candidate)
        for candidate in remote_matches
    ]

    raise ComicVineAPIError(
        "Found multiple possible Uncanny X-Men volumes. "
        "Run again with --comicvine-volume-id.\n"
        + "\n".join(candidate_lines)
    )


def fetch_current_run_volume_candidates(*, session, api_key):
    data = fetch_volumes_page(
        session,
        api_key,
        filter_value=f"name:{RUN_TITLE},start_year:{RUN_START_YEAR}",
        fields=VOLUME_LIST_FIELDS,
        offset=0,
        limit=100,
        sort="date_added:desc",
    )

    candidates = []

    for item in data.get("results", []):
        if not remote_volume_is_current_run_candidate(item):
            continue

        candidates.append(item)

    return candidates


def remote_volume_is_current_run_candidate(item):
    publisher = item.get("publisher") or {}

    return (
        clean_text(item.get("name")).lower() == RUN_TITLE.lower()
        and clean_text(item.get("start_year")) == RUN_START_YEAR
        and clean_text(publisher.get("name")).lower() == PUBLISHER_NAME.lower()
    )


def format_remote_volume_candidate(candidate):
    return (
        f"- ID {candidate.get('id')}: "
        f"{clean_text(candidate.get('name'))} "
        f"({clean_text(candidate.get('start_year'))}), "
        f"count_of_issues={candidate.get('count_of_issues')}"
    )


def fetch_run_volume(*, session, api_key, volume_id):
    data = fetch_volume_detail(
        session,
        api_key,
        volume_id=volume_id,
        fields=VOLUME_LIST_FIELDS,
    )

    return data.get("results") or {}


def fetch_run_issues(*, session, api_key, volume_id, include_future):
    today = timezone.localdate()
    offset = 0
    page_size = 100
    issues = []

    while True:
        data = fetch_issues_page(
            session,
            api_key,
            filter_value=f"volume:{volume_id}",
            fields=ISSUE_LIST_FIELDS,
            offset=offset,
            limit=page_size,
            sort="store_date:asc",
        )

        page_results = data.get("results", [])
        if not page_results:
            break

        for item in page_results:
            store_date = parse_comicvine_date(item.get("store_date"))

            if not include_future and store_date and store_date > today:
                continue

            issues.append(normalize_remote_issue(item))

        total_results = int(data.get("number_of_total_results") or 0)
        offset += page_size

        if offset >= total_results:
            break

    issues.sort(key=issue_sort_key)

    return issues


def normalize_remote_issue(item):
    image_data = item.get("image") or {}

    return {
        "comicvine_id": item.get("id"),
        "issue_number": clean_text(item.get("issue_number")),
        "title": clean_text(item.get("name")),
        "cover_date": parse_comicvine_date(item.get("cover_date")),
        "store_date": parse_comicvine_date(item.get("store_date")),
        "description": clean_description(item.get("description")),
        "image": image_data,
    }


def issue_sort_key(issue):
    return (
        issue["store_date"] or date.max,
        issue_number_sort_value(issue["issue_number"]),
        issue["issue_number"],
    )


def issue_number_sort_value(issue_number):
    cleaned_value = clean_text(issue_number)

    try:
        return float(cleaned_value)
    except ValueError:
        return 999999.0


def clean_description(value):
    cleaned_value = clean_text(value)

    if not cleaned_value:
        return ""

    return unescape(strip_tags(cleaned_value)).strip()


def fetch_collected_volume_data(*, session, api_key):
    candidates = fetch_collected_volume_candidates(
        session=session,
        api_key=api_key,
    )

    if not candidates:
        return {
            "title": COLLECTED_VOLUME_FALLBACK_TITLE,
            "release_date": None,
            "source": "fallback",
        }

    selected_candidate = candidates[0]
    collected_volume_id = selected_candidate["id"]

    collected_issue = fetch_first_collected_volume_issue(
        session=session,
        api_key=api_key,
        collected_volume_id=collected_volume_id,
    )

    return {
        "title": COLLECTED_VOLUME_FALLBACK_TITLE,
        "release_date": collected_issue.get("store_date"),
        "source": f"Comic Vine collected volume ID {collected_volume_id}",
    }


def fetch_collected_volume_candidates(*, session, api_key):
    candidates = []

    for start_year in COLLECTED_VOLUME_SEARCH_START_YEARS:
        data = fetch_volumes_page(
            session,
            api_key,
            filter_value=f"name:{RUN_TITLE},start_year:{start_year}",
            fields=VOLUME_LIST_FIELDS,
            offset=0,
            limit=100,
            sort="date_added:asc",
        )

        for item in data.get("results", []):
            publisher = item.get("publisher") or {}
            first_issue = item.get("first_issue") or {}
            first_issue_name = clean_text(first_issue.get("name")).lower()

            if clean_text(item.get("name")).lower() != RUN_TITLE.lower():
                continue

            if clean_text(publisher.get("name")).lower() != PUBLISHER_NAME.lower():
                continue

            if not first_issue_name.startswith("vol. 1"):
                continue

            candidates.append(item)

    return candidates


def fetch_first_collected_volume_issue(*, session, api_key, collected_volume_id):
    data = fetch_issues_page(
        session,
        api_key,
        filter_value=f"volume:{collected_volume_id}",
        fields=ISSUE_LIST_FIELDS,
        offset=0,
        limit=1,
        sort="store_date:asc",
    )

    results = data.get("results") or []

    if not results:
        return {
            "title": "",
            "store_date": None,
        }

    issue = normalize_remote_issue(results[0])

    return {
        "title": issue["title"],
        "store_date": issue["store_date"],
    }


def seed_catalog(*, run_volume, remote_issues, collected_volume_data, overwrite, dry_run):
    created = empty_count_group()
    updated = empty_count_group()
    skipped = empty_count_group()

    publisher, was_created = get_or_create_publisher(dry_run=dry_run)

    if was_created:
        created["publishers"] += 1
    else:
        if update_publisher(publisher, overwrite=overwrite, dry_run=dry_run):
            updated["publishers"] += 1
        else:
            skipped["publishers"] += 1

    run, was_created = get_or_create_run(
        publisher=publisher,
        run_volume=run_volume,
        remote_issues=remote_issues,
        dry_run=dry_run,
    )

    if was_created:
        created["runs"] += 1
    else:
        if update_run(
            run=run,
            run_volume=run_volume,
            remote_issues=remote_issues,
            overwrite=overwrite,
            dry_run=dry_run,
        ):
            updated["runs"] += 1
        else:
            skipped["runs"] += 1

    volume, was_created = get_or_create_collected_volume(
        publisher=publisher,
        run=run,
        collected_volume_data=collected_volume_data,
        dry_run=dry_run,
    )

    if was_created:
        created["volumes"] += 1
    else:
        if update_collected_volume(
            volume=volume,
            publisher=publisher,
            run=run,
            collected_volume_data=collected_volume_data,
            overwrite=overwrite,
            dry_run=dry_run,
        ):
            updated["volumes"] += 1
        else:
            skipped["volumes"] += 1

    issues_by_number = {}

    for issue_data in remote_issues:
        issue, was_created = get_or_create_issue(
            run=run,
            issue_data=issue_data,
            dry_run=dry_run,
        )
        issues_by_number[issue.issue_number] = issue

        if was_created:
            created["issues"] += 1
        else:
            if update_issue(
                issue=issue,
                issue_data=issue_data,
                overwrite=overwrite,
                dry_run=dry_run,
            ):
                updated["issues"] += 1
            else:
                skipped["issues"] += 1

    for issue_number in COLLECTED_VOLUME_ISSUE_NUMBERS:
        issue = issues_by_number.get(issue_number)

        if not issue:
            skipped["volume_issue_links"] += 1
            continue

        issue_order = COLLECTED_VOLUME_ISSUE_NUMBERS.index(issue_number) + 1

        was_created, was_updated = create_or_update_volume_issue_link(
            volume=volume,
            issue=issue,
            issue_order=issue_order,
            dry_run=dry_run,
        )

        if was_created:
            created["volume_issue_links"] += 1
        elif was_updated:
            updated["volume_issue_links"] += 1
        else:
            skipped["volume_issue_links"] += 1

    highest_issue_number = max(
        [issue["issue_number"] for issue in remote_issues],
        key=issue_number_sort_value,
    )

    return {
        "run_label": str(run),
        "volume_title": volume.title,
        "highest_issue_number": highest_issue_number,
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def empty_count_group():
    return {
        "publishers": 0,
        "runs": 0,
        "volumes": 0,
        "issues": 0,
        "volume_issue_links": 0,
    }


def get_or_create_publisher(*, dry_run):
    publisher = ComicPublisher.objects.filter(name=PUBLISHER_NAME).first()

    if publisher:
        return publisher, False

    publisher = ComicPublisher(
        name=PUBLISHER_NAME,
        slug=PUBLISHER_SLUG,
    )

    if not dry_run:
        publisher.save()

    return publisher, True


def update_publisher(publisher, *, overwrite, dry_run):
    changed_fields = []

    if set_field(publisher, "slug", PUBLISHER_SLUG, overwrite=overwrite):
        changed_fields.append("slug")

    return save_if_changed(publisher, changed_fields, dry_run=dry_run)


def get_or_create_run(*, publisher, run_volume, remote_issues, dry_run):
    run = (
        ComicRun.objects.filter(
            publisher=publisher,
            title=RUN_TITLE,
            start_year=RUN_START_YEAR,
        )
        .order_by("id")
        .first()
    )

    if run:
        return run, False

    run_data = build_run_data(
        run_volume=run_volume,
        remote_issues=remote_issues,
    )

    run = ComicRun(
        publisher=publisher,
        title=RUN_TITLE,
        start_year=RUN_START_YEAR,
        first_issue_date=run_data["first_issue_date"],
        last_issue_date=run_data["last_issue_date"],
        status=ComicRun.STATUS_ONGOING,
        issue_count=run_data["issue_count"],
        description=run_data["description"],
    )

    if not dry_run:
        run.save()

    return run, True


def update_run(*, run, run_volume, remote_issues, overwrite, dry_run):
    run_data = build_run_data(
        run_volume=run_volume,
        remote_issues=remote_issues,
    )
    changed_fields = []

    for field_name, value in run_data.items():
        if set_field(run, field_name, value, overwrite=overwrite):
            changed_fields.append(field_name)

    if set_field(run, "status", ComicRun.STATUS_ONGOING, overwrite=overwrite):
        changed_fields.append("status")

    return save_if_changed(run, changed_fields, dry_run=dry_run)


def build_run_data(*, run_volume, remote_issues):
    issue_dates = [
        issue["store_date"]
        for issue in remote_issues
        if issue.get("store_date")
    ]

    description = clean_description(run_volume.get("description")) or DEFAULT_RUN_DESCRIPTION

    return {
        "first_issue_date": min(issue_dates) if issue_dates else None,
        "last_issue_date": max(issue_dates) if issue_dates else None,
        "issue_count": len(remote_issues),
        "description": description,
    }


def get_or_create_collected_volume(*, publisher, run, collected_volume_data, dry_run):
    volume = (
        ComicVolume.objects.filter(
            publisher=publisher,
            run=run,
            volume_number=COLLECTED_VOLUME_NUMBER,
        )
        .order_by("id")
        .first()
    )

    if volume:
        return volume, False

    volume = ComicVolume(
        publisher=publisher,
        run=run,
        title=collected_volume_data["title"],
        volume_number=COLLECTED_VOLUME_NUMBER,
        first_issue_number=COLLECTED_VOLUME_FIRST_ISSUE_NUMBER,
        last_issue_number=COLLECTED_VOLUME_LAST_ISSUE_NUMBER,
        release_date=collected_volume_data["release_date"],
        issue_count=len(COLLECTED_VOLUME_ISSUE_NUMBERS),
        description=build_collected_volume_description(collected_volume_data),
    )

    if not dry_run:
        volume.save()

    return volume, True


def update_collected_volume(
    *,
    volume,
    publisher,
    run,
    collected_volume_data,
    overwrite,
    dry_run,
):
    changed_fields = []

    if volume.publisher_id != publisher.id:
        volume.publisher = publisher
        changed_fields.append("publisher")

    if volume.run_id != run.id:
        volume.run = run
        changed_fields.append("run")

    volume_data = {
        "title": collected_volume_data["title"],
        "volume_number": COLLECTED_VOLUME_NUMBER,
        "first_issue_number": COLLECTED_VOLUME_FIRST_ISSUE_NUMBER,
        "last_issue_number": COLLECTED_VOLUME_LAST_ISSUE_NUMBER,
        "release_date": collected_volume_data["release_date"],
        "issue_count": len(COLLECTED_VOLUME_ISSUE_NUMBERS),
        "description": build_collected_volume_description(collected_volume_data),
    }

    for field_name, value in volume_data.items():
        if set_field(volume, field_name, value, overwrite=overwrite):
            changed_fields.append(field_name)

    return save_if_changed(volume, changed_fields, dry_run=dry_run)


def build_collected_volume_description(collected_volume_data):
    source_note = collected_volume_data.get("source") or "manual seed"

    return (
        "The first collected volume of the 2024 Uncanny X-Men run by Gail Simone "
        "and David Marquez, collecting Uncanny X-Men #1-6. "
        f"Collected-volume release source: {source_note}."
    )


def get_or_create_issue(*, run, issue_data, dry_run):
    issue = (
        ComicIssue.objects.filter(
            run=run,
            issue_number=issue_data["issue_number"],
        )
        .order_by("id")
        .first()
    )

    if issue:
        return issue, False

    issue = ComicIssue(
        run=run,
        issue_number=issue_data["issue_number"],
        title=issue_data["title"],
        cover_date=issue_data["cover_date"],
        store_date=issue_data["store_date"],
        description=issue_data["description"],
    )

    if not dry_run:
        issue.save()

    return issue, True


def update_issue(*, issue, issue_data, overwrite, dry_run):
    changed_fields = []

    for field_name in [
        "title",
        "cover_date",
        "store_date",
        "description",
    ]:
        if set_field(issue, field_name, issue_data[field_name], overwrite=overwrite):
            changed_fields.append(field_name)

    return save_if_changed(issue, changed_fields, dry_run=dry_run)


def create_or_update_volume_issue_link(*, volume, issue, issue_order, dry_run):
    link = (
        ComicVolumeIssue.objects.filter(
            volume=volume,
            issue=issue,
        )
        .order_by("id")
        .first()
    )

    if link is None:
        link = ComicVolumeIssue(
            volume=volume,
            issue=issue,
            issue_order=issue_order,
        )

        if not dry_run:
            link.save()

        return True, False

    if link.issue_order == issue_order:
        return False, False

    link.issue_order = issue_order

    if not dry_run:
        link.save(update_fields=["issue_order"])

    return False, True


def is_empty(value):
    return value is None or value == ""


def set_field(obj, field_name, value, *, overwrite):
    current_value = getattr(obj, field_name)

    if overwrite or is_empty(current_value):
        setattr(obj, field_name, value)
        return True

    return False


def save_if_changed(obj, changed_fields, *, dry_run):
    if not changed_fields:
        return False

    if not dry_run:
        obj.save(update_fields=sorted(set(changed_fields)))

    return True


def print_counts(command, counts):
    for label, count in counts.items():
        command.stdout.write(f"{label}: {count}")