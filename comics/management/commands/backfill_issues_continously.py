import os
from dataclasses import dataclass
from datetime import timedelta

import requests
from django.core.management.base import BaseCommand, CommandError

from comics.management.commands.backfill_issues import (
    USER_AGENT,
    get_next_incomplete_backfill_date_scan,
    get_sync_state,
    print_batch_summary,
    process_one_issue_backfill_batch,
)
from comics.models import ComicVineDateScan


CANDIDATE_LIMIT = 100

MODE_ONE_DAY = "one-day"
MODE_CONTINUOUS = "continuous"


@dataclass
class RunnerSummary:
    batches_fetched: int = 0
    candidates_checked: int = 0
    issues_created: int = 0
    existing_issues_skipped: int = 0
    missing_data_skipped: int = 0
    minimal_volumes_needed: int = 0
    dates_completed: int = 0


class Command(BaseCommand):
    help = (
        "Runs Comic Vine issue backfill batches repeatedly. "
        "Can finish one incomplete date_added day or keep moving backward continuously."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=[MODE_ONE_DAY, MODE_CONTINUOUS],
            help=(
                "Run mode. Use 'one-day' to finish/start the closest incomplete day. "
                "Use 'continuous' to keep moving backward through days until stopped."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Preview one backfill batch without saving anything. "
                "Dry run does not loop because offsets are not saved."
            ),
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        mode = options["mode"] or ask_for_mode(command=self)
        dry_run = options["dry_run"]

        sync_state = get_sync_state()
        update_tracking_start_date = sync_state.update_tracking_start_date
        newest_backfill_scan_date = update_tracking_start_date - timedelta(days=1)

        summary = RunnerSummary()
        volume_cache = {}

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine issue backfill runner"))
        self.stdout.write("Uses the existing backfill_issues batch logic.")
        self.stdout.write("Scans Comic Vine issues by date_added.")
        self.stdout.write("Existing issues are skipped by Comic Vine issue ID.")
        self.stdout.write(f"Update tracking start date: {update_tracking_start_date.isoformat()}")
        self.stdout.write(f"Newest backfill scan date: {newest_backfill_scan_date.isoformat()}")
        self.stdout.write(f"Candidate batch size per API call: {CANDIDATE_LIMIT}")
        self.stdout.write(f"Mode: {mode}")

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry run enabled. Only one batch will be previewed because offsets are not saved."
                )
            )

        with requests.Session() as session:
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                }
            )

            try:
                if mode == MODE_ONE_DAY:
                    run_one_day(
                        command=self,
                        session=session,
                        api_key=api_key,
                        newest_backfill_scan_date=newest_backfill_scan_date,
                        volume_cache=volume_cache,
                        dry_run=dry_run,
                        summary=summary,
                    )
                else:
                    run_continuously(
                        command=self,
                        session=session,
                        api_key=api_key,
                        newest_backfill_scan_date=newest_backfill_scan_date,
                        volume_cache=volume_cache,
                        dry_run=dry_run,
                        summary=summary,
                    )
            except KeyboardInterrupt:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Backfill runner stopped by user."))
            except CommandError as error:
                if is_rate_limit_error(error):
                    self.stdout.write("")
                    self.stdout.write(
                        self.style.WARNING(
                            "Backfill runner stopped because Comic Vine returned a rate or velocity limit."
                        )
                    )
                    self.stdout.write(str(error))
                else:
                    raise

        print_runner_summary(command=self, summary=summary)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def ask_for_mode(command):
    command.stdout.write("")
    command.stdout.write("What do you want to do?")
    command.stdout.write("1. Finish/start one date_added day")
    command.stdout.write("   Uses the closest incomplete backfill day. If none exists, starts the next older day.")
    command.stdout.write("2. Run continuously")
    command.stdout.write("   Keeps finishing days and moving backward until Comic Vine rate-limits it or you stop it.")
    command.stdout.write("")

    while True:
        choice = input("Choose 1 or 2: ").strip()

        if choice == "1":
            return MODE_ONE_DAY

        if choice == "2":
            return MODE_CONTINUOUS

        command.stdout.write("Invalid choice. Enter 1 or 2.")
        command.stdout.write("")


