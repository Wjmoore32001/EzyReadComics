from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import ComicRun


OLD_STATUS = "ended"


class Command(BaseCommand):
    help = "Convert old ComicRun status value 'ended' to 'completed'."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually update matching ComicRun rows. Without this flag, only preview counts.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]

        queryset = ComicRun.objects.filter(status=OLD_STATUS)
        run_count = queryset.count()

        self.stdout.write(f"Runs with status '{OLD_STATUS}': {run_count}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. Re-run with --apply to convert these rows to 'completed'."
                )
            )
            return

        if run_count == 0:
            self.stdout.write(self.style.SUCCESS("No rows needed conversion."))
            return

        with transaction.atomic():
            updated_count = queryset.update(status=ComicRun.STATUS_COMPLETED)

        self.stdout.write(
            self.style.SUCCESS(
                f"Converted {updated_count} ComicRun rows from '{OLD_STATUS}' to '{ComicRun.STATUS_COMPLETED}'."
            )
        )