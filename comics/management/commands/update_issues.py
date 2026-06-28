import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from comics.models import (
    ComicIssue,
    ComicVineDateScan,
    ComicVineSyncState,
    ComicVolume,
)


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
USER_AGENT = "EzyReadComics issue update importer"


@dataclass
class UnsavedDateScan:
    scan_kind: str
    scan_date: object
    next_offset: int = 0
    total_results: int = 0
    completed: bool = False
    last_scanned_at: object = None
    completed_at: object = None


@dataclass
class UnsavedSyncState:
    update_tracking_start_date: object


@dataclass
class BatchResult:
    scan_date: object
    starting_offset: int
    ending_offset: int
    total_results: int
    candidates_checked: int = 0
    issues_created: int = 0
    issues_updated: int = 0
    missing_data_skipped: int = 0
    volume_lookups: int = 0
    date_completed: bool = False


@dataclass
class ImportSummary:
    issue_update_batches_fetched: int = 0
    candidates_checked: int = 0
    issues_created: int = 0
    issues_updated: int = 0
    missing_data_skipped: int = 0
    volume_lookups: int = 0
    dates_completed: int = 0


class Command(BaseCommand):
    help = (
        "Update local ComicIssue rows from Comic Vine issue records changed by "
        "date_last_updated. This command does not scan today."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--candidate-limit",
            type=int,
            default=100,
            help="Number of Comic Vine issue update candidates to fetch per batch. Defaults to 100.",
        )

        parser.add_argument(
            "--max-update-batches",
            type=int,
            default=1,
            help="Maximum number of issue update batches to fetch in one run. Defaults to 1.",
        )

        parser.add_argument(
            "--volume-request-delay",
            type=float,
            default=0.25,
            help="Seconds to pause after each Comic Vine volume lookup. Defaults to 0.25.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be updated without saving anything.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        candidate_limit = options["candidate_limit"]
        max_update_batches = options["max_update_batches"]
        volume_request_delay = options["volume_request_delay"]
        dry_run = options["dry_run"]

        validate_options(
            candidate_limit=candidate_limit,
            max_update_batches=max_update_batches,
            volume_request_delay=volume_request_delay,
        )

        sync_state = get_or_create_sync_state(dry_run=dry_run)
        update_tracking_start_date = sync_state.update_tracking_start_date

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine issue update importer"))
        self.stdout.write("Scanning Comic Vine issues by date_last_updated.")
        self.stdout.write("Today is intentionally not scanned.")
        self.stdout.write(f"Newest possible scan date: {get_newest_allowed_scan_date().isoformat()}")
        self.stdout.write(f"Update tracking start date: {update_tracking_start_date.isoformat()}")
        self.stdout.write(f"Candidate batch size: {candidate_limit}")
        self.stdout.write(f"Maximum issue update batches this run: {max_update_batches}")

        summary = ImportSummary()
        volume_cache = {}

        for batch_number in range(1, max_update_batches + 1):
            scan = get_next_incomplete_date_scan(
                update_tracking_start_date=update_tracking_start_date,
                dry_run=dry_run,
            )

            if not scan:
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        "No incomplete issue update dates remain at or after the update tracking start date."
                    )
                )
                break

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"Issue update batch {batch_number}"))
            self.stdout.write(f"Scan date_last_updated day: {scan.scan_date}")
            self.stdout.write(f"Starting offset for this date_last_updated day: {scan.next_offset}")

            result = process_one_issue_update_batch(
                command=self,
                api_key=api_key,
                scan=scan,
                candidate_limit=candidate_limit,
                volume_cache=volume_cache,
                volume_request_delay=volume_request_delay,
                dry_run=dry_run,
            )

            summary.issue_update_batches_fetched += 1
            summary.candidates_checked += result.candidates_checked
            summary.issues_created += result.issues_created
            summary.issues_updated += result.issues_updated
            summary.missing_data_skipped += result.missing_data_skipped
            summary.volume_lookups += result.volume_lookups

            if result.date_completed:
                summary.dates_completed += 1

            print_batch_summary(self, result)

        print_import_summary(self, summary)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def validate_options(candidate_limit, max_update_batches, volume_request_delay):
    if candidate_limit < 1:
        raise CommandError("candidate-limit must be at least 1.")

    if candidate_limit > 100:
        raise CommandError("Comic Vine issue requests cannot use a limit above 100.")

    if max_update_batches < 1:
        raise CommandError("max-update-batches must be at least 1.")

    if max_update_batches > 5:
        raise CommandError("This importer only allows max-update-batches up to 5 for now.")

    if volume_request_delay < 0:
        raise CommandError("volume-request-delay cannot be negative.")


