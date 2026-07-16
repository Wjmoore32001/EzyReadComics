from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction

from catalog.current_reading_era import get_handler_for_publisher
from catalog.models import ComicRun, CurrentReadingEraRun


class Command(BaseCommand):
    help = (
        "Add eligible ongoing comic runs from supported publishers to the current "
        "reading era. Existing era rows are preserved and no rows are removed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which rows would be added without changing the database.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each run that would be added, added, or skipped.",
        )

    def handle(self, *args, **options):
        close_old_connections()

        dry_run = options["dry_run"]
        verbose = options["verbose"]

        ongoing_runs = list(
            ComicRun.objects.filter(status=ComicRun.STATUS_ONGOING)
            .select_related("publisher")
            .order_by(
                "publisher__name",
                "first_issue_date",
                "title",
                "start_year",
                "id",
            )
        )

        eligible_runs = []
        unsupported_runs = []
        excluded_runs = []

        for run in ongoing_runs:
            handler = get_handler_for_publisher(run.publisher)

            if handler is None:
                unsupported_runs.append(run)
                continue

            exclusion_reason = handler.get_exclusion_reason(run)

            if exclusion_reason:
                excluded_runs.append((run, exclusion_reason))
                continue

            eligible_runs.append(run)

        eligible_run_ids = [run.id for run in eligible_runs]
        existing_eligible_run_ids = set(
            CurrentReadingEraRun.objects.filter(
                run_id__in=eligible_run_ids,
            ).values_list("run_id", flat=True)
        )
        missing_runs = [
            run for run in eligible_runs if run.id not in existing_eligible_run_ids
        ]
        preserved_row_count = CurrentReadingEraRun.objects.count()

        self.stdout.write("")
        self.stdout.write("Current reading era sync")
        self.stdout.write(f"Mode: {'dry-run' if dry_run else 'apply'}")
        self.stdout.write("Behavior: additive only")
        self.stdout.write("Existing era rows are never removed.")
        self.stdout.write("")

        if verbose:
            for run in unsupported_runs:
                self.stdout.write(
                    f"[skip unsupported publisher] {run.publisher.name} - {run}"
                )

            for run, reason in excluded_runs:
                self.stdout.write(
                    f"[skip publisher exclusion] {run.publisher.name} - {run}: {reason}"
                )

            action_label = "would add" if dry_run else "add"

            for run in missing_runs:
                self.stdout.write(
                    f"[{action_label}] {run.publisher.name} - {run}"
                )

        if missing_runs and not dry_run:
            with transaction.atomic():
                CurrentReadingEraRun.objects.bulk_create(
                    [
                        CurrentReadingEraRun(run_id=run.id)
                        for run in missing_runs
                    ]
                )

        self.stdout.write("")
        self.stdout.write("Summary")
        self.stdout.write(f"Ongoing runs found: {len(ongoing_runs)}")
        self.stdout.write(f"Eligible ongoing runs: {len(eligible_runs)}")
        self.stdout.write(
            f"Skipped unsupported publishers: {len(unsupported_runs)}"
        )
        self.stdout.write(
            f"Skipped publisher exclusions: {len(excluded_runs)}"
        )
        self.stdout.write(
            "Eligible runs already in the era: "
            f"{len(existing_eligible_run_ids)}"
        )
        self.stdout.write(
            f"Existing era rows preserved: {preserved_row_count}"
        )

        if dry_run:
            self.stdout.write(f"Rows that would be added: {len(missing_runs)}")
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. No current reading era rows were added."
                )
            )
        else:
            self.stdout.write(f"Rows added: {len(missing_runs)}")
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS("Current reading era sync complete.")
            )

        close_old_connections()
