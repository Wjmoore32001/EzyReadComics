import os
import re
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max
from django.utils import timezone

from comics.models import ComicIssue, ComicVolume


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
USER_AGENT = "EzyReadComics selected volume issue backfiller"
COMICVINE_PAGE_LIMIT = 100


@dataclass
class BackfillSummary:
    volumes_checked: int = 0
    volumes_skipped_missing_start_year: int = 0
    issue_pages_fetched: int = 0
    issue_candidates_checked: int = 0
    issues_created: int = 0
    issues_updated: int = 0
    existing_issues_skipped: int = 0
    wrong_volume_skipped: int = 0
    before_volume_start_year_skipped: int = 0
    missing_date_skipped: int = 0
    missing_issue_id_skipped: int = 0
    api_errors_skipped: int = 0
    api_requests_made: int = 0


class Command(BaseCommand):
    help = (
        "Temporarily backfill issues for the ComicVolume rows already in the local database. "
        "This is for the controlled current-Marvel sandbox setup."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--volume-id",
            type=int,
            default=None,
            help="Optional Comic Vine volume ID. If provided, only this local volume is processed.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=0.25,
            help="Seconds to pause after Comic Vine requests. Defaults to 0.25.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be saved without writing database changes.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError("COMICVINE_API_KEY is not set. Add it to your .env file.")

        volume_id = options["volume_id"]
        request_delay = options["request_delay"]
        dry_run = options["dry_run"]

        if request_delay < 0:
            raise CommandError("request-delay cannot be negative.")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Selected volume issue backfiller"))
        self.stdout.write("This is a temporary/manual sandbox command.")
        self.stdout.write("It uses local ComicVolume rows as the source of truth.")
        self.stdout.write("It queries Comic Vine /issues/ by the local volume Comic Vine ID.")
        self.stdout.write("It only saves issues whose returned volume ID matches the local volume.")
        self.stdout.write("It only saves issues dated in or after the local volume start_year.")
        self.stdout.write("There is no artificial issue-create limit. It fetches pages until Comic Vine is done.")

        if volume_id:
            self.stdout.write(f"Restricted to Comic Vine volume ID: {volume_id}")

        summary = backfill_volume_issues(
            command=self,
            api_key=api_key,
            volume_id=volume_id,
            request_delay=request_delay,
            dry_run=dry_run,
        )

        print_summary(self, summary)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def backfill_volume_issues(command, api_key, volume_id, request_delay, dry_run):
    summary = BackfillSummary()
    volumes = get_volumes_to_process(volume_id=volume_id)

    command.stdout.write(f"Local volumes to process: {volumes.count()}")

    for volume in volumes:
        process_volume(
            command=command,
            api_key=api_key,
            volume=volume,
            request_delay=request_delay,
            dry_run=dry_run,
            summary=summary,
        )

    return summary


def get_volumes_to_process(volume_id):
    queryset = ComicVolume.objects.filter(comicvine_id__isnull=False).order_by(
        "start_year",
        "name",
        "id",
    )

    if volume_id:
        queryset = queryset.filter(comicvine_id=volume_id)

    return queryset


def process_volume(command, api_key, volume, request_delay, dry_run, summary):
    summary.volumes_checked += 1
    volume_start_year = parse_start_year(volume.start_year)

    command.stdout.write("")
    command.stdout.write(
        command.style.SUCCESS(
            f"Volume: {volume.name} ({volume.start_year}) [Comic Vine ID {volume.comicvine_id}]"
        )
    )

    if not volume_start_year:
        command.stdout.write(
            command.style.WARNING(
                "Skipping volume because it does not have a usable start_year."
            )
        )
        summary.volumes_skipped_missing_start_year += 1
        return

    offset = 0
    saved_for_volume = 0

    while True:
        try:
            data = fetch_issue_page(
                api_key=api_key,
                volume_id=volume.comicvine_id,
                offset=offset,
            )
        except CommandError as error:
            command.stdout.write(
                command.style.WARNING(
                    f"Comic Vine request failed for this volume page. Skipping rest of volume. Error: {error}"
                )
            )
            summary.api_errors_skipped += 1
            return

        summary.api_requests_made += 1
        summary.issue_pages_fetched += 1

        total_results = to_int(data.get("number_of_total_results"))
        issues = data.get("results") or []

        command.stdout.write(
            f"Issue page fetched: offset={offset}, returned={len(issues)}, total={total_results}"
        )

        if not issues:
            break

        for issue in issues:
            summary.issue_candidates_checked += 1

            save_result = process_issue_candidate(
                command=command,
                issue=issue,
                volume=volume,
                volume_start_year=volume_start_year,
                dry_run=dry_run,
            )

            if save_result == "created":
                summary.issues_created += 1
                saved_for_volume += 1
            elif save_result == "updated":
                summary.issues_updated += 1
                saved_for_volume += 1
            elif save_result == "existing_skipped":
                summary.existing_issues_skipped += 1
            elif save_result == "wrong_volume":
                summary.wrong_volume_skipped += 1
            elif save_result == "before_volume_start_year":
                summary.before_volume_start_year_skipped += 1
            elif save_result == "missing_date":
                summary.missing_date_skipped += 1
            elif save_result == "missing_issue_id":
                summary.missing_issue_id_skipped += 1

        offset += len(issues)

        if len(issues) < COMICVINE_PAGE_LIMIT:
            break

        if total_results > 0 and offset >= total_results:
            break

        sleep_if_needed(request_delay)

    if saved_for_volume > 0 and not dry_run:
        update_volume_latest_local_issue_store_date(volume)

    command.stdout.write(f"Issues saved for this volume: {saved_for_volume}")


def fetch_issue_page(api_key, volume_id, offset):
    params = {
        "api_key": api_key,
        "format": "json",
        "limit": COMICVINE_PAGE_LIMIT,
        "offset": offset,
        "sort": "cover_date:asc",
        "filter": f"volume:{volume_id}",
        "field_list": ",".join(
            [
                "id",
                "aliases",
                "api_detail_url",
                "issue_number",
                "name",
                "date_added",
                "date_last_updated",
                "cover_date",
                "store_date",
                "site_detail_url",
                "deck",
                "description",
                "has_staff_review",
                "image",
                "volume",
            ]
        ),
    }

    return fetch_comicvine_json(ISSUES_URL, params)


def process_issue_candidate(command, issue, volume, volume_start_year, dry_run):
    issue_id = to_optional_int(issue.get("id"))

    if not issue_id:
        return "missing_issue_id"

    returned_volume_id = get_volume_id(issue.get("volume") or {})

    if returned_volume_id != volume.comicvine_id:
        command.stdout.write(
            command.style.WARNING(
                f"Skip issue ID {issue_id}: returned volume ID {returned_volume_id}, "
                f"expected {volume.comicvine_id}"
            )
        )
        return "wrong_volume"

    issue_date = get_best_issue_date(issue)

    if not issue_date:
        command.stdout.write(
            command.style.WARNING(
                f"Skip issue ID {issue_id}: no usable store_date or cover_date"
            )
        )
        return "missing_date"

    if issue_date.year < volume_start_year:
        command.stdout.write(
            command.style.WARNING(
                f"Skip issue ID {issue_id}: issue date {issue_date} is before volume start year {volume_start_year}"
            )
        )
        return "before_volume_start_year"

    existing_issue = ComicIssue.objects.filter(comicvine_id=issue_id).first()

    if existing_issue:
        if existing_issue.volume_id == volume.id:
            print_issue_preview(
                command=command,
                action="Update existing issue",
                issue=issue,
                volume=volume,
                issue_id=issue_id,
                issue_date=issue_date,
            )

            if not dry_run:
                save_issue(issue=issue, volume=volume)

            return "updated"

        command.stdout.write(
            command.style.WARNING(
                f"Skip issue ID {issue_id}: already exists on a different local volume."
            )
        )
        return "existing_skipped"

    print_issue_preview(
        command=command,
        action="Create issue",
        issue=issue,
        volume=volume,
        issue_id=issue_id,
        issue_date=issue_date,
    )

    if not dry_run:
        save_issue(issue=issue, volume=volume)

    return "created"


def save_issue(issue, volume):
    image = issue.get("image") or {}

    ComicIssue.objects.update_or_create(
        comicvine_id=issue["id"],
        defaults={
            "volume": volume,
            "issue_number": str(issue.get("issue_number") or ""),
            "issue_title": issue.get("name") or "",
            "cover_date": parse_comicvine_date(issue.get("cover_date")),
            "store_date": parse_comicvine_date(issue.get("store_date")),
            "date_added": parse_comicvine_datetime(issue.get("date_added")),
            "date_last_updated": parse_comicvine_datetime(issue.get("date_last_updated")),
            "comicvine_url": issue.get("site_detail_url") or "",
            "api_detail_url": issue.get("api_detail_url") or "",
            "aliases": issue.get("aliases") or "",
            "deck": issue.get("deck") or "",
            "description": issue.get("description") or "",
            "has_staff_review": bool(issue.get("has_staff_review")),
            "comicvine_image_icon_url": image.get("icon_url") or "",
            "comicvine_image_medium_url": image.get("medium_url") or "",
            "comicvine_image_screen_url": image.get("screen_url") or "",
            "comicvine_image_screen_large_url": image.get("screen_large_url") or "",
            "comicvine_image_small_url": image.get("small_url") or "",
            "comicvine_image_super_url": image.get("super_url") or "",
            "comicvine_image_thumb_url": image.get("thumb_url") or "",
            "comicvine_image_tiny_url": image.get("tiny_url") or "",
            "comicvine_image_original_url": image.get("original_url") or "",
            "comicvine_image_tags": image.get("image_tags") or "",
        },
    )


def get_volume_id(volume):
    raw_volume_id = volume.get("id")

    if raw_volume_id:
        parsed_id = to_optional_int(raw_volume_id)

        if parsed_id:
            return parsed_id

    api_detail_url = volume.get("api_detail_url") or ""
    match = re.search(r"4050-(\d+)", api_detail_url)

    if match:
        return int(match.group(1))

    site_detail_url = volume.get("site_detail_url") or ""
    match = re.search(r"4050-(\d+)", site_detail_url)

    if match:
        return int(match.group(1))

    return None


def get_best_issue_date(issue):
    store_date = parse_comicvine_date(issue.get("store_date"))

    if store_date:
        return store_date

    return parse_comicvine_date(issue.get("cover_date"))


def parse_start_year(value):
    if not value:
        return None

    match = re.search(r"\d{4}", str(value))

    if not match:
        return None

    return int(match.group(0))


def update_volume_latest_local_issue_store_date(volume):
    latest_store_date = (
        ComicIssue.objects.filter(
            volume=volume,
            store_date__isnull=False,
        )
        .aggregate(latest_store_date=Max("store_date"))
        .get("latest_store_date")
    )

    if volume.latest_local_issue_store_date != latest_store_date:
        volume.latest_local_issue_store_date = latest_store_date
        volume.save(update_fields=["latest_local_issue_store_date"])


def fetch_comicvine_json(url, params):
    headers = {
        "User-Agent": USER_AGENT,
    }

    max_attempts = 3
    retry_statuses = {429, 500, 502, 503, 504}

    for attempt_number in range(1, max_attempts + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as error:
            if attempt_number == max_attempts:
                raise CommandError(
                    f"Comic Vine request failed after {max_attempts} attempts: {error}"
                ) from error

            time.sleep(attempt_number * 2)
            continue

        if response.status_code == 200:
            data = response.json()

            status_code = data.get("status_code")
            error_message = data.get("error")

            if str(status_code) != "1":
                raise CommandError(
                    f"Comic Vine API returned status_code={status_code}: {error_message}"
                )

            return data

        if response.status_code == 420:
            raise CommandError(
                "Comic Vine returned HTTP 420. This is probably a temporary rate or velocity limit. "
                "Wait before running the command again."
            )

        if response.status_code in retry_statuses:
            if attempt_number == max_attempts:
                raise CommandError(
                    f"Comic Vine request failed with HTTP status {response.status_code} "
                    f"after {max_attempts} attempts."
                )

            time.sleep(attempt_number * 2)
            continue

        raise CommandError(
            f"Comic Vine request failed with HTTP status {response.status_code}."
        )

    raise CommandError("Comic Vine request failed unexpectedly.")


def parse_comicvine_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_comicvine_datetime(value):
    if not value:
        return None

    try:
        parsed_datetime = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    if timezone.is_naive(parsed_datetime):
        return timezone.make_aware(parsed_datetime, timezone.get_current_timezone())

    return parsed_datetime


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sleep_if_needed(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)


def print_issue_preview(command, action, issue, volume, issue_id, issue_date):
    command.stdout.write(
        f"{action}: {volume.name} #{issue.get('issue_number') or ''} "
        f"— {issue.get('name') or ''} "
        f"[Comic Vine Issue ID {issue_id}] "
        f"[date {issue_date}]"
    )


def print_summary(command, summary):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Selected volume issue backfill summary:"))
    command.stdout.write(f"Volumes checked: {summary.volumes_checked}")
    command.stdout.write(f"Volumes skipped missing start_year: {summary.volumes_skipped_missing_start_year}")
    command.stdout.write(f"Issue pages fetched: {summary.issue_pages_fetched}")
    command.stdout.write(f"Issue candidates checked: {summary.issue_candidates_checked}")
    command.stdout.write(f"Issues created: {summary.issues_created}")
    command.stdout.write(f"Issues updated: {summary.issues_updated}")
    command.stdout.write(f"Existing issues skipped: {summary.existing_issues_skipped}")
    command.stdout.write(f"Wrong-volume issues skipped: {summary.wrong_volume_skipped}")
    command.stdout.write(f"Issues before volume start year skipped: {summary.before_volume_start_year_skipped}")
    command.stdout.write(f"Issues missing date skipped: {summary.missing_date_skipped}")
    command.stdout.write(f"Issues missing issue ID skipped: {summary.missing_issue_id_skipped}")
    command.stdout.write(f"Comic Vine API requests made: {summary.api_requests_made}")
    command.stdout.write(f"Comic Vine/API errors skipped: {summary.api_errors_skipped}")