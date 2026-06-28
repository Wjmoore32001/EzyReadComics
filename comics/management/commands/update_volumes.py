import os
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from comics.models import ComicVineDateScan, ComicVineSyncState, ComicVolume


VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
USER_AGENT = "EzyReadComics volume update importer"


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
    volumes_updated: int = 0
    unknown_volumes_skipped: int = 0
    missing_data_skipped: int = 0
    date_completed: bool = False


@dataclass
class ImportSummary:
    volume_update_batches_fetched: int = 0
    candidates_checked: int = 0
    volumes_updated: int = 0
    unknown_volumes_skipped: int = 0
    missing_data_skipped: int = 0
    dates_completed: int = 0


class Command(BaseCommand):
    help = (
        "Update local ComicVolume rows from Comic Vine volume records changed by "
        "date_last_updated. This command does not scan today."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--candidate-limit",
            type=int,
            default=100,
            help="Number of Comic Vine volume update candidates to fetch per batch. Defaults to 100.",
        )

        parser.add_argument(
            "--max-update-batches",
            type=int,
            default=1,
            help="Maximum number of volume update batches to fetch in one run. Defaults to 1.",
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
        dry_run = options["dry_run"]

        validate_options(
            candidate_limit=candidate_limit,
            max_update_batches=max_update_batches,
        )

        sync_state = get_or_create_sync_state(dry_run=dry_run)
        update_tracking_start_date = sync_state.update_tracking_start_date

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine volume update importer"))
        self.stdout.write("Scanning Comic Vine volumes by date_last_updated.")
        self.stdout.write("Today is intentionally not scanned.")
        self.stdout.write("Only volumes already stored locally will be updated.")
        self.stdout.write(f"Newest possible scan date: {get_newest_allowed_scan_date().isoformat()}")
        self.stdout.write(f"Update tracking start date: {update_tracking_start_date.isoformat()}")
        self.stdout.write(f"Candidate batch size: {candidate_limit}")
        self.stdout.write(f"Maximum volume update batches this run: {max_update_batches}")

        summary = ImportSummary()

        for batch_number in range(1, max_update_batches + 1):
            scan = get_next_incomplete_date_scan(
                update_tracking_start_date=update_tracking_start_date,
                dry_run=dry_run,
            )

            if not scan:
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        "No incomplete volume update dates remain at or after the update tracking start date."
                    )
                )
                break

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"Volume update batch {batch_number}"))
            self.stdout.write(f"Scan date_last_updated day: {scan.scan_date}")
            self.stdout.write(f"Starting offset for this date_last_updated day: {scan.next_offset}")

            result = process_one_volume_update_batch(
                command=self,
                api_key=api_key,
                scan=scan,
                candidate_limit=candidate_limit,
                dry_run=dry_run,
            )

            summary.volume_update_batches_fetched += 1
            summary.candidates_checked += result.candidates_checked
            summary.volumes_updated += result.volumes_updated
            summary.unknown_volumes_skipped += result.unknown_volumes_skipped
            summary.missing_data_skipped += result.missing_data_skipped

            if result.date_completed:
                summary.dates_completed += 1

            print_batch_summary(self, result)

        print_import_summary(self, summary)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def validate_options(candidate_limit, max_update_batches):
    if candidate_limit < 1:
        raise CommandError("candidate-limit must be at least 1.")

    if candidate_limit > 100:
        raise CommandError("Comic Vine volume requests cannot use a limit above 100.")

    if max_update_batches < 1:
        raise CommandError("max-update-batches must be at least 1.")

    if max_update_batches > 5:
        raise CommandError("This importer only allows max-update-batches up to 5 for now.")


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
    scan_kind = ComicVineDateScan.VOLUME_DATE_LAST_UPDATED
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