def get_newest_allowed_scan_date():
    return timezone.localdate() - timedelta(days=1)


def get_or_create_sync_state(dry_run):
    default_start_date = get_newest_allowed_scan_date()

    existing_sync_state = ComicVineSyncState.objects.filter(name="default").first()

    if existing_sync_state:
        if existing_sync_state.update_tracking_start_date:
            return existing_sync_state

        if dry_run:
            return UnsavedSyncState(update_tracking_start_date=default_start_date)

        existing_sync_state.update_tracking_start_date = default_start_date
        existing_sync_state.save()
        return existing_sync_state

    if dry_run:
        return UnsavedSyncState(update_tracking_start_date=default_start_date)

    return ComicVineSyncState.objects.create(
        name="default",
        update_tracking_start_date=default_start_date,
    )


def get_next_incomplete_date_scan(update_tracking_start_date, dry_run):
    scan_kind = ComicVineDateScan.ISSUE_DATE_LAST_UPDATED
    scan_date = get_newest_allowed_scan_date()

    while scan_date >= update_tracking_start_date:
        existing_scan = ComicVineDateScan.objects.filter(
            scan_kind=scan_kind,
            scan_date=scan_date,
        ).first()

        if existing_scan:
            if existing_scan.completed:
                scan_date = scan_date - timedelta(days=1)
                continue

            if dry_run:
                return UnsavedDateScan(
                    scan_kind=existing_scan.scan_kind,
                    scan_date=existing_scan.scan_date,
                    next_offset=existing_scan.next_offset,
                    total_results=existing_scan.total_results,
                    completed=existing_scan.completed,
                    last_scanned_at=existing_scan.last_scanned_at,
                    completed_at=existing_scan.completed_at,
                )

            return existing_scan

        if dry_run:
            return UnsavedDateScan(
                scan_kind=scan_kind,
                scan_date=scan_date,
            )

        return ComicVineDateScan.objects.create(
            scan_kind=scan_kind,
            scan_date=scan_date,
        )

    return None


def process_one_issue_update_batch(
    command,
    api_key,
    scan,
    candidate_limit,
    volume_cache,
    volume_request_delay,
    dry_run,
):
    starting_offset = scan.next_offset

    data = fetch_issue_update_candidates(
        api_key=api_key,
        scan_date=scan.scan_date,
        limit=candidate_limit,
        offset=starting_offset,
    )

    total_results = to_int(data.get("number_of_total_results"))
    candidates = data.get("results") or []

    print_scan_progress(
        command=command,
        total_results=total_results,
        starting_offset=starting_offset,
        candidates=candidates,
        candidate_limit=candidate_limit,
    )

    scan.total_results = total_results
    scan.last_scanned_at = timezone.now()

    result = BatchResult(
        scan_date=scan.scan_date,
        starting_offset=starting_offset,
        ending_offset=starting_offset,
        total_results=total_results,
    )

    if not candidates:
        scan.completed = True
        scan.completed_at = timezone.now()
        save_scan(scan, dry_run=dry_run)

        result.date_completed = True
        result.ending_offset = scan.next_offset
        return result

    existing_issue_ids = get_existing_issue_ids(candidates)

    for issue in candidates:
        result.candidates_checked += 1

        comicvine_issue_id = issue.get("id")

        if not comicvine_issue_id:
            result.missing_data_skipped += 1
            continue

        volume_data = get_volume_data(
            api_key=api_key,
            volume=issue.get("volume") or {},
            volume_cache=volume_cache,
            volume_request_delay=volume_request_delay,
            dry_run=dry_run,
        )

        if not volume_data:
            result.missing_data_skipped += 1
            continue

        if volume_data["was_fetched_from_api"]:
            result.volume_lookups += 1

        issue_already_exists = comicvine_issue_id in existing_issue_ids

        print_issue_preview(
            command=command,
            issue=issue,
            volume_data=volume_data,
            issue_already_exists=issue_already_exists,
        )

        if not dry_run:
            save_issue(issue=issue, volume_data=volume_data)

        if issue_already_exists:
            result.issues_updated += 1
        else:
            result.issues_created += 1

    scan.next_offset = starting_offset + len(candidates)
    result.ending_offset = scan.next_offset

    if total_results > 0 and scan.next_offset >= total_results:
        scan.completed = True
        scan.completed_at = timezone.now()
        result.date_completed = True

    if len(candidates) < candidate_limit:
        scan.completed = True
        scan.completed_at = timezone.now()
        result.date_completed = True

    save_scan(scan, dry_run=dry_run)

    return result


