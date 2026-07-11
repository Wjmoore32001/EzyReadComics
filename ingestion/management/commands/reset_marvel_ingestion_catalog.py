from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import ComicIssue, ComicRun, ComicVolume
from ingestion.models import (
    ComicVineCollectedEditionCandidate,
    ComicVineCollectedEditionIssue,
    ComicVineVolumeCandidate,
    MarvelCatalogIssueSource,
    MarvelCatalogRunSource,
    MarvelCatalogVolumeSource,
)


class Command(BaseCommand):
    help = (
        "Reset Marvel ingestion analysis and optionally delete catalog rows tracked "
        "by Marvel source links."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete-catalog",
            action="store_true",
            help=(
                "Delete catalog issues and collected volumes connected to Marvel "
                "ingestion source links."
            ),
        )
        parser.add_argument(
            "--delete-runs",
            action="store_true",
            help="Also delete source-linked catalog runs. Requires --delete-catalog.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually perform the reset. Without this flag, this is a dry run.",
        )

    def handle(self, *args, **options):
        delete_catalog = options["delete_catalog"]
        delete_runs = options["delete_runs"]
        confirm = options["confirm"]

        if delete_runs and not delete_catalog:
            raise CommandError("--delete-runs requires --delete-catalog.")

        snapshot = build_snapshot()
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Marvel ingestion/catalog reset"))
        self.stdout.write(f"Mode: {'writing to database' if confirm else 'dry run'}")
        self.stdout.write(
            f"Delete source-linked catalog rows: {'yes' if delete_catalog else 'no'}"
        )
        self.stdout.write(
            f"Delete source-linked catalog runs: {'yes' if delete_runs else 'no'}"
        )
        self.stdout.write("")
        print_snapshot(self, snapshot)

        if not confirm:
            self.stdout.write("")
            self.stdout.write("Dry run only. Nothing was deleted.")
            self.stdout.write("")
            self.stdout.write("Reset ingestion analysis only:")
            self.stdout.write(
                "  python manage.py reset_marvel_ingestion_catalog --confirm"
            )
            self.stdout.write("")
            self.stdout.write("Reset ingestion plus source-linked issues/volumes:")
            self.stdout.write(
                "  python manage.py reset_marvel_ingestion_catalog "
                "--delete-catalog --confirm"
            )
            self.stdout.write("")
            self.stdout.write("Reset all source-linked catalog data including runs:")
            self.stdout.write(
                "  python manage.py reset_marvel_ingestion_catalog "
                "--delete-catalog --delete-runs --confirm"
            )
            return

        with transaction.atomic():
            reset_data(
                snapshot=snapshot,
                delete_catalog=delete_catalog,
                delete_runs=delete_runs,
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Reset complete."))


def build_snapshot():
    issue_source_links = MarvelCatalogIssueSource.objects.all()
    volume_source_links = MarvelCatalogVolumeSource.objects.all()
    run_source_links = MarvelCatalogRunSource.objects.all()
    catalog_issue_ids = list(
        issue_source_links.values_list("catalog_issue_id", flat=True).distinct()
    )
    catalog_volume_ids = list(
        volume_source_links.values_list("catalog_volume_id", flat=True).distinct()
    )
    catalog_run_ids = list(
        run_source_links.values_list("catalog_run_id", flat=True).distinct()
    )

    return {
        "issue_source_link_count": issue_source_links.count(),
        "volume_source_link_count": volume_source_links.count(),
        "run_source_link_count": run_source_links.count(),
        "catalog_issue_ids": catalog_issue_ids,
        "catalog_volume_ids": catalog_volume_ids,
        "catalog_run_ids": catalog_run_ids,
        "catalog_issue_count": ComicIssue.objects.filter(
            id__in=catalog_issue_ids
        ).count(),
        "catalog_volume_count": ComicVolume.objects.filter(
            id__in=catalog_volume_ids
        ).count(),
        "catalog_run_count": ComicRun.objects.filter(id__in=catalog_run_ids).count(),
        "collected_issue_link_count": ComicVineCollectedEditionIssue.objects.count(),
        "collected_candidate_count": (
            ComicVineCollectedEditionCandidate.objects.count()
        ),
        "run_candidate_count": ComicVineVolumeCandidate.objects.count(),
    }


def print_snapshot(command, snapshot):
    command.stdout.write("Source links:")
    command.stdout.write(f"  issue source links: {snapshot['issue_source_link_count']}")
    command.stdout.write(
        f"  collected-volume source links: {snapshot['volume_source_link_count']}"
    )
    command.stdout.write(f"  run source links: {snapshot['run_source_link_count']}")
    command.stdout.write("")
    command.stdout.write("Source-linked catalog rows:")
    command.stdout.write(f"  issues: {snapshot['catalog_issue_count']}")
    command.stdout.write(f"  collected volumes: {snapshot['catalog_volume_count']}")
    command.stdout.write(f"  runs: {snapshot['catalog_run_count']}")
    command.stdout.write("")
    command.stdout.write("Ingestion rows:")
    command.stdout.write(
        f"  resolved collected issue links: "
        f"{snapshot['collected_issue_link_count']}"
    )
    command.stdout.write(
        f"  collected-edition candidates: "
        f"{snapshot['collected_candidate_count']}"
    )
    command.stdout.write(f"  run candidates: {snapshot['run_candidate_count']}")


def reset_data(*, snapshot, delete_catalog, delete_runs):
    catalog_issue_ids = snapshot["catalog_issue_ids"]
    catalog_volume_ids = snapshot["catalog_volume_ids"]
    catalog_run_ids = snapshot["catalog_run_ids"]

    MarvelCatalogIssueSource.objects.all().delete()
    MarvelCatalogVolumeSource.objects.all().delete()
    MarvelCatalogRunSource.objects.all().delete()

    ComicVineCollectedEditionCandidate.objects.update(
        proposed_parent_run_candidate=None,
        catalog_volume=None,
    )
    ComicVineVolumeCandidate.objects.update(catalog_run=None)

    ComicVineCollectedEditionIssue.objects.all().delete()
    ComicVineCollectedEditionCandidate.objects.all().delete()
    ComicVineVolumeCandidate.objects.all().delete()

    if not delete_catalog:
        return

    ComicVolume.objects.filter(id__in=catalog_volume_ids).delete()
    ComicIssue.objects.filter(id__in=catalog_issue_ids).delete()

    if delete_runs:
        ComicRun.objects.filter(id__in=catalog_run_ids).delete()