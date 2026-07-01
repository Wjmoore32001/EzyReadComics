from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q

from comicvine.models import (
    ComicVineDateScan,
    ComicVineIssue,
    ComicVineIssueAssociatedImage,
    ComicVineSyncState,
    ComicVineVolume,
)
from comicvine.services.sync.scans import (
    DEFAULT_SYNC_STATE_NAME,
    get_default_current_import_start_date,
    parse_scan_date,
)


DEFAULT_OLDEST_BACKFILL_DATE = date(1930, 1, 1)

CURRENT_SCAN_KINDS = [
    {
        "label": "Issue date_added",
        "scan_kind": ComicVineDateScan.ISSUE_DATE_ADDED,
    },
    {
        "label": "Issue date_last_updated",
        "scan_kind": ComicVineDateScan.ISSUE_DATE_LAST_UPDATED,
    },
    {
        "label": "Volume date_added",
        "scan_kind": ComicVineDateScan.VOLUME_DATE_ADDED,
    },
    {
        "label": "Volume date_last_updated",
        "scan_kind": ComicVineDateScan.VOLUME_DATE_LAST_UPDATED,
    },
]


class Command(BaseCommand):
    help = "Show current Comic Vine import progress and database coverage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            help=(
                "YYYY-MM-DD. Current scan start date. "
                "Defaults to ComicVineSyncState.update_tracking_start_date."
            ),
        )

        parser.add_argument(
            "--end-date",
            help="YYYY-MM-DD. Current scan end date. Defaults to yesterday.",
        )

        parser.add_argument(
            "--backfill-oldest-date",
            help=(
                "YYYY-MM-DD. Used only for estimating historical issue backfill coverage. "
                "Defaults to 1930-01-01."
            ),
        )

    def handle(self, *args, **options):
        sync_state = get_sync_state()

        start_date = parse_date_option(options["start_date"], "--start-date")
        end_date = parse_date_option(options["end_date"], "--end-date")
        backfill_oldest_date = parse_date_option(
            options["backfill_oldest_date"],
            "--backfill-oldest-date",
        )

        if start_date is None and sync_state:
            start_date = sync_state.update_tracking_start_date

        if end_date is None:
            end_date = get_default_current_import_start_date()

        if backfill_oldest_date is None:
            backfill_oldest_date = DEFAULT_OLDEST_BACKFILL_DATE

        validate_options(
            start_date=start_date,
            end_date=end_date,
            backfill_oldest_date=backfill_oldest_date,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine import status"))

        print_sync_state(
            command=self,
            sync_state=sync_state,
            start_date=start_date,
            end_date=end_date,
            backfill_oldest_date=backfill_oldest_date,
        )

        print_volume_status(command=self)
        print_issue_status(command=self)

        if start_date:
            print_current_scan_status(
                command=self,
                start_date=start_date,
                end_date=end_date,
            )

            print_backfill_status(
                command=self,
                current_import_start_date=start_date,
                oldest_date=backfill_oldest_date,
            )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Scan status unavailable."))
            self.stdout.write(
                "ComicVineSyncState.update_tracking_start_date is not set yet."
            )


def get_sync_state():
    return ComicVineSyncState.objects.filter(name=DEFAULT_SYNC_STATE_NAME).first()


def parse_date_option(value, option_name):
    try:
        return parse_scan_date(value)
    except ValueError as error:
        raise CommandError(f"{option_name}: {error}") from error


def validate_options(*, start_date, end_date, backfill_oldest_date):
    if start_date and end_date and end_date < start_date:
        raise CommandError("--end-date cannot be earlier than --start-date.")

    if backfill_oldest_date is None:
        raise CommandError("--backfill-oldest-date is required.")


def print_sync_state(
    *,
    command,
    sync_state,
    start_date,
    end_date,
    backfill_oldest_date,
):
    command.stdout.write("")
    command.stdout.write("Sync state:")

    if sync_state:
        command.stdout.write(f"  Sync state name: {sync_state.name}")
        command.stdout.write(
            f"  Stored current import start date: "
            f"{format_value(sync_state.update_tracking_start_date)}"
        )
        command.stdout.write(f"  Sync state created: {format_value(sync_state.created_at)}")
        command.stdout.write(f"  Sync state updated: {format_value(sync_state.updated_at)}")
    else:
        command.stdout.write("  No ComicVineSyncState row found.")

    command.stdout.write(f"  Current scan range: {format_value(start_date)} through {format_value(end_date)}")
    command.stdout.write(f"  Backfill oldest date estimate: {backfill_oldest_date}")


def print_volume_status(*, command):
    total_volumes = ComicVineVolume.objects.count()
    refreshed_volumes = ComicVineVolume.objects.filter(
        list_data_refreshed_at__isnull=False,
    ).count()
    never_refreshed_volumes = ComicVineVolume.objects.filter(
        list_data_refreshed_at__isnull=True,
    ).count()
    stale_after_refresh_volumes = ComicVineVolume.objects.filter(
        list_data_refreshed_at__isnull=False,
        date_last_updated__gt=F("list_data_refreshed_at"),
    ).count()
    needs_refresh_volumes = ComicVineVolume.objects.filter(
        Q(list_data_refreshed_at__isnull=True)
        | Q(date_last_updated__gt=F("list_data_refreshed_at"))
    ).count()

    volumes_with_publisher = ComicVineVolume.objects.exclude(publisher="").count()
    volumes_with_issue_count = ComicVineVolume.objects.filter(
        count_of_issues__isnull=False,
    ).count()
    volumes_with_image = ComicVineVolume.objects.exclude(display_image_url="").count()
    detail_hydrated_volumes = ComicVineVolume.objects.filter(
        detail_hydrated_at__isnull=False,
    ).count()
    detail_attempted_volumes = ComicVineVolume.objects.filter(
        detail_hydration_attempted_at__isnull=False,
    ).count()

    command.stdout.write("")
    command.stdout.write("Volumes:")
    command.stdout.write(f"  Total volumes: {total_volumes}")
    command.stdout.write(
        f"  List data refreshed: {refreshed_volumes} "
        f"({format_percent(refreshed_volumes, total_volumes)})"
    )
    command.stdout.write(f"  Never list-data refreshed: {never_refreshed_volumes}")
    command.stdout.write(f"  Stale after last list refresh: {stale_after_refresh_volumes}")
    command.stdout.write(f"  Need list-data refresh now: {needs_refresh_volumes}")
    command.stdout.write(
        f"  Have publisher: {volumes_with_publisher} "
        f"({format_percent(volumes_with_publisher, total_volumes)})"
    )
    command.stdout.write(
        f"  Have issue count: {volumes_with_issue_count} "
        f"({format_percent(volumes_with_issue_count, total_volumes)})"
    )
    command.stdout.write(
        f"  Have display image: {volumes_with_image} "
        f"({format_percent(volumes_with_image, total_volumes)})"
    )
    command.stdout.write(
        f"  Detail hydration attempted: {detail_attempted_volumes} "
        f"({format_percent(detail_attempted_volumes, total_volumes)})"
    )
    command.stdout.write(
        f"  Detail hydrated: {detail_hydrated_volumes} "
        f"({format_percent(detail_hydrated_volumes, total_volumes)})"
    )


def print_issue_status(*, command):
    total_issues = ComicVineIssue.objects.count()
    issues_with_comicvine_id = ComicVineIssue.objects.filter(
        comicvine_id__isnull=False,
    ).count()
    issues_with_volume = ComicVineIssue.objects.filter(volume__isnull=False).count()
    issues_without_volume = ComicVineIssue.objects.filter(volume__isnull=True).count()
    issues_with_store_date = ComicVineIssue.objects.filter(store_date__isnull=False).count()
    issues_with_cover_date = ComicVineIssue.objects.filter(cover_date__isnull=False).count()
    issues_with_image = ComicVineIssue.objects.exclude(comicvine_image_original_url="").count()
    detail_hydrated_issues = ComicVineIssue.objects.filter(
        detail_hydrated_at__isnull=False,
    ).count()
    detail_attempted_issues = ComicVineIssue.objects.filter(
        detail_hydration_attempted_at__isnull=False,
    ).count()
    associated_images = ComicVineIssueAssociatedImage.objects.count()

    command.stdout.write("")
    command.stdout.write("Issues:")
    command.stdout.write(f"  Total issues: {total_issues}")
    command.stdout.write(
        f"  Have Comic Vine ID: {issues_with_comicvine_id} "
        f"({format_percent(issues_with_comicvine_id, total_issues)})"
    )
    command.stdout.write(
        f"  Linked to volume: {issues_with_volume} "
        f"({format_percent(issues_with_volume, total_issues)})"
    )
    command.stdout.write(f"  Missing volume link: {issues_without_volume}")
    command.stdout.write(
        f"  Have store date: {issues_with_store_date} "
        f"({format_percent(issues_with_store_date, total_issues)})"
    )
    command.stdout.write(
        f"  Have cover date: {issues_with_cover_date} "
        f"({format_percent(issues_with_cover_date, total_issues)})"
    )
    command.stdout.write(
        f"  Have original image: {issues_with_image} "
        f"({format_percent(issues_with_image, total_issues)})"
    )
    command.stdout.write(f"  Associated image rows: {associated_images}")
    command.stdout.write(
        f"  Detail hydration attempted: {detail_attempted_issues} "
        f"({format_percent(detail_attempted_issues, total_issues)})"
    )
    command.stdout.write(
        f"  Detail hydrated: {detail_hydrated_issues} "
        f"({format_percent(detail_hydrated_issues, total_issues)})"
    )


def print_current_scan_status(*, command, start_date, end_date):
    command.stdout.write("")
    command.stdout.write("Current scan progress:")

    for scan_config in CURRENT_SCAN_KINDS:
        status = get_scan_range_status(
            scan_kind=scan_config["scan_kind"],
            start_date=start_date,
            end_date=end_date,
        )

        command.stdout.write("")
        command.stdout.write(f"  {scan_config['label']}:")
        command.stdout.write(f"    Date range: {start_date} through {end_date}")
        command.stdout.write(f"    Total days in range: {status['total_days']}")
        command.stdout.write(
            f"    Completed days: {status['completed_days']} "
            f"({format_percent(status['completed_days'], status['total_days'])})"
        )
        command.stdout.write(f"    Incomplete started days: {status['incomplete_started_days']}")
        command.stdout.write(f"    Not started days: {status['not_started_days']}")

        if status["next_open_date"]:
            command.stdout.write(f"    Next open date: {status['next_open_date']}")

            if status["next_open_scan"]:
                scan = status["next_open_scan"]
                command.stdout.write(f"    Next open offset: {scan.next_offset}")
                command.stdout.write(f"    Next open remote total: {scan.total_results}")
            else:
                command.stdout.write("    Next open offset: 0")
        else:
            command.stdout.write("    Next open date: none")


def print_backfill_status(*, command, current_import_start_date, oldest_date):
    status = get_backfill_status(
        current_import_start_date=current_import_start_date,
        oldest_date=oldest_date,
    )

    command.stdout.write("")
    command.stdout.write("Historical issue backfill:")
    command.stdout.write(
        f"  Estimated range: {oldest_date} through "
        f"{current_import_start_date - timedelta(days=1)}"
    )
    command.stdout.write(f"  Existing tracked backfill days: {status['existing_days']}")
    command.stdout.write(f"  Existing completed backfill days: {status['completed_existing_days']}")
    command.stdout.write(f"  Existing incomplete backfill days: {status['incomplete_existing_days']}")
    command.stdout.write(f"  Contiguous completed days from current start going backward: {status['contiguous_completed_days']}")

    if status["confirmed_complete_through"]:
        command.stdout.write(
            f"  Confirmed complete through: {status['confirmed_complete_through']}"
        )
    else:
        command.stdout.write("  Confirmed complete through: none")

    if status["next_unconfirmed_date"]:
        command.stdout.write(f"  Next unconfirmed backfill date: {status['next_unconfirmed_date']}")

        if status["next_unconfirmed_scan"]:
            scan = status["next_unconfirmed_scan"]
            command.stdout.write(f"  Next unconfirmed offset: {scan.next_offset}")
            command.stdout.write(f"  Next unconfirmed remote total: {scan.total_results}")
        else:
            command.stdout.write("  Next unconfirmed offset: 0")
    else:
        command.stdout.write("  Next unconfirmed backfill date: none")


def get_scan_range_status(*, scan_kind, start_date, end_date):
    if not start_date or not end_date:
        return {
            "total_days": 0,
            "completed_days": 0,
            "incomplete_started_days": 0,
            "not_started_days": 0,
            "next_open_date": None,
            "next_open_scan": None,
        }

    scans = {
        scan.scan_date: scan
        for scan in ComicVineDateScan.objects.filter(
            scan_kind=scan_kind,
            scan_date__gte=start_date,
            scan_date__lte=end_date,
        )
    }

    total_days = 0
    completed_days = 0
    incomplete_started_days = 0
    not_started_days = 0
    next_open_date = None
    next_open_scan = None

    current_date = start_date

    while current_date <= end_date:
        total_days += 1
        scan = scans.get(current_date)

        if scan is None:
            not_started_days += 1

            if next_open_date is None:
                next_open_date = current_date
                next_open_scan = None
        elif scan.completed:
            completed_days += 1
        else:
            incomplete_started_days += 1

            if next_open_date is None:
                next_open_date = current_date
                next_open_scan = scan

        current_date += timedelta(days=1)

    return {
        "total_days": total_days,
        "completed_days": completed_days,
        "incomplete_started_days": incomplete_started_days,
        "not_started_days": not_started_days,
        "next_open_date": next_open_date,
        "next_open_scan": next_open_scan,
    }


def get_backfill_status(*, current_import_start_date, oldest_date):
    newest_backfill_date = current_import_start_date - timedelta(days=1)

    existing_scans = {
        scan.scan_date: scan
        for scan in ComicVineDateScan.objects.filter(
            scan_kind=ComicVineDateScan.ISSUE_DATE_ADDED,
            scan_date__gte=oldest_date,
            scan_date__lte=newest_backfill_date,
        )
    }

    existing_days = len(existing_scans)
    completed_existing_days = sum(1 for scan in existing_scans.values() if scan.completed)
    incomplete_existing_days = existing_days - completed_existing_days

    contiguous_completed_days = 0
    next_unconfirmed_date = None
    next_unconfirmed_scan = None
    confirmed_complete_through = None

    current_date = newest_backfill_date

    while current_date >= oldest_date:
        scan = existing_scans.get(current_date)

        if scan and scan.completed:
            contiguous_completed_days += 1
            confirmed_complete_through = current_date
            current_date -= timedelta(days=1)
            continue

        next_unconfirmed_date = current_date
        next_unconfirmed_scan = scan
        break

    return {
        "existing_days": existing_days,
        "completed_existing_days": completed_existing_days,
        "incomplete_existing_days": incomplete_existing_days,
        "contiguous_completed_days": contiguous_completed_days,
        "confirmed_complete_through": confirmed_complete_through,
        "next_unconfirmed_date": next_unconfirmed_date,
        "next_unconfirmed_scan": next_unconfirmed_scan,
    }


def format_percent(part, total):
    if not total:
        return "0.0%"

    return f"{(part / total) * 100:.1f}%"


def format_value(value):
    if value is None:
        return "not set"

    return str(value)