from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from comics.importers.results import DateScanProgressResult
from comics.models import ComicVineDateScan, ComicVineSyncState


DEFAULT_SYNC_STATE_NAME = "default"


def parse_scan_date(value):
    if value is None:
        return None

    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value

    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Date must use YYYY-MM-DD format.") from error


def get_default_current_import_start_date():
    return timezone.localdate() - timedelta(days=1)


def validate_date_window(start_date, end_date):
    if start_date is None:
        raise ValueError("start_date is required.")

    if end_date is None:
        raise ValueError("end_date is required.")

    if end_date < start_date:
        raise ValueError("end_date cannot be earlier than start_date.")


def get_or_initialize_default_sync_state(*, start_date=None, dry_run=False):
    effective_start_date = start_date or get_default_current_import_start_date()

    state = ComicVineSyncState.objects.filter(name=DEFAULT_SYNC_STATE_NAME).first()

    if state:
        if state.update_tracking_start_date:
            if start_date and start_date != state.update_tracking_start_date:
                raise ValueError(
                    "ComicVineSyncState already has update_tracking_start_date="
                    f"{state.update_tracking_start_date}. Do not pass --start-date "
                    "unless the sync state is empty."
                )

            return state, False, False

        if dry_run:
            state.update_tracking_start_date = effective_start_date
            return state, False, True

        state.update_tracking_start_date = effective_start_date
        state.save(update_fields=["update_tracking_start_date", "updated_at"])

        return state, False, True

    if dry_run:
        state = ComicVineSyncState(
            name=DEFAULT_SYNC_STATE_NAME,
            update_tracking_start_date=effective_start_date,
        )
        return state, True, True

    state = ComicVineSyncState.objects.create(
        name=DEFAULT_SYNC_STATE_NAME,
        update_tracking_start_date=effective_start_date,
    )

    return state, True, True


def get_next_incomplete_date_scan(*, scan_kind, start_date, end_date, dry_run=False):
    validate_date_window(start_date, end_date)

    current_date = start_date

    while current_date <= end_date:
        scan = ComicVineDateScan.objects.filter(
            scan_kind=scan_kind,
            scan_date=current_date,
        ).first()

        if scan:
            if not scan.completed:
                return scan, False

            current_date += timedelta(days=1)
            continue

        if dry_run:
            scan = ComicVineDateScan(
                scan_kind=scan_kind,
                scan_date=current_date,
                next_offset=0,
                total_results=0,
                completed=False,
            )
            return scan, True

        scan, created = ComicVineDateScan.objects.get_or_create(
            scan_kind=scan_kind,
            scan_date=current_date,
            defaults={
                "next_offset": 0,
                "total_results": 0,
                "completed": False,
            },
        )

        if not scan.completed:
            return scan, created

        current_date += timedelta(days=1)

    return None, False


def advance_date_scan_after_page(
    *,
    scan,
    starting_offset,
    total_results,
    page_results,
    dry_run=False,
):
    total_results = int(total_results or 0)
    page_results = int(page_results or 0)
    ending_offset = starting_offset + page_results

    completed = page_results == 0 or ending_offset >= total_results

    result = DateScanProgressResult(
        scan_kind=scan.scan_kind,
        scan_date=scan.scan_date,
        starting_offset=starting_offset,
        ending_offset=ending_offset,
        total_results=total_results,
        page_results=page_results,
        completed=completed,
    )

    if dry_run:
        return result

    with transaction.atomic():
        locked_scan = ComicVineDateScan.objects.select_for_update().get(id=scan.id)

        locked_scan.total_results = total_results
        locked_scan.next_offset = ending_offset
        locked_scan.last_scanned_at = timezone.now()
        locked_scan.completed = completed

        update_fields = [
            "total_results",
            "next_offset",
            "last_scanned_at",
            "completed",
        ]

        if completed and locked_scan.completed_at is None:
            locked_scan.completed_at = timezone.now()
            update_fields.append("completed_at")

        locked_scan.save(update_fields=update_fields)

    return result