from collections import Counter
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import ComicIssue, ComicRun
from comicvine.models import ComicVineIssue, ComicVineVolume


class Command(BaseCommand):
    help = (
        "Copy complete local Comic Vine issues from one Comic Vine volume into one catalog run. "
        "No API calls are made."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--catalog-run-id",
            type=int,
            required=True,
            help="Catalog ComicRun database ID to copy issues into.",
        )
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            required=True,
            help="Comic Vine volume ID stored in comicvine.ComicVineVolume.comicvine_id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would happen without creating or updating catalog issues.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print every copied, updated, skipped, and incomplete issue.",
        )

    def handle(self, *args, **options):
        catalog_run_id = options["catalog_run_id"]
        comicvine_volume_id = options["comicvine_volume_id"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        catalog_run = get_catalog_run(catalog_run_id)
        comicvine_volume = get_comicvine_volume(comicvine_volume_id)

        source_issues = list(
            ComicVineIssue.objects.filter(volume=comicvine_volume)
            .order_by("store_date", "cover_date", "issue_number", "id")
        )

        existing_catalog_issues = {
            normalize_issue_number(issue.issue_number): issue
            for issue in catalog_run.issues.all()
        }

        self.write_header(
            catalog_run=catalog_run,
            comicvine_volume=comicvine_volume,
            source_issues=source_issues,
            dry_run=dry_run,
        )

        created_count = 0
        updated_count = 0
        unchanged_count = 0
        skipped_count = 0
        skipped_reasons = Counter()

        with transaction.atomic():
            for source_issue in source_issues:
                validation_errors = get_source_issue_validation_errors(source_issue)

                if validation_errors:
                    skipped_count += 1

                    for reason in validation_errors:
                        skipped_reasons[reason] += 1

                    if verbose:
                        self.stdout.write(
                            self.style.WARNING(
                                format_source_skip_line(
                                    source_issue=source_issue,
                                    reasons=validation_errors,
                                )
                            )
                        )

                    continue

                normalized_issue_number = normalize_issue_number(source_issue.issue_number)
                existing_issue = existing_catalog_issues.get(normalized_issue_number)

                if existing_issue:
                    changed = update_existing_catalog_issue_from_source(
                        catalog_issue=existing_issue,
                        source_issue=source_issue,
                    )

                    if changed:
                        updated_count += 1

                        if not dry_run:
                            existing_issue.save()

                        if verbose:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Updated catalog issue: {existing_issue}"
                                )
                            )
                    else:
                        unchanged_count += 1

                        if verbose:
                            self.stdout.write(
                                f"Already complete: {existing_issue}"
                            )

                    continue

                created_count += 1

                if dry_run:
                    if verbose:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Would create catalog issue: {catalog_run} #{source_issue.issue_number}"
                            )
                        )

                    continue

                catalog_issue = ComicIssue.objects.create(
                    run=catalog_run,
                    issue_number=clean_text(source_issue.issue_number),
                    title=clean_text(source_issue.issue_title),
                    store_date=source_issue.store_date,
                    cover_date=source_issue.cover_date,
                    is_released=is_released_from_store_date(source_issue.store_date),
                    description="",
                )

                existing_catalog_issues[normalized_issue_number] = catalog_issue

                if verbose:
                    self.stdout.write(
                        self.style.SUCCESS(f"Created catalog issue: {catalog_issue}")
                    )

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine local issue copy complete."))
        self.stdout.write("API calls made: 0")
        self.stdout.write(f"Source Comic Vine issues checked: {len(source_issues)}")
        self.stdout.write(f"Created catalog issues: {created_count}")
        self.stdout.write(f"Updated catalog issues: {updated_count}")
        self.stdout.write(f"Already complete catalog issues: {unchanged_count}")
        self.stdout.write(f"Skipped source issues: {skipped_count}")

        if skipped_reasons:
            self.stdout.write("")
            self.stdout.write("Skipped reason counts:")

            for reason, count in sorted(skipped_reasons.items()):
                self.stdout.write(f"- {reason}: {count}")

        if dry_run:
            self.stdout.write("")
            self.stdout.write("Dry run only. No catalog issues were created or updated.")

    def write_header(self, *, catalog_run, comicvine_volume, source_issues, dry_run):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Copy local Comic Vine issues to catalog run"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write("Source: local comicvine tables")
        self.stdout.write("API calls: none")
        self.stdout.write(f"Catalog run: {catalog_run} [id={catalog_run.id}]")
        self.stdout.write(
            f"Comic Vine volume: {comicvine_volume.name} "
            f"[comicvine_id={comicvine_volume.comicvine_id}, local_id={comicvine_volume.id}]"
        )
        self.stdout.write(f"Local Comic Vine issues attached: {len(source_issues)}")

        if comicvine_volume.publisher and catalog_run.publisher:
            if comicvine_volume.publisher.casefold() != catalog_run.publisher.name.casefold():
                self.stdout.write(
                    self.style.WARNING(
                        f"Publisher warning: Comic Vine volume publisher is "
                        f"{comicvine_volume.publisher!r}, catalog run publisher is "
                        f"{catalog_run.publisher.name!r}."
                    )
                )

        self.stdout.write("")


