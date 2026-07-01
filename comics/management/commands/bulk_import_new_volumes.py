import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, transaction
from requests.exceptions import RequestException

from comics.comicvine.client import (
    ComicVineAPIError,
    create_comicvine_session,
    fetch_volumes_page,
    get_comicvine_api_key,
)
from comics.comicvine.fields import VOLUME_LIST_FIELDS
from comics.comicvine.parsing import build_day_filter, clean_text
from comics.importers.scans import (
    DEFAULT_SYNC_STATE_NAME,
    advance_date_scan_after_page,
    get_default_current_import_start_date,
    get_next_incomplete_date_scan,
    parse_scan_date,
    validate_date_window,
)
from comics.importers.volumes import save_volume_list_data
from comics.models import ComicVineDateScan, ComicVineSyncState


USER_AGENT = "EzyReadComics bulk_import_new_volumes"

DEFAULT_API_ERROR_RETRY_DELAY = 90 * 60

SCAN_PHASES = [
    {
        "title": "Volumes added on Comic Vine",
        "scan_kind": ComicVineDateScan.VOLUME_DATE_ADDED,
        "comicvine_field": "date_added",
    },
    {
        "title": "Volumes updated on Comic Vine",
        "scan_kind": ComicVineDateScan.VOLUME_DATE_LAST_UPDATED,
        "comicvine_field": "date_last_updated",
    },
]