def fetch_issue_update_candidates(api_key, scan_date, limit, offset):
    start_datetime = datetime.combine(scan_date, datetime_time.min)
    end_datetime = datetime.combine(scan_date, datetime_time.max).replace(microsecond=0)

    params = {
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "offset": offset,
        "sort": "date_last_updated:asc",
        "filter": f"date_last_updated:{start_datetime}|{end_datetime}",
        "field_list": ",".join(
            [
                "id",
                "issue_number",
                "name",
                "date_added",
                "date_last_updated",
                "cover_date",
                "store_date",
                "site_detail_url",
                "image",
                "volume",
            ]
        ),
    }

    return fetch_comicvine_json(ISSUES_URL, params)


def get_existing_issue_ids(candidates):
    candidate_issue_ids = [
        issue.get("id")
        for issue in candidates
        if issue.get("id")
    ]

    return set(
        ComicIssue.objects.filter(
            comicvine_id__in=candidate_issue_ids
        ).values_list("comicvine_id", flat=True)
    )


def get_volume_data(
    api_key,
    volume,
    volume_cache,
    volume_request_delay,
    dry_run,
):
    volume_id = get_volume_id(volume)

    if not volume_id:
        return None

    if volume_id in volume_cache:
        cached_volume_data = volume_cache[volume_id].copy()
        cached_volume_data["was_fetched_from_api"] = False
        return cached_volume_data

    existing_volume = ComicVolume.objects.filter(comicvine_id=volume_id).first()

    if existing_volume and existing_volume.publisher:
        volume_data = {
            "comicvine_id": existing_volume.comicvine_id,
            "name": existing_volume.name,
            "publisher": existing_volume.publisher,
            "date_added": existing_volume.date_added,
            "date_last_updated": existing_volume.date_last_updated,
            "comicvine_url": existing_volume.comicvine_url,
            "was_fetched_from_api": False,
        }
        volume_cache[volume_id] = volume_data.copy()
        return volume_data

    volume_api_url = volume.get("api_detail_url")

    if not volume_api_url:
        return None

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": "id,name,publisher,date_added,date_last_updated,site_detail_url",
    }

    data = fetch_comicvine_json(volume_api_url, params)
    fetched_volume = data.get("results") or {}
    publisher = fetched_volume.get("publisher") or {}

    volume_data = {
        "comicvine_id": volume_id,
        "name": fetched_volume.get("name") or volume.get("name") or "",
        "publisher": publisher.get("name") or "",
        "date_added": parse_comicvine_datetime(fetched_volume.get("date_added")),
        "date_last_updated": parse_comicvine_datetime(fetched_volume.get("date_last_updated")),
        "comicvine_url": fetched_volume.get("site_detail_url") or volume.get("site_detail_url") or "",
        "was_fetched_from_api": True,
    }

    volume_cache[volume_id] = volume_data.copy()

    if not dry_run:
        ComicVolume.objects.update_or_create(
            comicvine_id=volume_data["comicvine_id"],
            defaults={
                "name": volume_data["name"],
                "publisher": volume_data["publisher"],
                "date_added": volume_data["date_added"],
                "date_last_updated": volume_data["date_last_updated"],
                "comicvine_url": volume_data["comicvine_url"],
            },
        )

    time.sleep(volume_request_delay)

    return volume_data


def save_issue(issue, volume_data):
    volume_object, _ = ComicVolume.objects.update_or_create(
        comicvine_id=volume_data["comicvine_id"],
        defaults={
            "name": volume_data["name"],
            "publisher": volume_data["publisher"],
            "date_added": volume_data["date_added"],
            "date_last_updated": volume_data["date_last_updated"],
            "comicvine_url": volume_data["comicvine_url"],
        },
    )

    image = issue.get("image") or {}

    ComicIssue.objects.update_or_create(
        comicvine_id=issue["id"],
        defaults={
            "volume": volume_object,
            "issue_number": issue.get("issue_number") or "",
            "issue_title": issue.get("name") or "",
            "date_added": parse_comicvine_datetime(issue.get("date_added")),
            "date_last_updated": parse_comicvine_datetime(issue.get("date_last_updated")),
            "cover_date": parse_comicvine_date(issue.get("cover_date")),
            "store_date": parse_comicvine_date(issue.get("store_date")),
            "comicvine_url": issue.get("site_detail_url") or "",
            "image_url": image.get("small_url") or "",
        },
    )


