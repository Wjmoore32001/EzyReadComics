from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Min
from django.utils import timezone

from catalog.models import ComicRun


class Command(BaseCommand):
    help = (
        "Update every ComicRun first_issue_date and last_issue_date from its "
        "connected ComicIssue published_date values."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing updates.",
        )
        parser.add_argument(
            "--clear-empty",
            action="store_true",
            help=(
                "Clear first/latest issue dates on runs with no dated issues. "
                "By default, runs with no dated issues are left unchanged."
            ),
        )
        parser.add_argument(
            "--publisher",
            type=str,
            default="",
            help="Only update runs for a publisher name match, case-insensitive.",
        )
        parser.add_argument(
            "--run-id",
            type=int,
            action="append",
            default=[],
            help="Only update a specific run ID. Can be passed more than once.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit how many runs are checked.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each run that would be changed or was changed.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        clear_empty = options["clear_empty"]
        publisher = options["publisher"].strip()
        run_ids = options["run_id"]
        limit = options["limit"]
        verbose = options["verbose"]

        runs = ComicRun.objects.select_related(
            "publisher",
        ).annotate(
            computed_first_issue_date=Min("issues__published_date"),
            computed_last_issue_date=Max("issues__published_date"),
            issue_total=Count("issues", distinct=True),
            dated_issue_total=Count("issues__published_date"),
        ).order_by(
            "publisher__name",
            "title",
            "start_year",
            "id",
        )

        if publisher:
            runs = runs.filter(publisher__name__icontains=publisher)

        if run_ids:
            runs = runs.filter(id__in=run_ids)

        if limit is not None:
            runs = runs[:limit]

        checked_count = 0
        changed_count = 0
        skipped_no_dates_count = 0

        for run in runs.iterator():
            checked_count += 1

            new_first_issue_date = run.computed_first_issue_date
            new_last_issue_date = run.computed_last_issue_date

            has_dated_issues = bool(new_first_issue_date or new_last_issue_date)

            if not has_dated_issues and not clear_empty:
                skipped_no_dates_count += 1
                continue

            if (
                run.first_issue_date == new_first_issue_date
                and run.last_issue_date == new_last_issue_date
            ):
                continue

            changed_count += 1

            if verbose or dry_run:
                self.print_run_change(
                    run=run,
                    new_first_issue_date=new_first_issue_date,
                    new_last_issue_date=new_last_issue_date,
                    dry_run=dry_run,
                )

            if dry_run:
                continue

            ComicRun.objects.filter(id=run.id).update(
                first_issue_date=new_first_issue_date,
                last_issue_date=new_last_issue_date,
                updated_at=timezone.now(),
            )

        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run only. No runs were updated."))

        self.stdout.write(self.style.SUCCESS("Run issue date update complete."))
        self.stdout.write(f"Runs checked: {checked_count}")
        self.stdout.write(f"Runs changed: {changed_count}")
        self.stdout.write(f"Runs skipped with no dated issues: {skipped_no_dates_count}")

    def print_run_change(
        self,
        *,
        run,
        new_first_issue_date,
        new_last_issue_date,
        dry_run,
    ):
        prefix = "Would update" if dry_run else "Updating"

        old_first = run.first_issue_date.isoformat() if run.first_issue_date else "Unknown"
        old_last = run.last_issue_date.isoformat() if run.last_issue_date else "Unknown"
        new_first = new_first_issue_date.isoformat() if new_first_issue_date else "Unknown"
        new_last = new_last_issue_date.isoformat() if new_last_issue_date else "Unknown"

        self.stdout.write(
            f"{prefix}: {run} "
            f"| first: {old_first} -> {new_first} "
            f"| latest: {old_last} -> {new_last} "
            f"| issues: {run.issue_total} "
            f"| dated issues: {run.dated_issue_total}"
        )