def run_one_day(
    command,
    session,
    api_key,
    newest_backfill_scan_date,
    volume_cache,
    dry_run,
    summary,
):
    scan = get_next_incomplete_backfill_date_scan(
        newest_backfill_scan_date=newest_backfill_scan_date,
        dry_run=dry_run,
    )
    target_scan_date = scan.scan_date

    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("One-day mode selected"))
    command.stdout.write(f"Target date_added day: {target_scan_date}")
    command.stdout.write(f"Starting offset: {scan.next_offset}")

    while True:
        result = process_runner_batch(
            command=command,
            session=session,
            api_key=api_key,
            scan=scan,
            volume_cache=volume_cache,
            dry_run=dry_run,
            summary=summary,
        )

        if dry_run:
            command.stdout.write("")
            command.stdout.write(
                "Dry run stopped after one preview batch. Run without --dry-run to actually finish the day."
            )
            return

        if result.date_completed:
            command.stdout.write("")
            command.stdout.write(
                command.style.SUCCESS(
                    f"Finished date_added day: {target_scan_date}"
                )
            )
            return

        scan.refresh_from_db()


def run_continuously(
    command,
    session,
    api_key,
    newest_backfill_scan_date,
    volume_cache,
    dry_run,
    summary,
):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Continuous mode selected"))
    command.stdout.write(
        "The runner will keep finishing date_added days and moving backward until stopped."
    )

    while True:
        scan = get_next_incomplete_backfill_date_scan(
            newest_backfill_scan_date=newest_backfill_scan_date,
            dry_run=dry_run,
        )

        result = process_runner_batch(
            command=command,
            session=session,
            api_key=api_key,
            scan=scan,
            volume_cache=volume_cache,
            dry_run=dry_run,
            summary=summary,
        )

        if dry_run:
            command.stdout.write("")
            command.stdout.write(
                "Dry run stopped after one preview batch. Run without --dry-run to continue."
            )
            return

        if result.date_completed:
            command.stdout.write("")
            command.stdout.write(
                command.style.SUCCESS(
                    f"Finished date_added day: {result.scan_date}. Moving to the previous incomplete day."
                )
            )


def process_runner_batch(
    command,
    session,
    api_key,
    scan,
    volume_cache,
    dry_run,
    summary,
):
    batch_number = summary.batches_fetched + 1

    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS(f"Backfill runner batch {batch_number}"))
    command.stdout.write(f"Scan date_added day: {scan.scan_date}")
    command.stdout.write(f"Starting offset for this date_added day: {scan.next_offset}")

    result = process_one_issue_backfill_batch(
        command=command,
        session=session,
        api_key=api_key,
        scan=scan,
        candidate_limit=CANDIDATE_LIMIT,
        volume_cache=volume_cache,
        dry_run=dry_run,
    )

    summary.batches_fetched += 1
    summary.candidates_checked += result.candidates_checked
    summary.issues_created += result.issues_created
    summary.existing_issues_skipped += result.existing_issues_skipped
    summary.missing_data_skipped += result.missing_data_skipped
    summary.minimal_volumes_needed += result.minimal_volumes_needed

    if result.date_completed:
        summary.dates_completed += 1

    print_batch_summary(command, result)

    return result


def is_rate_limit_error(error):
    message = str(error).lower()

    return (
        "http 420" in message
        or "rate" in message
        or "velocity" in message
        or "wait before running" in message
    )


def print_runner_summary(command, summary):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Backfill runner summary:"))
    command.stdout.write(f"Backfill batches fetched: {summary.batches_fetched}")
    command.stdout.write(f"Candidates checked: {summary.candidates_checked}")
    command.stdout.write(f"Issues created: {summary.issues_created}")
    command.stdout.write(f"Existing issues skipped: {summary.existing_issues_skipped}")
    command.stdout.write(f"Missing-data candidates skipped: {summary.missing_data_skipped}")
    command.stdout.write(f"Minimal local volumes needed: {summary.minimal_volumes_needed}")
    command.stdout.write(f"Dates completed: {summary.dates_completed}")


def get_incomplete_backfill_scan_count():
    return ComicVineDateScan.objects.filter(
        scan_kind=ComicVineDateScan.ISSUE_DATE_ADDED,
        completed=False,
    ).count()