def get_volume_id(volume):
    raw_volume_id = volume.get("id")

    if raw_volume_id:
        try:
            return int(raw_volume_id)
        except (TypeError, ValueError):
            pass

    api_detail_url = volume.get("api_detail_url") or ""
    match = re.search(r"4050-(\d+)", api_detail_url)

    if match:
        return int(match.group(1))

    return None


def fetch_comicvine_json(url, params):
    headers = {
        "User-Agent": USER_AGENT,
    }

    response = requests.get(url, params=params, headers=headers, timeout=30)

    if response.status_code == 420:
        raise CommandError(
            "Comic Vine returned HTTP 420. This is probably a temporary rate or velocity limit. "
            "Wait before running the command again."
        )

    if response.status_code != 200:
        raise CommandError(
            f"Comic Vine request failed with HTTP status {response.status_code}."
        )

    data = response.json()

    status_code = data.get("status_code")
    error_message = data.get("error")

    if str(status_code) != "1":
        raise CommandError(
            f"Comic Vine API returned status_code={status_code}: {error_message}"
        )

    return data


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


def save_scan(scan, dry_run):
    if dry_run:
        return

    scan.save()


def print_scan_progress(command, total_results, starting_offset, candidates, candidate_limit):
    candidates_returned = len(candidates)
    expected_checked_after_batch = starting_offset + candidates_returned
    expected_remaining_after_batch = max(total_results - expected_checked_after_batch, 0)

    command.stdout.write("")
    command.stdout.write("Scan progress for this date:")
    command.stdout.write(f"Total candidates for this date: {total_results}")
    command.stdout.write(f"Already checked before this batch: {starting_offset}")
    command.stdout.write(f"Requested batch size: {candidate_limit}")
    command.stdout.write(f"Candidates returned in this batch: {candidates_returned}")
    command.stdout.write(f"Expected checked after this batch: {expected_checked_after_batch}")
    command.stdout.write(f"Expected remaining after this batch: {expected_remaining_after_batch}")


def print_issue_preview(command, issue, volume_data, issue_already_exists):
    image = issue.get("image") or {}
    action = "would update" if issue_already_exists else "would create"

    command.stdout.write("")
    command.stdout.write(
        f"Issue update candidate ({action}): {volume_data['name']} #{issue.get('issue_number') or ''}"
    )
    command.stdout.write(f"Comic Vine Issue ID: {issue.get('id')}")
    command.stdout.write(f"Comic Vine Volume ID: {volume_data['comicvine_id']}")
    command.stdout.write(f"Publisher: {volume_data['publisher']}")
    command.stdout.write(f"Issue Title: {issue.get('name') or ''}")
    command.stdout.write(f"Date Added to Comic Vine: {issue.get('date_added') or ''}")
    command.stdout.write(f"Date Last Updated on Comic Vine: {issue.get('date_last_updated') or ''}")
    command.stdout.write(f"Cover Date: {parse_comicvine_date(issue.get('cover_date')) or ''}")
    command.stdout.write(f"Store Date: {parse_comicvine_date(issue.get('store_date')) or ''}")
    command.stdout.write(f"Comic Vine URL: {issue.get('site_detail_url') or ''}")
    command.stdout.write(f"Image URL: {image.get('small_url') or ''}")


def print_batch_summary(command, result):
    command.stdout.write("")
    command.stdout.write("Batch summary:")
    command.stdout.write(f"Date-last-updated scan day: {result.scan_date}")
    command.stdout.write(f"Starting offset: {result.starting_offset}")
    command.stdout.write(f"Ending offset: {result.ending_offset}")
    command.stdout.write(f"Total issue records updated on Comic Vine on this date: {result.total_results}")
    command.stdout.write(f"Candidates checked in this batch: {result.candidates_checked}")
    command.stdout.write(f"Issues created in this batch: {result.issues_created}")
    command.stdout.write(f"Issues updated in this batch: {result.issues_updated}")
    command.stdout.write(f"Missing-data candidates skipped: {result.missing_data_skipped}")
    command.stdout.write(f"Volume API lookups: {result.volume_lookups}")
    command.stdout.write(f"Date completed: {result.date_completed}")


def print_import_summary(command, summary):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Issue update summary:"))
    command.stdout.write(f"Issue update batches fetched: {summary.issue_update_batches_fetched}")
    command.stdout.write(f"Candidates checked: {summary.candidates_checked}")
    command.stdout.write(f"Issues created: {summary.issues_created}")
    command.stdout.write(f"Issues updated: {summary.issues_updated}")
    command.stdout.write(f"Missing-data candidates skipped: {summary.missing_data_skipped}")
    command.stdout.write(f"Volume API lookups: {summary.volume_lookups}")
    command.stdout.write(f"Dates completed: {summary.dates_completed}")