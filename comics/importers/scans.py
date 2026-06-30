from django.db import transaction
from django.utils import timezone

from comics.models import ComicVineDateScan, ComicVineSyncState


DEFAULT_SYNC_STATE_NAME = "default"


def get_default_sync_state():
    sync_state, _created = ComicVineSyncState.objects.get_or_create(
        name=DEFAULT_SYNC_STATE_NAME
    )

    return sync_state


def set_update_tracking_start_date_if_missing(start_date):
    with transaction.atomic():
        sync_state, _created = ComicVineSyncState.objects.select_for_update().get_or_create(
            name=DEFAULT_SYNC_STATE_NAME
        )

        if sync_state.update_tracking_start_date:
            return sync_state, False

        sync_state.update_tracking_start_date = start_date
        sync_state.save(update_fields=["update_tracking_start_date", "updated_at"])

    return sync_state, True


def get_or_create_date_scan(*, scan_kind, scan_date):
    scan, _created = ComicVineDateScan.objects.get_or_create(
        scan_kind=scan_kind,
        scan_date=scan_date,
    )

    return scan


def get_incomplete_date_scan(*, scan_kind, scan_date):
    return ComicVineDateScan.objects.filter(
        scan_kind=scan_kind,
        scan_date=scan_date,
        completed=False,
    ).first()


def start_or_resume_date_scan(*, scan_kind, scan_date):
    return get_or_create_date_scan(scan_kind=scan_kind, scan_date=scan_date)


def advance_date_scan_after_success(
    *,
    scan_id,
    next_offset,
    total_results,
    completed=False,
    notes="",
):
    with transaction.atomic():
        scan = ComicVineDateScan.objects.select_for_update().get(id=scan_id)
        scan.next_offset = next_offset
        scan.total_results = total_results
        scan.last_scanned_at = timezone.now()

        update_fields = [
            "next_offset",
            "total_results",
            "last_scanned_at",
        ]

        if notes:
            scan.notes = notes
            update_fields.append("notes")

        if completed:
            scan.completed = True
            scan.completed_at = timezone.now()
            update_fields.extend(["completed", "completed_at"])

        scan.save(update_fields=update_fields)

    return scan


def mark_date_scan_complete(*, scan_id, total_results=None, notes=""):
    with transaction.atomic():
        scan = ComicVineDateScan.objects.select_for_update().get(id=scan_id)
        scan.completed = True
        scan.completed_at = timezone.now()
        scan.last_scanned_at = timezone.now()

        update_fields = [
            "completed",
            "completed_at",
            "last_scanned_at",
        ]

        if total_results is not None:
            scan.total_results = total_results
            update_fields.append("total_results")

        if notes:
            scan.notes = notes
            update_fields.append("notes")

        scan.save(update_fields=update_fields)

    return scan


def get_next_backfill_scan_date():
    sync_state = get_default_sync_state()

    if not sync_state.update_tracking_start_date:
        return None

    latest_incomplete_scan = (
        ComicVineDateScan.objects.filter(
            scan_kind=ComicVineDateScan.ISSUE_DATE_ADDED,
            completed=False,
            scan_date__lt=sync_state.update_tracking_start_date,
        )
        .order_by("-scan_date")
        .first()
    )

    if latest_incomplete_scan:
        return latest_incomplete_scan.scan_date

    latest_completed_scan = (
        ComicVineDateScan.objects.filter(
            scan_kind=ComicVineDateScan.ISSUE_DATE_ADDED,
            completed=True,
            scan_date__lt=sync_state.update_tracking_start_date,
        )
        .order_by("scan_date")
        .first()
    )

    if latest_completed_scan:
        from datetime import timedelta

        return latest_completed_scan.scan_date - timedelta(days=1)

    from datetime import timedelta

    return sync_state.update_tracking_start_date - timedelta(days=1)