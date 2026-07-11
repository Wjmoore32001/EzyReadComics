from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, transaction


APP_LABELS_TO_CLEAR = [
    "ingestion",
    "catalog",
]


class Command(BaseCommand):
    help = (
        "Completely clears all ingestion and catalog tables. "
        "No flags. No partial reset. This is destructive."
    )

    def handle(self, *args, **options):
        models = []

        for app_label in APP_LABELS_TO_CLEAR:
            app_config = apps.get_app_config(app_label)
            models.extend(app_config.get_models())

        tables = [
            model._meta.db_table
            for model in models
            if model._meta.managed
        ]

        if not tables:
            self.stdout.write(self.style.WARNING("No ingestion/catalog tables found."))
            return

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Reset Marvel ingestion/catalog"))
        self.stdout.write("Mode: destructive database reset")
        self.stdout.write("Apps cleared: ingestion, catalog")
        self.stdout.write("")
        self.stdout.write("Tables to clear:")

        for table in tables:
            self.stdout.write(f"  - {table}")

        quoted_tables = ", ".join(
            connection.ops.quote_name(table)
            for table in tables
        )

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE;"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Reset complete. Cleared all ingestion and catalog tables."
            )
        )