def process_one_volume_update_batch(
    command,
    api_key,
    scan,
    candidate_limit,
    dry_run,
):
    starting_offset = scan.next_offset

    data = fetch_volume_update_candidates(
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

    existing_volume_ids = get_existing_volume_ids(candidates)

    for volume in candidates:
        result.candidates_checked += 1

        comicvine_volume_id = volume.get("id")

        if not comicvine_volume_id:
            result.missing_data_skipped += 1
            continue

        if comicvine_volume_id not in existing_volume_ids:
            result.unknown_volumes_skipped += 1
            continue

        volume_data = build_volume_data(volume)

        print_volume_preview(
            command=command,
            volume_data=volume_data,
            dry_run=dry_run,
        )

        if not dry_run:
            update_existing_volume(volume_data)

        result.volumes_updated += 1

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


def fetch_volume_update_candidates(api_key, scan_date, limit, offset):
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
                "name",
                "publisher",
                "date_added",
                "date_last_updated",
                "site_detail_url",
            ]
        ),
    }

    return fetch_comicvine_json(VOLUMES_URL, params)


def get_existing_volume_ids(candidates):
    candidate_volume_ids = [
        volume.get("id")
        for volume in candidates
        if volume.get("id")
    ]

    return set(
        ComicVolume.objects.filter(
            comicvine_id__in=candidate_volume_ids
        ).values_list("comicvine_id", flat=True)
    )


def build_volume_data(volume):
    publisher = volume.get("publisher") or {}

    return {
        "comicvine_id": volume["id"],
        "name": volume.get("name") or "",
        "publisher": publisher.get("name") or "",
        "date_added": parse_comicvine_datetime(volume.get("date_added")),
        "date_last_updated": parse_comicvine_datetime(volume.get("date_last_updated")),
        "comicvine_url": volume.get("site_detail_url") or "",
    }


def update_existing_volume(volume_data):
    ComicVolume.objects.filter(
        comicvine_id=volume_data["comicvine_id"],
    ).update(
        name=volume_data["name"],
        publisher=volume_data["publisher"],
        date_added=volume_data["date_added"],
        date_last_updated=volume_data["date_last_updated"],
        comicvine_url=volume_data["comicvine_url"],
    )


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


def print_volume_preview(command, volume_data, dry_run):
    action = "would update" if dry_run else "will update"

    command.stdout.write("")
    command.stdout.write(
        f"Volume update candidate ({action}): {volume_data['name']}"
    )
    command.stdout.write(f"Comic Vine Volume ID: {volume_data['comicvine_id']}")
    command.stdout.write(f"Publisher: {volume_data['publisher']}")
    command.stdout.write(f"Date Added to Comic Vine: {volume_data['date_added'] or ''}")
    command.stdout.write(f"Date Last Updated on Comic Vine: {volume_data['date_last_updated'] or ''}")
    command.stdout.write(f"Comic Vine URL: {volume_data['comicvine_url']}")


def print_batch_summary(command, result):
    command.stdout.write("")
    command.stdout.write("Batch summary:")
    command.stdout.write(f"Date-last-updated scan day: {result.scan_date}")
    command.stdout.write(f"Starting offset: {result.starting_offset}")
    command.stdout.write(f"Ending offset: {result.ending_offset}")
    command.stdout.write(f"Total volume records updated on Comic Vine on this date: {result.total_results}")
    command.stdout.write(f"Candidates checked in this batch: {result.candidates_checked}")
    command.stdout.write(f"Volumes updated in this batch: {result.volumes_updated}")
    command.stdout.write(f"Unknown local volumes skipped: {result.unknown_volumes_skipped}")
    command.stdout.write(f"Missing-data candidates skipped: {result.missing_data_skipped}")
    command.stdout.write(f"Date completed: {result.date_completed}")


def print_import_summary(command, summary):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Volume update summary:"))
    command.stdout.write(f"Volume update batches fetched: {summary.volume_update_batches_fetched}")
    command.stdout.write(f"Candidates checked: {summary.candidates_checked}")
    command.stdout.write(f"Volumes updated: {summary.volumes_updated}")
    command.stdout.write(f"Unknown local volumes skipped: {summary.unknown_volumes_skipped}")
    command.stdout.write(f"Missing-data candidates skipped: {summary.missing_data_skipped}")
    command.stdout.write(f"Dates completed: {summary.dates_completed}")