class Command(BaseCommand):
    help = (
        "Import current Comic Vine volumes using completed date_added and "
        "date_last_updated days. This does not call detail endpoints or hydrate credits."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            help=(
                "YYYY-MM-DD. Defaults to ComicVineSyncState.update_tracking_start_date."
            ),
        )

        parser.add_argument(
            "--end-date",
            help="YYYY-MM-DD. Defaults to yesterday so only completed days are scanned.",
        )

        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Comic Vine page size. Defaults to 100. Maximum is 100.",
        )

        parser.add_argument(
            "--max-pages",
            type=int,
            default=None,
            help=(
                "Optional maximum successful pages to fetch for each scan type this run. "
                "If omitted during a real run, the command keeps going until all "
                "selected completed-day volume scans are caught up. "
                "Dry runs default to 1 page per scan type."
            ),
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=3.0,
            help="Seconds to wait between successful API pages/phases. Defaults to 3.",
        )

        parser.add_argument(
            "--api-error-retry-delay",
            type=float,
            default=DEFAULT_API_ERROR_RETRY_DELAY,
            help=(
                "Seconds to pause after a Comic Vine/API/web error before retrying. "
                "Defaults to 5400 seconds, which is 90 minutes."
            ),
        )

        parser.add_argument(
            "--stop-on-api-error",
            action="store_true",
            help=(
                "Stop immediately on a Comic Vine/API/web error instead of pausing "
                "and retrying. Dry runs always behave this way."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and summarize what would happen without writing to the database.",
        )

    def handle(self, *args, **options):
        sync_state = get_existing_sync_state()

        default_start_date = sync_state.update_tracking_start_date
        default_end_date = get_default_current_import_start_date()

        start_date = parse_scan_date(options["start_date"]) or default_start_date
        end_date = parse_scan_date(options["end_date"]) or default_end_date

        page_size = options["page_size"]
        max_pages = options["max_pages"]
        request_delay = options["request_delay"]
        api_error_retry_delay = options["api_error_retry_delay"]
        dry_run = options["dry_run"]

        # Dry runs should never trap you in a 90-minute retry pause.
        stop_on_api_error = options["stop_on_api_error"] or dry_run

        if dry_run and max_pages is None:
            max_pages = 1

        validate_command_options(
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
            max_pages=max_pages,
            request_delay=request_delay,
            api_error_retry_delay=api_error_retry_delay,
        )

        api_key = get_comicvine_api_key()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Bulk import current Comic Vine volumes"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")
        self.stdout.write(f"Import date range: {start_date} through {end_date}")
        self.stdout.write(f"Page size: {page_size}")

        if max_pages is None:
            self.stdout.write("Page cap per phase: no limit")
        else:
            self.stdout.write(f"Page cap per phase: {max_pages}")

        if stop_on_api_error:
            self.stdout.write("API/web error handling: stop immediately")
        else:
            self.stdout.write(
                f"API/web error handling: pause {api_error_retry_delay} seconds, then retry"
            )

        total_pages_processed = 0
        total_api_errors_seen = 0
        total_api_error_retries = 0
        stopped_by_api_error = False
        phase_results = []

        with create_comicvine_session(USER_AGENT) as session:
            for phase_index, phase in enumerate(SCAN_PHASES, start=1):
                if phase_index > 1:
                    sleep_if_needed(request_delay)

                self.stdout.write("")
                self.stdout.write("#" * 80)
                self.stdout.write(
                    f"Phase {phase_index} of {len(SCAN_PHASES)}: {phase['title']}"
                )
                self.stdout.write("#" * 80)

                phase_result = run_scan_phase(
                    command=self,
                    session=session,
                    api_key=api_key,
                    phase=phase,
                    start_date=start_date,
                    end_date=end_date,
                    page_size=page_size,
                    max_pages=max_pages,
                    request_delay=request_delay,
                    api_error_retry_delay=api_error_retry_delay,
                    stop_on_api_error=stop_on_api_error,
                    dry_run=dry_run,
                )

                phase_results.append(phase_result)
                total_pages_processed += phase_result["pages_processed"]
                total_api_errors_seen += phase_result["api_errors_seen"]
                total_api_error_retries += phase_result["api_error_retries"]

                if phase_result["stopped_by_api_error"]:
                    stopped_by_api_error = True
                    break

        all_phases_caught_up = (
            len(phase_results) == len(SCAN_PHASES)
            and all(phase_result["caught_up"] for phase_result in phase_results)
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Run complete."))
        self.stdout.write(f"Total pages processed: {total_pages_processed}")
        self.stdout.write(f"API/web errors seen: {total_api_errors_seen}")
        self.stdout.write(f"API/web error retries: {total_api_error_retries}")

        if dry_run:
            self.stdout.write("Dry run only. No database changes were saved.")
        elif stopped_by_api_error:
            self.stdout.write("Stopped early because Comic Vine returned an API/web error.")
        elif all_phases_caught_up:
            self.stdout.write("Volume import caught up through the selected date range.")
        else:
            self.stdout.write(
                "Stopped at the page cap before all volume scans were confirmed complete. "
                "Run again to continue."
            )


def get_existing_sync_state():
    sync_state = ComicVineSyncState.objects.filter(
        name=DEFAULT_SYNC_STATE_NAME,
    ).first()

    if not sync_state or not sync_state.update_tracking_start_date:
        raise CommandError(
            "ComicVineSyncState.update_tracking_start_date is missing. "
            "Run bulk_import_new_issues first so volume importing knows where current importing starts."
        )

    return sync_state


def run_scan_phase(
    *,
    command,
    session,
    api_key,
    phase,
    start_date,
    end_date,
    page_size,
    max_pages,
    request_delay,
    api_error_retry_delay,
    stop_on_api_error,
    dry_run,
):
    pages_processed = 0
    caught_up = False
    stopped_by_api_error = False
    api_errors_seen = 0
    api_error_retries = 0
    scan_kind = phase["scan_kind"]
    comicvine_field = phase["comicvine_field"]

    while max_pages is None or pages_processed < max_pages:
        # Important for long retry sleeps.
        # Neon/Postgres may close the idle SSL connection while the command is waiting.
        # This forces Django to open a fresh connection before the next ORM query.
        close_old_connections()

        scan, scan_created = get_next_incomplete_date_scan(
            scan_kind=scan_kind,
            start_date=start_date,
            end_date=end_date,
            dry_run=dry_run,
        )

        if scan is None:
            caught_up = True
            command.stdout.write("")
            command.stdout.write(
                command.style.SUCCESS(
                    f"No incomplete volume {comicvine_field} scans remain."
                )
            )
            break

        if scan_created:
            command.stdout.write("")
            command.stdout.write(
                command.style.WARNING(
                    f"Volume progress would be created for {comicvine_field} {scan.scan_date}."
                    if dry_run
                    else f"Volume progress created for {comicvine_field} {scan.scan_date}."
                )
            )

        starting_offset = scan.next_offset

        command.stdout.write("")
        command.stdout.write("=" * 80)
        command.stdout.write(f"Scanning volume {comicvine_field}: {scan.scan_date}")
        command.stdout.write(f"Offset: {starting_offset}")
        command.stdout.write("=" * 80)

        try:
            response_data = fetch_volumes_page(
                session,
                api_key,
                filter_value=build_day_filter(comicvine_field, scan.scan_date),
                fields=VOLUME_LIST_FIELDS,
                offset=starting_offset,
                limit=page_size,
                sort=f"{comicvine_field}:asc",
            )
        except (ComicVineAPIError, RequestException) as error:
            api_errors_seen += 1

            command.stdout.write("")
            command.stdout.write(command.style.ERROR("Comic Vine/API/web error."))
            command.stdout.write(str(error))
            command.stdout.write("")

            if stop_on_api_error:
                stopped_by_api_error = True
                command.stdout.write(
                    "Progress from completed pages was saved. "
                    "The current page was not marked complete. "
                    "Run this command again later to continue."
                )
                break

            api_error_retries += 1

            command.stdout.write(
                "Progress from completed pages was saved. "
                "The current page was not marked complete."
            )
            command.stdout.write(
                f"Pausing for {format_seconds(api_error_retry_delay)} before retrying "
                f"{comicvine_field} {scan.scan_date} at offset {starting_offset}."
            )

            sleep_if_needed(api_error_retry_delay)

            command.stdout.write("")
            command.stdout.write(
                command.style.WARNING(
                    "Retrying after API/web error. Press Ctrl+C to stop the command."
                )
            )

            continue

        remote_volumes = response_data.get("results") or []
        total_results = int(response_data.get("number_of_total_results") or 0)
        page_results = len(remote_volumes)

        if dry_run:
            save_result, item_results = process_volume_page_dry_run(remote_volumes)
            progress_result = advance_date_scan_after_page(
                scan=scan,
                starting_offset=starting_offset,
                total_results=total_results,
                page_results=page_results,
                dry_run=True,
            )
        else:
            with transaction.atomic():
                save_result, item_results = process_volume_page(remote_volumes)
                progress_result = advance_date_scan_after_page(
                    scan=scan,
                    starting_offset=starting_offset,
                    total_results=total_results,
                    page_results=page_results,
                    dry_run=False,
                )

        print_volume_items(
            command=command,
            item_results=item_results,
            dry_run=dry_run,
        )

        print_batch_summary(
            command=command,
            save_result=save_result,
            progress_result=progress_result,
            dry_run=dry_run,
        )

        pages_processed += 1

        if progress_result.completed:
            command.stdout.write("")
            command.stdout.write(
                command.style.SUCCESS(
                    f"Completed volume {comicvine_field}: {scan.scan_date}"
                )
            )
        else:
            command.stdout.write("")
            command.stdout.write(
                command.style.WARNING(
                    f"Volume {comicvine_field} date not complete yet. "
                    f"Next offset: {progress_result.ending_offset}"
                )
            )

        sleep_if_needed(request_delay)

    return {
        "pages_processed": pages_processed,
        "caught_up": caught_up,
        "stopped_by_api_error": stopped_by_api_error,
        "api_errors_seen": api_errors_seen,
        "api_error_retries": api_error_retries,
    }


def process_volume_page(remote_volumes):
    save_result = build_empty_result()
    item_results = []

    for remote_volume in remote_volumes:
        item_result = save_single_volume(
            remote_volume,
            dry_run=False,
        )
        record_single_volume_result(save_result, item_result)
        item_results.append(item_result)

    return save_result, item_results


def process_volume_page_dry_run(remote_volumes):
    save_result = build_empty_result()
    item_results = []

    for remote_volume in remote_volumes:
        item_result = save_single_volume(
            remote_volume,
            dry_run=True,
        )
        record_single_volume_result(save_result, item_result)
        item_results.append(item_result)

    return save_result, item_results


def save_single_volume(remote_volume, *, dry_run):
    remote_volume_id = remote_volume.get("id")

    if not remote_volume_id:
        return {
            "action": "skipped_missing_id",
            "remote_volume": remote_volume,
            "update_fields": [],
        }

    action, _volume, update_fields = save_volume_list_data(
        remote_volume,
        overwrite_existing=True,
        dry_run=dry_run,
    )

    if action == "created":
        item_action = "created"
    elif action == "updated":
        item_action = "updated"
    elif action == "unchanged":
        item_action = "refreshed"
    else:
        item_action = action

    return {
        "action": item_action,
        "remote_volume": remote_volume,
        "update_fields": update_fields,
    }


def build_empty_result():
    return {
        "volumes_seen": 0,
        "volumes_created": 0,
        "volumes_updated": 0,
        "volumes_refreshed_no_changes": 0,
        "volumes_skipped_missing_id": 0,
        "volumes_skipped_other": 0,
    }


def record_single_volume_result(save_result, item_result):
    save_result["volumes_seen"] += 1

    action = item_result["action"]

    if action == "created":
        save_result["volumes_created"] += 1
    elif action == "updated":
        save_result["volumes_updated"] += 1
    elif action == "refreshed":
        save_result["volumes_refreshed_no_changes"] += 1
    elif action == "skipped_missing_id":
        save_result["volumes_skipped_missing_id"] += 1
    else:
        save_result["volumes_skipped_other"] += 1


def print_volume_items(*, command, item_results, dry_run):
    command.stdout.write("")
    command.stdout.write("Volumes returned:")

    if not item_results:
        command.stdout.write("  None")
        return

    for item_result in item_results:
        action = format_action(item_result["action"], dry_run=dry_run)
        remote_volume = item_result["remote_volume"]
        command.stdout.write(f"  {action} {format_volume_line(remote_volume)}")


def format_action(action, *, dry_run):
    if dry_run:
        if action == "created":
            return "[WOULD CREATE]"
        if action == "updated":
            return "[WOULD UPDATE]"
        if action == "refreshed":
            return "[WOULD REFRESH]"
        if action == "skipped_missing_id":
            return "[SKIP MISSING ID]"
        return "[WOULD SKIP]"

    if action == "created":
        return "[CREATED]"
    if action == "updated":
        return "[UPDATED]"
    if action == "refreshed":
        return "[REFRESHED]"
    if action == "skipped_missing_id":
        return "[SKIP MISSING ID]"
    return "[SKIPPED]"


def format_volume_line(remote_volume):
    volume_id = remote_volume.get("id") or "unknown-id"
    volume_name = clean_text(remote_volume.get("name")) or "Unknown volume"
    publisher = clean_text((remote_volume.get("publisher") or {}).get("name"))
    start_year = clean_text(remote_volume.get("start_year"))
    count_of_issues = remote_volume.get("count_of_issues")
    date_added = clean_text(remote_volume.get("date_added")) or "unknown date_added"
    date_last_updated = (
        clean_text(remote_volume.get("date_last_updated"))
        or "unknown date_last_updated"
    )

    details = []

    if publisher:
        details.append(f"publisher {publisher}")

    if start_year:
        details.append(f"start {start_year}")

    if count_of_issues is not None:
        details.append(f"{count_of_issues} issues")

    details.append(f"added {date_added}")
    details.append(f"updated {date_last_updated}")

    details_text = ", ".join(details)

    return f"{volume_name} (volume {volume_id}, {details_text})"


def print_batch_summary(*, command, save_result, progress_result, dry_run):
    prefix = "Would " if dry_run else ""

    command.stdout.write("")
    command.stdout.write("Batch summary:")
    command.stdout.write(f"  Remote total for this date: {progress_result.total_results}")
    command.stdout.write(f"  Remote volumes in this page: {progress_result.page_results}")
    command.stdout.write(f"  Starting offset: {progress_result.starting_offset}")
    command.stdout.write(f"  Ending offset: {progress_result.ending_offset}")
    command.stdout.write("")
    command.stdout.write(f"  Volumes returned: {save_result['volumes_seen']}")
    command.stdout.write(f"  {prefix}volumes created: {save_result['volumes_created']}")
    command.stdout.write(f"  {prefix}volumes updated: {save_result['volumes_updated']}")
    command.stdout.write(
        f"  {prefix}volumes refreshed with no data changes: "
        f"{save_result['volumes_refreshed_no_changes']}"
    )
    command.stdout.write(
        f"  Remote volumes skipped because ID was missing: "
        f"{save_result['volumes_skipped_missing_id']}"
    )

    if save_result["volumes_skipped_other"]:
        command.stdout.write(f"  Other skipped volumes: {save_result['volumes_skipped_other']}")


def validate_command_options(
    *,
    start_date,
    end_date,
    page_size,
    max_pages,
    request_delay,
    api_error_retry_delay,
):
    if start_date is None:
        raise CommandError("--start-date is required.")

    if end_date is None:
        raise CommandError("--end-date is required.")

    try:
        validate_date_window(start_date, end_date)
    except ValueError as error:
        raise CommandError(str(error)) from error

    if page_size < 1:
        raise CommandError("--page-size must be at least 1.")

    if page_size > 100:
        raise CommandError("--page-size cannot be above 100.")

    if max_pages is not None and max_pages < 1:
        raise CommandError("--max-pages must be at least 1 when provided.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")

    if api_error_retry_delay < 0:
        raise CommandError("--api-error-retry-delay cannot be negative.")


def format_seconds(seconds):
    seconds = int(seconds)
    minutes = seconds // 60

    if seconds == DEFAULT_API_ERROR_RETRY_DELAY:
        return "90 minutes"

    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"

    if seconds % 60 == 0:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    return f"{seconds} seconds"


def sleep_if_needed(delay):
    if delay > 0:
        time.sleep(delay)

    close_old_connections()