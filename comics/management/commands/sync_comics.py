from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


SYNC_COMMANDS = [
    "update_issues",
    "add_issues",
    "update_volumes",
    "hydrate_volumes",
    "hydrate_issues",
]


class Command(BaseCommand):
    help = "Run the normal Comic Vine sync commands in the recommended order."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run each sync command in dry-run mode without saving database changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine normal sync"))
        self.stdout.write("Command order:")

        for index, command_name in enumerate(SYNC_COMMANDS, start=1):
            self.stdout.write(f"{index}. {command_name}")

        for index, command_name in enumerate(SYNC_COMMANDS, start=1):
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"Step {index}/{len(SYNC_COMMANDS)}: {command_name}"))

            try:
                call_command(
                    command_name,
                    dry_run=dry_run,
                    stdout=self.stdout,
                    stderr=self.stderr,
                )
            except CommandError:
                raise
            except Exception as error:
                raise CommandError(
                    f"Comic Vine normal sync stopped during {command_name}: {error}"
                ) from error

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine normal sync finished."))