def get_catalog_run(catalog_run_id):
    try:
        return ComicRun.objects.select_related("publisher").get(id=catalog_run_id)
    except ComicRun.DoesNotExist as exc:
        raise CommandError(f"No catalog ComicRun found with id={catalog_run_id}.") from exc


def get_comicvine_volume(comicvine_volume_id):
    try:
        return ComicVineVolume.objects.get(comicvine_id=comicvine_volume_id)
    except ComicVineVolume.DoesNotExist as exc:
        raise CommandError(
            f"No local ComicVineVolume found with comicvine_id={comicvine_volume_id}."
        ) from exc


def get_source_issue_validation_errors(source_issue):
    errors = []

    if not clean_text(source_issue.issue_number):
        errors.append("missing issue_number")

    if not clean_text(source_issue.issue_title):
        errors.append("missing title")

    if source_issue.store_date is None:
        errors.append("missing store_date")

    if source_issue.cover_date is None:
        errors.append("missing cover_date")

    return errors


def update_existing_catalog_issue_from_source(*, catalog_issue, source_issue):
    changed = False

    source_title = clean_text(source_issue.issue_title)

    if title_needs_repair(catalog_issue.title) and source_title:
        catalog_issue.title = source_title
        changed = True

    if catalog_issue.store_date is None and source_issue.store_date is not None:
        catalog_issue.store_date = source_issue.store_date
        changed = True

    if catalog_issue.cover_date is None and source_issue.cover_date is not None:
        catalog_issue.cover_date = source_issue.cover_date
        changed = True

    source_is_released = is_released_from_store_date(source_issue.store_date)

    if catalog_issue.is_released != source_is_released:
        catalog_issue.is_released = source_is_released
        changed = True

    return changed


def format_source_skip_line(*, source_issue, reasons):
    issue_number = clean_text(source_issue.issue_number) or "?"
    title = clean_text(source_issue.issue_title) or "[blank]"
    reason_text = ", ".join(reasons)

    return (
        f"Skipped Comic Vine issue #{issue_number}: "
        f"title={title}; "
        f"store_date={source_issue.store_date or 'missing'}; "
        f"cover_date={source_issue.cover_date or 'missing'}; "
        f"reason={reason_text}"
    )


def title_needs_repair(title):
    title = clean_text(title)

    if not title:
        return True

    return title.casefold() == "untitled"


def is_released_from_store_date(store_date):
    if store_date is None:
        return False

    return store_date <= date.today()


def normalize_issue_number(value):
    value = clean_text(value).casefold()
    value = value.replace("#", "")
    value = "".join(character for character in value if character.isalnum() or character == ".")
    return value


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()