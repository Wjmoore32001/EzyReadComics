from datetime import date, timedelta
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from requests.exceptions import RequestException

from comics.comicvine.client import (
    ComicVineAPIError,
    create_comicvine_session,
    fetch_issues_page,
    get_comicvine_api_key,
)
from comics.comicvine.fields import ISSUE_LIST_FIELDS
from comics.comicvine.parsing import build_day_filter, clean_text
from comics.importers.issues import save_issue_list_data
from comics.importers.results import IssueListSaveResult
from comics.importers.scans import (
    DEFAULT_SYNC_STATE_NAME,
    advance_date_scan_after_page,
    parse_scan_date,
)
from comics.models import ComicVineDateScan, ComicVineSyncState


USER_AGENT = "EzyReadComics bulk_backfill_old_issues"

DEFAULT_OLDEST_BACKFILL_DATE = date(1930, 1, 1)
DEFAULT_API_ERROR_RETRY_DELAY = 90 * 60


class Command(BaseCommand):
    help = (
        "Backfill older Comic Vine issues using completed historical date_added days. "
        "This does not call detail endpoints or hydrate credits."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--oldest-date",
            help=(
                "YYYY-MM-DD. Oldest date_added day to backfill. "
                "Defaults to 1930-01-01."
            ),
        )

        parser.add_argument(
            "--newest-date",
            help=(
                "YYYY-MM-DD. Newest date_added day to backfill. "
                "Defaults to the day before ComicVineSyncState.update_tracking_start_date."
            ),
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
                "Optional maximum pages to fetch this run. "
                "If omitted during a real run, the command keeps going until the "
                "backfill range is caught up. "
                "Dry runs default to 1 page."
            ),
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=3.0,
            help="Seconds to wait between successful API pages. Defaults to 3.",
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

        current_import_start_date = sync_state.update_tracking_start_date
        default_newest_date = current_import_start_date - timedelta(days=1)

        oldest_date = parse_scan_date(options["oldest_date"]) or DEFAULT_OLDEST_BACKFILL_DATE
        newest_date = parse_scan_date(options["newest_date"]) or default_newest_date

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
            oldest_date=oldest_date,
            newest_date=newest_date,
            current_import_start_date=current_import_start_date,
            page_size=page_size,
            max_pages=max_pages,
            request_delay=request_delay,
            api_error_retry_delay=api_error_retry_delay,
        )

        api_key = get_comicvine_api_key()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Bulk backfill older Comic Vine issues"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")
        self.stdout.write(f"Backfill date range: {oldest_date} through {newest_date}")
        self.stdout.write(f"Current import starts at: {current_import_start_date}")
        self.stdout.write(f"Page size: {page_size}")

        if max_pages is None:
            self.stdout.write("Page cap: no limit")
        else:
            self.stdout.write(f"Page cap: {max_pages}")

        if stop_on_api_error:
            self.stdout.write("API/web error handling: stop immediately")
        else:
            self.stdout.write(
                f"API/web error handling: pause {api_error_retry_delay} seconds, then retry"
            )

        with create_comicvine_session(USER_AGENT) as session:
            run_result = run_backfill_scan(
                command=self,
                session=session,
                api_key=api_key,
                oldest_date=oldest_date,
                newest_date=newest_date,
                page_size=page_size,
                max_pages=max_pages,
                request_delay=request_delay,
                api_error_retry_delay=api_error_retry_delay,
                stop_on_api_error=stop_on_api_error,
                dry_run=dry_run,
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Run complete."))
        self.stdout.write(f"Pages processed: {run_result['pages_processed']}")
        self.stdout.write(f"API/web errors seen: {run_result['api_errors_seen']}")
        self.stdout.write(f"API/web error retries: {run_result['api_error_retries']}")

        if dry_run:
            self.stdout.write("Dry run only. No database changes were saved.")
        elif run_result["stopped_by_api_error"]:
            self.stdout.write("Stopped early because Comic Vine returned an API/web error.")
        elif run_result["caught_up"]:
            self.stdout.write("Backfill caught up through the selected date range.")
        else:
            self.stdout.write(
                "Stopped at the page cap before the backfill range was confirmed complete. "
                "Run again to continue."
            )


def get_existing_sync_state():
    sync_state = ComicVineSyncState.objects.filter(
        name=DEFAULT_SYNC_STATE_NAME,
    ).first()

    if not sync_state or not sync_state.update_tracking_start_date:
        raise CommandError(
            "ComicVineSyncState.update_tracking_start_date is missing. "
            "Run bulk_import_new_issues first so backfill knows where current importing starts."
        )

    return sync_state


def run_backfill_scan(
    *,
    command,
    session,
    api_key,
    oldest_date,
    newest_date,
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

    while max_pages is None or pages_processed < max_pages:
        scan, scan_created = get_next_backfill_date_scan(
            scan_kind=ComicVineDateScan.ISSUE_DATE_ADDED,
            oldest_date=oldest_date,
            newest_date=newest_date,
            dry_run=dry_run,
        )

        if scan is None:
            caught_up = True
            command.stdout.write("")
            command.stdout.write(
                command.style.SUCCESS("No incomplete backfill date_added scans remain.")
            )
            break

        if scan_created:
            command.stdout.write("")
            command.stdout.write(
                command.style.WARNING(
                    f"Backfill progress would be created for date_added {scan.scan_date}."
                    if dry_run
                    else f"Backfill progress created for date_added {scan.scan_date}."
                )
            )

        starting_offset = scan.next_offset

        command.stdout.write("")
        command.stdout.write("=" * 80)
        command.stdout.write(f"Backfilling date_added: {scan.scan_date}")
        command.stdout.write(f"Offset: {starting_offset}")
        command.stdout.write("=" * 80)

        try:
            response_data = fetch_issues_page(
                session,
                api_key,
                filter_value=build_day_filter("date_added", scan.scan_date),
                fields=ISSUE_LIST_FIELDS,
                offset=starting_offset,
                limit=page_size,
                sort="date_added:asc",
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
                f"date_added {scan.scan_date} at offset {starting_offset}."
            )

            sleep_if_needed(api_error_retry_delay)

            command.stdout.write("")
            command.stdout.write(
                command.style.WARNING(
                    "Retrying after API/web error. Press Ctrl+C to stop the command."
                )
            )

            continue

        remote_issues = response_data.get("results") or []
        total_results = int(response_data.get("number_of_total_results") or 0)
        page_results = len(remote_issues)

        if dry_run:
            save_result, item_results = process_issue_page_dry_run(remote_issues)
            progress_result = advance_date_scan_after_page(
                scan=scan,
                starting_offset=starting_offset,
                total_results=total_results,
                page_results=page_results,
                dry_run=True,
            )
        else:
            with transaction.atomic():
                save_result, item_results = process_issue_page(remote_issues)
                progress_result = advance_date_scan_after_page(
                    scan=scan,
                    starting_offset=starting_offset,
                    total_results=total_results,
                    page_results=page_results,
                    dry_run=False,
                )

        print_issue_items(
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
                command.style.SUCCESS(f"Completed date_added: {scan.scan_date}")
            )
        else:
            command.stdout.write("")
            command.stdout.write(
                command.style.WARNING(
                    f"date_added date not complete yet. "
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


def get_next_backfill_date_scan(*, scan_kind, oldest_date, newest_date, dry_run=False):
    current_date = newest_date

    while current_date >= oldest_date:
        scan = ComicVineDateScan.objects.filter(
            scan_kind=scan_kind,
            scan_date=current_date,
        ).first()

        if scan:
            if not scan.completed:
                return scan, False

            current_date -= timedelta(days=1)
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

        current_date -= timedelta(days=1)

    return None, False


def validate_command_options(
    *,
    oldest_date,
    newest_date,
    current_import_start_date,
    page_size,
    max_pages,
    request_delay,
    api_error_retry_delay,
):
    if oldest_date is None:
        raise CommandError("--oldest-date is required.")

    if newest_date is None:
        raise CommandError("--newest-date is required.")

    if oldest_date > newest_date:
        raise CommandError("--oldest-date cannot be later than --newest-date.")

    if newest_date >= current_import_start_date:
        raise CommandError(
            "--newest-date must be earlier than the current import start date. "
            "This prevents backfill from overlapping the current import command."
        )

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


def process_issue_page(remote_issues):
    save_result = IssueListSaveResult()
    item_results = []

    for remote_issue in remote_issues:
        item_result = save_single_issue(remote_issue, dry_run=False)
        record_single_issue_result(save_result, item_result)
        item_results.append(item_result)

    return save_result, item_results


def process_issue_page_dry_run(remote_issues):
    save_result = IssueListSaveResult()
    item_results = []

    for remote_issue in remote_issues:
        item_result = save_single_issue(remote_issue, dry_run=True)
        record_single_issue_result(save_result, item_result)
        item_results.append(item_result)

    return save_result, item_results


def save_single_issue(remote_issue, *, dry_run):
    (
        action,
        _issue,
        update_fields,
        volume_created,
        volume_update_fields,
        image_result,
    ) = save_issue_list_data(
        remote_issue,
        overwrite_existing=True,
        create_missing=True,
        dry_run=dry_run,
    )

    return {
        "action": action,
        "remote_issue": remote_issue,
        "update_fields": update_fields,
        "volume_created": volume_created,
        "volume_update_fields": volume_update_fields,
        "image_result": image_result,
    }


def record_single_issue_result(save_result, item_result):
    save_result.issues_seen += 1

    action = item_result["action"]
    update_fields = item_result["update_fields"]
    volume_created = item_result["volume_created"]
    volume_update_fields = item_result["volume_update_fields"]
    image_result = item_result["image_result"]

    if volume_created:
        save_result.volumes_created += 1

    if volume_update_fields:
        save_result.volumes_updated += 1

    save_result.record_relationship_result(image_result)

    if action == "created":
        save_result.issues_created += 1
        save_result.record_issue_fields(update_fields)
    elif action == "updated":
        save_result.issues_updated += 1
        save_result.record_issue_fields(update_fields)
    elif action == "unchanged":
        save_result.issues_unchanged += 1
    else:
        save_result.issues_skipped += 1


def print_issue_items(*, command, item_results, dry_run):
    command.stdout.write("")
    command.stdout.write("Issues returned:")

    if not item_results:
        command.stdout.write("  None")
        return

    for item_result in item_results:
        action = format_action(item_result["action"], dry_run=dry_run)
        remote_issue = item_result["remote_issue"]
        command.stdout.write(f"  {action} {format_issue_line(remote_issue)}")


def format_action(action, *, dry_run):
    if dry_run:
        if action == "created":
            return "[WOULD CREATE]"
        if action == "updated":
            return "[WOULD UPDATE]"
        if action == "unchanged":
            return "[WOULD KEEP]"
        return "[WOULD SKIP]"

    if action == "created":
        return "[CREATED]"
    if action == "updated":
        return "[UPDATED]"
    if action == "unchanged":
        return "[UNCHANGED]"
    return "[SKIPPED]"


def format_issue_line(remote_issue):
    issue_id = remote_issue.get("id") or "unknown-id"
    issue_number = clean_text(remote_issue.get("issue_number")) or "?"
    issue_title = clean_text(remote_issue.get("name")) or "No title"
    store_date = clean_text(remote_issue.get("store_date")) or "unknown store date"
    date_added = clean_text(remote_issue.get("date_added")) or "unknown date_added"
    date_last_updated = (
        clean_text(remote_issue.get("date_last_updated")) or "unknown date_last_updated"
    )

    remote_volume = remote_issue.get("volume") or {}
    volume_name = clean_text(remote_volume.get("name")) or "Unknown volume"
    volume_id = remote_volume.get("id") or "unknown-volume-id"

    return (
        f"{volume_name} #{issue_number} — {issue_title} "
        f"(issue {issue_id}, volume {volume_id}, store {store_date}, "
        f"added {date_added}, updated {date_last_updated})"
    )


def print_batch_summary(*, command, save_result, progress_result, dry_run):
    prefix = "Would " if dry_run else ""

    command.stdout.write("")
    command.stdout.write("Batch summary:")
    command.stdout.write(f"  Remote total for this date: {progress_result.total_results}")
    command.stdout.write(f"  Remote issues in this page: {progress_result.page_results}")
    command.stdout.write(f"  Starting offset: {progress_result.starting_offset}")
    command.stdout.write(f"  Ending offset: {progress_result.ending_offset}")
    command.stdout.write("")
    command.stdout.write(f"  {prefix}issues created: {save_result.issues_created}")
    command.stdout.write(f"  {prefix}issues updated: {save_result.issues_updated}")
    command.stdout.write(f"  {prefix}issues unchanged: {save_result.issues_unchanged}")
    command.stdout.write(f"  {prefix}issues skipped: {save_result.issues_skipped}")
    command.stdout.write(f"  {prefix}minimal volumes created: {save_result.volumes_created}")
    command.stdout.write(f"  {prefix}minimal volumes updated: {save_result.volumes_updated}")
    command.stdout.write(f"  {prefix}associated images created: {save_result.associated_images_created}")
    command.stdout.write(f"  {prefix}associated images deleted: {save_result.associated_images_deleted}")


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