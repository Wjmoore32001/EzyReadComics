from calendar import monthrange

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Count, Max, Min
from django.utils import timezone

from catalog.models import ComicRun


COMPLETED_STATUS = "completed"
ONGOING_STATUS = "ongoing"
DEFAULT_MONTHS_WITHOUT_RELEASE = 3
DEFAULT_BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Sync every comic run's first/latest issue dates from related issues, "
        "then update stale/recent run statuses."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--months-without-release",
            type=int,
            default=DEFAULT_MONTHS_WITHOUT_RELEASE,
            help=(
                "How many months without a newer issue date makes a run completed. "
                f"Default: {DEFAULT_MONTHS_WITHOUT_RELEASE}."
            ),
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Bulk update batch size. Default: {DEFAULT_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without updating the database.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each changed run.",
        )

    def handle(self, *args, **options):
        close_old_connections()

        months_without_release = options["months_without_release"]
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        if months_without_release < 1:
            raise CommandError("--months-without-release must be at least 1.")

        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")

        today = timezone.localdate()
        stale_before_date = subtract_months(today, months_without_release)

        self.stdout.write("")
        self.stdout.write("Run issue date/status sync")
        self.stdout.write(f"Mode: {'dry-run' if dry_run else 'apply'}")
        self.stdout.write(f"Today: {today}")
        self.stdout.write(
            f"Completed threshold: latest issue date before {stale_before_date}"
        )
        self.stdout.write(f"Months without release: {months_without_release}")
        self.stdout.write(f"Batch size: {batch_size}")
        self.stdout.write("")

        totals = {
            "runs_scanned": 0,
            "runs_without_issues": 0,
            "runs_without_dated_issues": 0,
            "runs_changed": 0,
            "first_issue_date_updates": 0,
            "latest_issue_date_updates": 0,
            "completed_status_updates": 0,
            "ongoing_status_updates": 0,
        }

        changed_runs = []

        runs = (
            ComicRun.objects.select_related("publisher")
            .annotate(
                calculated_first_issue_date=Min("issues__published_date"),
                calculated_last_issue_date=Max("issues__published_date"),
                calculated_issue_count=Count("issues", distinct=True),
            )
            .only(
                "id",
                "publisher__name",
                "title",
                "start_year",
                "first_issue_date",
                "last_issue_date",
                "status",
                "updated_at",
            )
            .order_by("id")
        )

        for run in runs.iterator(chunk_size=batch_size):
            totals["runs_scanned"] += 1

            issue_count = run.calculated_issue_count or 0
            calculated_first_issue_date = run.calculated_first_issue_date
            calculated_last_issue_date = run.calculated_last_issue_date

            if issue_count == 0:
                totals["runs_without_issues"] += 1
            elif calculated_last_issue_date is None:
                totals["runs_without_dated_issues"] += 1

            changed_fields = []

            if run.first_issue_date != calculated_first_issue_date:
                run.first_issue_date = calculated_first_issue_date
                changed_fields.append("first_issue_date")
                totals["first_issue_date_updates"] += 1

            if run.last_issue_date != calculated_last_issue_date:
                run.last_issue_date = calculated_last_issue_date
                changed_fields.append("last_issue_date")
                totals["latest_issue_date_updates"] += 1

            status_changed = sync_run_status(
                run=run,
                latest_issue_date=calculated_last_issue_date,
                stale_before_date=stale_before_date,
            )

            if status_changed == "completed":
                changed_fields.append("status")
                totals["completed_status_updates"] += 1
            elif status_changed == "ongoing":
                changed_fields.append("status")
                totals["ongoing_status_updates"] += 1

            if changed_fields:
                run.updated_at = timezone.now()
                changed_runs.append(run)
                totals["runs_changed"] += 1

                if verbose:
                    publisher_name = run.publisher.name if run.publisher_id else "Unknown"
                    self.stdout.write(
                        "[change] "
                        f"{publisher_name} - {run} | "
                        f"first={run.first_issue_date or 'none'} | "
                        f"latest={run.last_issue_date or 'none'} | "
                        f"status={run.status} | "
                        f"fields={', '.join(sorted(set(changed_fields)))}"
                    )

        if changed_runs and not dry_run:
            ComicRun.objects.bulk_update(
                changed_runs,
                ["first_issue_date", "last_issue_date", "status", "updated_at"],
                batch_size=batch_size,
            )

        self.stdout.write("")
        self.stdout.write("Summary")
        self.stdout.write(f"Runs scanned: {totals['runs_scanned']}")
        self.stdout.write(f"Runs changed: {totals['runs_changed']}")
        self.stdout.write(f"Runs without issues: {totals['runs_without_issues']}")
        self.stdout.write(
            f"Runs with issues but no dated issues: {totals['runs_without_dated_issues']}"
        )
        self.stdout.write(
            f"First issue date updates: {totals['first_issue_date_updates']}"
        )
        self.stdout.write(
            f"Latest issue date updates: {totals['latest_issue_date_updates']}"
        )
        self.stdout.write(
            f"Status changed to completed: {totals['completed_status_updates']}"
        )
        self.stdout.write(
            f"Status changed to ongoing: {totals['ongoing_status_updates']}"
        )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("Dry run only. No database changes were saved.")
            )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Run issue dates/statuses synced."))


def sync_run_status(run, latest_issue_date, stale_before_date):
    if latest_issue_date is None:
        return ""

    if latest_issue_date < stale_before_date:
        if run.status != COMPLETED_STATUS:
            run.status = COMPLETED_STATUS
            return "completed"

        return ""

    if run.status == COMPLETED_STATUS:
        run.status = ONGOING_STATUS
        return "ongoing"

    return ""


def subtract_months(value, months):
    month_index = value.month - 1 - months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])

    return value.replace(year=year, month=month, day=day)