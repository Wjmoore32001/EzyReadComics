import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from comics.comicvine.client import (
    create_comicvine_session,
    fetch_issues_page,
    get_comicvine_api_key,
)
from comics.comicvine.fields import ISSUE_LIST_FIELDS
from comics.comicvine.parsing import build_day_filter, clean_text
from comics.importers.issues import save_issue_list_data
from comics.importers.results import IssueListSaveResult
from comics.importers.scans import (
    advance_date_scan_after_page,
    get_default_current_import_start_date,
    get_next_incomplete_date_scan,
    get_or_initialize_default_sync_state,
    parse_scan_date,
    validate_date_window,
)
from comics.models import ComicVineDateScan


USER_AGENT = "EzyReadComics bulk_import_new_issues"


class Command(BaseCommand):
    help = (
        "Import newly added Comic Vine issues using completed date_added days only. "
        "This is the first current-data command to run on an empty database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            help=(
                "YYYY-MM-DD. Only used when ComicVineSyncState has no "
                "update_tracking_start_date yet. Defaults to yesterday."
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
            default=1,
            help="Maximum /issues/ pages to fetch this run. Defaults to 1.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=0.0,
            help="Seconds to wait between API pages when --max-pages is above 1.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and summarize what would happen without writing to the database.",
        )

    def handle(self, *args, **options):
        provided_start_date = parse_scan_date(options["start_date"])
        default_completed_day = get_default_current_import_start_date()
        end_date = parse_scan_date(options["end_date"]) or default_completed_day

        page_size = options["page_size"]
        max_pages = options["max_pages"]
        request_delay = options["request_delay"]
        dry_run = options["dry_run"]

        validate_command_options(
            page_size=page_size,
            max_pages=max_pages,
            request_delay=request_delay,
        )

        api_key = get_comicvine_api_key()

        sync_state, state_created, state_initialized = get_or_initialize_default_sync_state(
            start_date=provided_start_date,
            dry_run=dry_run,
        )

        start_date = sync_state.update_tracking_start_date
        validate_date_window(start_date, end_date)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Bulk import new Comic Vine issues"))
        self.stdout.write(f"Dry run: {dry_run}")
        self.stdout.write("")
        self.stdout.write("Completed-day scan:")
        self.stdout.write(f"  Today: {timezone.localdate()}")
        self.stdout.write(f"  Default completed day: {default_completed_day}")
        self.stdout.write(f"  Start date: {start_date}")
        self.stdout.write(f"  End date: {end_date}")
        self.stdout.write("")
        self.stdout.write(f"Page size: {page_size}")
        self.stdout.write(f"Max pages this run: {max_pages}")

        if state_created:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Sync state would be created."
                    if dry_run
                    else "Sync state created."
                )
            )

        if state_initialized:
            self.stdout.write(
                self.style.WARNING(
                    f"Current import start date would be set to {start_date}."
                    if dry_run
                    else f"Current import start date set to {start_date}."
                )
            )

        pages_processed = 0

        with create_comicvine_session(USER_AGENT) as session:
            while pages_processed < max_pages:
                scan, scan_created = get_next_incomplete_date_scan(
                    scan_kind=ComicVineDateScan.ISSUE_DATE_ADDED,
                    start_date=start_date,
                    end_date=end_date,
                    dry_run=dry_run,
                )

                if scan is None:
                    self.stdout.write("")
                    self.stdout.write(self.style.SUCCESS("No incomplete date_added scans remain."))
                    break

                if scan_created:
                    self.stdout.write("")
                    self.stdout.write(
                        self.style.WARNING(
                            f"Scan progress would be created for {scan.scan_date}."
                            if dry_run
                            else f"Scan progress created for {scan.scan_date}."
                        )
                    )

                starting_offset = scan.next_offset

                self.stdout.write("")
                self.stdout.write("=" * 80)
                self.stdout.write(f"Scanning date_added: {scan.scan_date}")
                self.stdout.write(f"Offset: {starting_offset}")
                self.stdout.write("=" * 80)

                response_data = fetch_issues_page(
                    session,
                    api_key,
                    filter_value=build_day_filter("date_added", scan.scan_date),
                    fields=ISSUE_LIST_FIELDS,
                    offset=starting_offset,
                    limit=page_size,
                    sort="date_added:asc",
                )

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
                    command=self,
                    item_results=item_results,
                    dry_run=dry_run,
                )

                print_batch_summary(
                    command=self,
                    save_result=save_result,
                    progress_result=progress_result,
                    dry_run=dry_run,
                )

                pages_processed += 1

                if progress_result.completed:
                    self.stdout.write("")
                    self.stdout.write(self.style.SUCCESS(f"Completed date: {scan.scan_date}"))
                else:
                    self.stdout.write("")
                    self.stdout.write(
                        self.style.WARNING(
                            f"Date not complete yet. Next offset: {progress_result.ending_offset}"
                        )
                    )

                if pages_processed < max_pages and request_delay > 0:
                    time.sleep(request_delay)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Run complete."))
        self.stdout.write(f"Pages processed: {pages_processed}")

        if pages_processed >= max_pages:
            if dry_run:
                self.stdout.write("Dry run only. No database changes were saved.")
            else:
                self.stdout.write("Run again to continue from the saved date/offset.")


def validate_command_options(*, page_size, max_pages, request_delay):
    if page_size < 1:
        raise CommandError("--page-size must be at least 1.")

    if page_size > 100:
        raise CommandError("--page-size cannot be above 100.")

    if max_pages < 1:
        raise CommandError("--max-pages must be at least 1.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")


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

    remote_volume = remote_issue.get("volume") or {}
    volume_name = clean_text(remote_volume.get("name")) or "Unknown volume"
    volume_id = remote_volume.get("id") or "unknown-volume-id"

    return (
        f"{volume_name} #{issue_number} — {issue_title} "
        f"(issue {issue_id}, volume {volume_id}, store {store_date}, added {date_added})"
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