import re
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Case, IntegerField, When
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import ComicIssue, ComicPublisher, ComicRun, ComicVolume
from comicvine.models import ComicVineIssue
from ingestion.models import (
    ComicVineVolumeCandidate,
    MarvelCatalogIssueSource,
    MarvelCatalogRunSource,
    MarvelCatalogVolumeSource,
    MarvelVolumeContainment,
)


PUBLISHER_NAME = "Marvel"


@dataclass
class ApplyResult:
    candidates_seen: int = 0

    runs_created: int = 0
    runs_linked_existing: int = 0
    runs_updated: int = 0
    run_source_links_created: int = 0
    run_source_links_updated: int = 0

    issues_seen: int = 0
    issues_created: int = 0
    issues_linked_existing: int = 0
    issues_updated: int = 0
    issue_source_links_created: int = 0
    issue_source_links_updated: int = 0
    issues_skipped: int = 0

    volumes_created: int = 0
    volumes_linked_existing: int = 0
    volumes_updated: int = 0
    volume_source_links_created: int = 0
    volume_source_links_updated: int = 0

    candidates_marked_applied: int = 0
    missing_catalog_targets: int = 0
    conflicts: int = 0
    skipped: int = 0


class Command(BaseCommand):
    help = (
        "Apply confirmed Marvel ingestion candidates into catalog rows and create "
        "source-link tracking rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            action="append",
            dest="comicvine_volume_ids",
            help=(
                "Optional Comic Vine volume ID to apply. Can be provided multiple times. "
                "If omitted, all ready confirmed Marvel candidates are selected."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional maximum number of candidates to apply.",
        )
        parser.add_argument(
            "--create-missing-catalog",
            action="store_true",
            help=(
                "Create missing catalog runs, issues, and collected volumes. "
                "Without this flag, the command only links to existing exact catalog rows."
            ),
        )
        parser.add_argument(
            "--update-existing-catalog",
            action="store_true",
            help=(
                "Update existing catalog fields from source data. "
                "Without this flag, existing catalog rows only have blank fields filled."
            ),
        )
        parser.add_argument(
            "--skip-collected-volumes",
            action="store_true",
            help=(
                "Apply confirmed runs and issues only. "
                "Do not create/link collected volume catalog rows."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Summarize what would happen without saving database changes.",
        )

    def handle(self, *args, **options):
        comicvine_volume_ids = options["comicvine_volume_ids"] or []
        limit = options["limit"]
        create_missing_catalog = options["create_missing_catalog"]
        update_existing_catalog = options["update_existing_catalog"]
        skip_collected_volumes = options["skip_collected_volumes"]
        dry_run = options["dry_run"]

        validate_options(
            comicvine_volume_ids=comicvine_volume_ids,
            limit=limit,
        )

        candidates = list_selected_candidates(
            comicvine_volume_ids=comicvine_volume_ids,
            limit=limit,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Apply Marvel ingestion to catalog"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")
        self.stdout.write("Source: confirmed Marvel ingestion candidates")
        self.stdout.write("Comic Vine API calls: none")
        self.stdout.write(
            f"Create missing catalog rows: {'yes' if create_missing_catalog else 'no'}"
        )
        self.stdout.write(
            "Update existing catalog rows: "
            f"{'yes' if update_existing_catalog else 'fill blanks only'}"
        )
        self.stdout.write(
            f"Collected volumes: {'skipped' if skip_collected_volumes else 'included'}"
        )

        if comicvine_volume_ids:
            self.stdout.write(
                "Selected Comic Vine volume IDs: "
                + ", ".join(str(volume_id) for volume_id in comicvine_volume_ids)
            )
        else:
            self.stdout.write("Selected Comic Vine volume IDs: all ready candidates")

        self.stdout.write(f"Limit: {limit if limit is not None else 'none'}")
        self.stdout.write(f"Candidates selected: {len(candidates)}")

        with transaction.atomic():
            publisher = get_or_create_marvel_publisher()
            result = apply_candidates(
                candidates=candidates,
                publisher=publisher,
                create_missing_catalog=create_missing_catalog,
                update_existing_catalog=update_existing_catalog,
                skip_collected_volumes=skip_collected_volumes,
            )

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Run complete."))
        self.stdout.write("=" * 60)

        prefix = "Would " if dry_run else ""

        self.stdout.write(f"Candidates seen: {result.candidates_seen}")
        self.stdout.write("")
        self.stdout.write(f"{prefix}runs created: {result.runs_created}")
        self.stdout.write(f"{prefix}runs linked existing: {result.runs_linked_existing}")
        self.stdout.write(f"{prefix}runs updated: {result.runs_updated}")
        self.stdout.write(
            f"{prefix}run source links created: {result.run_source_links_created}"
        )
        self.stdout.write(
            f"{prefix}run source links updated: {result.run_source_links_updated}"
        )
        self.stdout.write("")
        self.stdout.write(f"Issues seen: {result.issues_seen}")
        self.stdout.write(f"{prefix}issues created: {result.issues_created}")
        self.stdout.write(
            f"{prefix}issues linked existing: {result.issues_linked_existing}"
        )
        self.stdout.write(f"{prefix}issues updated: {result.issues_updated}")
        self.stdout.write(
            f"{prefix}issue source links created: {result.issue_source_links_created}"
        )
        self.stdout.write(
            f"{prefix}issue source links updated: {result.issue_source_links_updated}"
        )
        self.stdout.write(f"Issues skipped: {result.issues_skipped}")
        self.stdout.write("")
        self.stdout.write(f"{prefix}volumes created: {result.volumes_created}")
        self.stdout.write(
            f"{prefix}volumes linked existing: {result.volumes_linked_existing}"
        )
        self.stdout.write(f"{prefix}volumes updated: {result.volumes_updated}")
        self.stdout.write(
            f"{prefix}volume source links created: {result.volume_source_links_created}"
        )
        self.stdout.write(
            f"{prefix}volume source links updated: {result.volume_source_links_updated}"
        )
        self.stdout.write("")
        self.stdout.write(
            f"{prefix}candidates marked applied: {result.candidates_marked_applied}"
        )
        self.stdout.write(f"Missing catalog targets: {result.missing_catalog_targets}")
        self.stdout.write(f"Conflicts: {result.conflicts}")
        self.stdout.write(f"Skipped: {result.skipped}")

        if dry_run:
            self.stdout.write("")
            self.stdout.write("Dry run only. No database changes were saved.")


def validate_options(*, comicvine_volume_ids, limit):
    invalid_volume_ids = [
        volume_id for volume_id in comicvine_volume_ids if volume_id < 1
    ]

    if invalid_volume_ids:
        raise CommandError("--comicvine-volume-id values must be positive integers.")

    if limit is not None and limit < 1:
        raise CommandError("--limit must be at least 1 when provided.")


def list_selected_candidates(*, comicvine_volume_ids, limit):
    queryset = (
        ComicVineVolumeCandidate.objects.select_related(
            "comicvine_volume",
            "group",
            "proposed_parent_run_candidate",
            "catalog_volume",
        )
        .filter(
            publisher_name__iexact=PUBLISHER_NAME,
            analysis_status__in=[
                ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
                ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME,
            ],
            catalog_status__in=[
                ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
                ComicVineVolumeCandidate.CATALOG_STATUS_UPDATE_AVAILABLE,
                ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED,
            ],
        )
        .annotate(
            apply_order=Case(
                When(
                    analysis_status=ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
                    then=0,
                ),
                When(
                    analysis_status=(
                        ComicVineVolumeCandidate
                        .ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
                    ),
                    then=1,
                ),
                default=2,
                output_field=IntegerField(),
            )
        )
        .order_by(
            "normalized_title",
            "apply_order",
            "first_issue_date",
            "last_issue_date",
            "comicvine_volume__comicvine_id",
        )
    )

    if comicvine_volume_ids:
        queryset = queryset.filter(
            comicvine_volume__comicvine_id__in=comicvine_volume_ids,
        )

    if limit is not None:
        queryset = queryset[:limit]

    return list(queryset)


def get_or_create_marvel_publisher():
    publisher = ComicPublisher.objects.filter(slug="marvel").first()

    if publisher is not None:
        return publisher

    publisher = ComicPublisher.objects.filter(name__iexact=PUBLISHER_NAME).first()

    if publisher is not None:
        return publisher

    return ComicPublisher.objects.create(
        name=PUBLISHER_NAME,
        slug=slugify(PUBLISHER_NAME),
    )


def apply_candidates(
    *,
    candidates,
    publisher,
    create_missing_catalog,
    update_existing_catalog,
    skip_collected_volumes,
):
    result = ApplyResult()

    run_candidates = [
        candidate
        for candidate in candidates
        if candidate.analysis_status
        == ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN
    ]
    collected_volume_candidates = [
        candidate
        for candidate in candidates
        if candidate.analysis_status
        == ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
    ]

    for candidate in run_candidates:
        result.candidates_seen += 1

        apply_run_candidate(
            candidate=candidate,
            publisher=publisher,
            create_missing_catalog=create_missing_catalog,
            update_existing_catalog=update_existing_catalog,
            result=result,
        )

    if skip_collected_volumes:
        result.skipped += len(collected_volume_candidates)
        return result

    for candidate in collected_volume_candidates:
        result.candidates_seen += 1

        apply_collected_volume_candidate(
            candidate=candidate,
            publisher=publisher,
            create_missing_catalog=create_missing_catalog,
            update_existing_catalog=update_existing_catalog,
            result=result,
        )

    return result


def apply_run_candidate(
    *,
    candidate,
    publisher,
    create_missing_catalog,
    update_existing_catalog,
    result,
):
    now = timezone.now()

    catalog_run, run_status = resolve_catalog_run(
        candidate=candidate,
        publisher=publisher,
        create_missing_catalog=create_missing_catalog,
    )

    if run_status == "conflict":
        result.conflicts += 1
        return

    if catalog_run is None:
        result.missing_catalog_targets += 1
        return

    if run_status == "created":
        result.runs_created += 1
    elif run_status == "existing":
        result.runs_linked_existing += 1

    if update_catalog_run_from_source(
        catalog_run=catalog_run,
        candidate=candidate,
        update_existing_catalog=update_existing_catalog,
    ):
        result.runs_updated += 1

    run_link, run_link_status = upsert_run_source_link(
        candidate=candidate,
        catalog_run=catalog_run,
        now=now,
    )

    if run_link_status == "conflict":
        result.conflicts += 1
        return

    if run_link_status == "created":
        result.run_source_links_created += 1
    elif run_link_status == "updated":
        result.run_source_links_updated += 1

    if mark_candidate_applied(
        candidate=candidate,
        now=now,
    ):
        result.candidates_marked_applied += 1

    apply_run_issues(
        candidate=candidate,
        catalog_run=catalog_run,
        run_source=run_link,
        create_missing_catalog=create_missing_catalog,
        update_existing_catalog=update_existing_catalog,
        result=result,
        now=now,
    )


def resolve_catalog_run(*, candidate, publisher, create_missing_catalog):
    existing_link = find_run_source_link(candidate)

    if existing_link is not None:
        return existing_link.catalog_run, "existing"

    matching_runs = list(
        ComicRun.objects.filter(
            publisher=publisher,
            title=candidate.title,
            start_year=candidate.start_year,
        )
    )

    if len(matching_runs) == 1:
        return matching_runs[0], "existing"

    if len(matching_runs) > 1:
        return None, "conflict"

    if not create_missing_catalog:
        return None, "missing"

    catalog_run = ComicRun.objects.create(
        publisher=publisher,
        title=candidate.title,
        start_year=candidate.start_year,
        first_issue_date=candidate.first_issue_date,
        last_issue_date=candidate.last_issue_date,
        issue_count=candidate.source_issue_count,
        status=ComicRun.STATUS_UNKNOWN,
        description=clean_text(candidate.comicvine_volume.description),
    )
    copy_image_fields_from_volume_source(catalog_run, candidate.comicvine_volume)
    catalog_run.save()

    return catalog_run, "created"


def update_catalog_run_from_source(
    *,
    catalog_run,
    candidate,
    update_existing_catalog,
):
    update_fields = []

    field_values = {
        "first_issue_date": candidate.first_issue_date,
        "last_issue_date": candidate.last_issue_date,
        "issue_count": candidate.source_issue_count,
        "description": clean_text(candidate.comicvine_volume.description),
    }

    for field_name, source_value in field_values.items():
        if source_value in [None, ""]:
            continue

        current_value = getattr(catalog_run, field_name)

        if update_existing_catalog or current_value in [None, ""]:
            if current_value != source_value:
                setattr(catalog_run, field_name, source_value)
                update_fields.append(field_name)

    image_fields_changed = fill_image_fields_from_volume_source(
        catalog_object=catalog_run,
        source_volume=candidate.comicvine_volume,
        update_existing_catalog=update_existing_catalog,
    )
    update_fields.extend(image_fields_changed)

    if update_fields:
        catalog_run.save(update_fields=dedupe(update_fields))
        return True

    return False


def upsert_run_source_link(*, candidate, catalog_run, now):
    existing_link = find_run_source_link(candidate)

    link_data = {
        "catalog_run": catalog_run,
        "comicvine_volume": candidate.comicvine_volume,
        "candidate": candidate,
        "source_volume_date_last_updated": candidate.source_volume_date_last_updated,
        "source_issue_fingerprint": candidate.source_issue_fingerprint,
        "last_processed_at": now,
    }

    if existing_link is None:
        existing_link = MarvelCatalogRunSource.objects.create(
            confirmed_at=now,
            **link_data,
        )
        return existing_link, "created"

    if existing_link.catalog_run_id != catalog_run.id:
        return existing_link, "conflict"

    if existing_link.comicvine_volume_id != candidate.comicvine_volume_id:
        return existing_link, "conflict"

    update_fields = []

    for field_name, new_value in link_data.items():
        if getattr(existing_link, field_name) != new_value:
            setattr(existing_link, field_name, new_value)
            update_fields.append(field_name)

    if existing_link.source_changed_at is not None:
        existing_link.source_changed_at = None
        update_fields.append("source_changed_at")

    if update_fields:
        existing_link.save(update_fields=dedupe(update_fields))
        return existing_link, "updated"

    return existing_link, "unchanged"


def find_run_source_link(candidate):
    link = MarvelCatalogRunSource.objects.filter(candidate=candidate).first()

    if link is not None:
        return link

    return MarvelCatalogRunSource.objects.filter(
        comicvine_volume=candidate.comicvine_volume,
    ).first()


def mark_candidate_applied(*, candidate, now):
    update_fields = []

    if candidate.catalog_status != ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED:
        candidate.catalog_status = ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED
        update_fields.append("catalog_status")

    if candidate.catalog_applied_at is None:
        candidate.catalog_applied_at = now
        update_fields.append("catalog_applied_at")

    if update_fields:
        candidate.save(update_fields=dedupe(update_fields))
        return True

    return False


def apply_run_issues(
    *,
    candidate,
    catalog_run,
    run_source,
    create_missing_catalog,
    update_existing_catalog,
    result,
    now,
):
    source_issues = (
        ComicVineIssue.objects.filter(volume=candidate.comicvine_volume)
        .order_by(
            "store_date",
            "cover_date",
            "issue_number",
            "comicvine_id",
            "id",
        )
    )

    for source_issue in source_issues:
        result.issues_seen += 1

        issue_number = clean_text(source_issue.issue_number)

        if not issue_number:
            result.issues_skipped += 1
            continue

        catalog_issue, issue_status = resolve_catalog_issue(
            catalog_run=catalog_run,
            source_issue=source_issue,
            create_missing_catalog=create_missing_catalog,
        )

        if issue_status == "conflict":
            result.conflicts += 1
            continue

        if catalog_issue is None:
            result.missing_catalog_targets += 1
            continue

        if issue_status == "created":
            result.issues_created += 1
        elif issue_status == "existing":
            result.issues_linked_existing += 1

        if update_catalog_issue_from_source(
            catalog_issue=catalog_issue,
            source_issue=source_issue,
            update_existing_catalog=update_existing_catalog,
        ):
            result.issues_updated += 1

        _, issue_link_status = upsert_issue_source_link(
            catalog_issue=catalog_issue,
            catalog_run=catalog_run,
            source_issue=source_issue,
            source_volume=candidate.comicvine_volume,
            run_source=run_source,
            now=now,
        )

        if issue_link_status == "conflict":
            result.conflicts += 1
        elif issue_link_status == "created":
            result.issue_source_links_created += 1
        elif issue_link_status == "updated":
            result.issue_source_links_updated += 1


def resolve_catalog_issue(*, catalog_run, source_issue, create_missing_catalog):
    existing_link = MarvelCatalogIssueSource.objects.filter(
        comicvine_issue=source_issue,
    ).first()

    if existing_link is not None:
        if existing_link.catalog_run_id != catalog_run.id:
            return None, "conflict"

        return existing_link.catalog_issue, "existing"

    issue_number = clean_text(source_issue.issue_number)

    try:
        catalog_issue = ComicIssue.objects.get(
            run=catalog_run,
            issue_number=issue_number,
        )
        return catalog_issue, "existing"
    except ComicIssue.DoesNotExist:
        pass

    if not create_missing_catalog:
        return None, "missing"

    catalog_issue = ComicIssue.objects.create(
        run=catalog_run,
        issue_number=issue_number,
        title=clean_text(source_issue.issue_title),
        cover_date=source_issue.cover_date,
        store_date=source_issue.store_date,
        description=clean_text(source_issue.description),
    )
    copy_image_fields_from_issue_source(catalog_issue, source_issue)
    catalog_issue.save()

    return catalog_issue, "created"


def update_catalog_issue_from_source(
    *,
    catalog_issue,
    source_issue,
    update_existing_catalog,
):
    update_fields = []

    field_values = {
        "title": clean_text(source_issue.issue_title),
        "cover_date": source_issue.cover_date,
        "store_date": source_issue.store_date,
        "description": clean_text(source_issue.description),
    }

    for field_name, source_value in field_values.items():
        if source_value in [None, ""]:
            continue

        current_value = getattr(catalog_issue, field_name)

        if update_existing_catalog or current_value in [None, ""]:
            if current_value != source_value:
                setattr(catalog_issue, field_name, source_value)
                update_fields.append(field_name)

    image_fields_changed = fill_image_fields_from_issue_source(
        catalog_object=catalog_issue,
        source_issue=source_issue,
        update_existing_catalog=update_existing_catalog,
    )
    update_fields.extend(image_fields_changed)

    if update_fields:
        catalog_issue.save(update_fields=dedupe(update_fields))
        return True

    return False


def upsert_issue_source_link(
    *,
    catalog_issue,
    catalog_run,
    source_issue,
    source_volume,
    run_source,
    now,
):
    link_by_source = MarvelCatalogIssueSource.objects.filter(
        comicvine_issue=source_issue,
    ).first()
    link_by_catalog_issue = MarvelCatalogIssueSource.objects.filter(
        catalog_issue=catalog_issue,
    ).first()

    if (
        link_by_source is not None
        and link_by_catalog_issue is not None
        and link_by_source.id != link_by_catalog_issue.id
    ):
        return link_by_source, "conflict"

    existing_link = link_by_source or link_by_catalog_issue

    if existing_link is not None:
        if existing_link.comicvine_issue_id != source_issue.id:
            return existing_link, "conflict"

        if existing_link.catalog_issue_id != catalog_issue.id:
            return existing_link, "conflict"

        if existing_link.catalog_run_id != catalog_run.id:
            return existing_link, "conflict"

    link_data = {
        "catalog_issue": catalog_issue,
        "catalog_run": catalog_run,
        "comicvine_issue": source_issue,
        "comicvine_volume": source_volume,
        "run_source": run_source,
        "source_issue_date_last_updated": source_issue.date_last_updated,
        "last_processed_at": now,
    }

    if existing_link is None:
        existing_link = MarvelCatalogIssueSource.objects.create(
            confirmed_at=now,
            **link_data,
        )
        return existing_link, "created"

    update_fields = []

    for field_name, new_value in link_data.items():
        if getattr(existing_link, field_name) != new_value:
            setattr(existing_link, field_name, new_value)
            update_fields.append(field_name)

    if existing_link.source_changed_at is not None:
        existing_link.source_changed_at = None
        update_fields.append("source_changed_at")

    if update_fields:
        existing_link.save(update_fields=dedupe(update_fields))
        return existing_link, "updated"

    return existing_link, "unchanged"


def apply_collected_volume_candidate(
    *,
    candidate,
    publisher,
    create_missing_catalog,
    update_existing_catalog,
    result,
):
    now = timezone.now()

    parent_candidate = candidate.proposed_parent_run_candidate

    if parent_candidate is None:
        result.missing_catalog_targets += 1
        return

    parent_run = resolve_parent_catalog_run(parent_candidate)

    if parent_run is None:
        result.missing_catalog_targets += 1
        return

    containment = MarvelVolumeContainment.objects.filter(
        run_candidate=parent_candidate,
        collected_volume_candidate=candidate,
        status=MarvelVolumeContainment.STATUS_CONFIRMED_BY_RULE,
    ).first()

    catalog_volume, volume_status = resolve_catalog_volume(
        candidate=candidate,
        publisher=publisher,
        parent_run=parent_run,
        create_missing_catalog=create_missing_catalog,
    )

    if volume_status == "conflict":
        result.conflicts += 1
        return

    if catalog_volume is None:
        result.missing_catalog_targets += 1
        return

    if volume_status == "created":
        result.volumes_created += 1
    elif volume_status == "existing":
        result.volumes_linked_existing += 1

    if update_catalog_volume_from_source(
        catalog_volume=catalog_volume,
        candidate=candidate,
        parent_run=parent_run,
        update_existing_catalog=update_existing_catalog,
    ):
        result.volumes_updated += 1

    _, volume_link_status = upsert_volume_source_link(
        candidate=candidate,
        catalog_volume=catalog_volume,
        catalog_run=parent_run,
        containment=containment,
        now=now,
    )

    if volume_link_status == "conflict":
        result.conflicts += 1
        return

    if volume_link_status == "created":
        result.volume_source_links_created += 1
    elif volume_link_status == "updated":
        result.volume_source_links_updated += 1

    if mark_volume_candidate_applied(
        candidate=candidate,
        catalog_volume=catalog_volume,
        now=now,
    ):
        result.candidates_marked_applied += 1


def resolve_parent_catalog_run(parent_candidate):
    source_link = find_run_source_link(parent_candidate)

    if source_link is not None:
        return source_link.catalog_run

    return None


def resolve_catalog_volume(
    *,
    candidate,
    publisher,
    parent_run,
    create_missing_catalog,
):
    existing_link = find_volume_source_link(candidate)

    if existing_link is not None:
        if (
            candidate.catalog_volume_id
            and candidate.catalog_volume_id != existing_link.catalog_volume_id
        ):
            return None, "conflict"

        return existing_link.catalog_volume, "existing"

    if candidate.catalog_volume_id:
        return candidate.catalog_volume, "existing"

    volume_title, volume_number = derive_catalog_volume_title_and_number(
        candidate=candidate,
        run_title=parent_run.title,
    )

    matching_volumes = list(
        ComicVolume.objects.filter(
            publisher=publisher,
            run=parent_run,
            title=volume_title,
            volume_number=volume_number,
        )
    )

    if len(matching_volumes) == 1:
        return matching_volumes[0], "existing"

    if len(matching_volumes) > 1:
        return None, "conflict"

    if not create_missing_catalog:
        return None, "missing"

    catalog_volume = ComicVolume.objects.create(
        publisher=publisher,
        run=parent_run,
        title=volume_title,
        volume_number=volume_number,
        first_issue_number="",
        last_issue_number="",
        release_date=candidate.first_issue_date,
        issue_count=None,
        description=clean_text(candidate.comicvine_volume.description),
    )
    copy_image_fields_from_volume_source(catalog_volume, candidate.comicvine_volume)
    catalog_volume.save()

    return catalog_volume, "created"


def update_catalog_volume_from_source(
    *,
    catalog_volume,
    candidate,
    parent_run,
    update_existing_catalog,
):
    update_fields = []

    volume_title, volume_number = derive_catalog_volume_title_and_number(
        candidate=candidate,
        run_title=parent_run.title,
    )

    field_values = {
        "title": volume_title,
        "volume_number": volume_number,
        "release_date": candidate.first_issue_date,
        "description": clean_text(candidate.comicvine_volume.description),
    }

    for field_name, source_value in field_values.items():
        if source_value in [None, ""]:
            continue

        current_value = getattr(catalog_volume, field_name)

        if update_existing_catalog or current_value in [None, ""]:
            if current_value != source_value:
                setattr(catalog_volume, field_name, source_value)
                update_fields.append(field_name)

    image_fields_changed = fill_image_fields_from_volume_source(
        catalog_object=catalog_volume,
        source_volume=candidate.comicvine_volume,
        update_existing_catalog=update_existing_catalog,
    )
    update_fields.extend(image_fields_changed)

    if update_fields:
        catalog_volume.save(update_fields=dedupe(update_fields))
        return True

    return False


def upsert_volume_source_link(
    *,
    candidate,
    catalog_volume,
    catalog_run,
    containment,
    now,
):
    existing_link = find_volume_source_link(candidate)

    link_data = {
        "catalog_volume": catalog_volume,
        "catalog_run": catalog_run,
        "comicvine_volume": candidate.comicvine_volume,
        "candidate": candidate,
        "containment": containment,
        "source_volume_date_last_updated": candidate.source_volume_date_last_updated,
        "source_issue_fingerprint": candidate.source_issue_fingerprint,
        "last_processed_at": now,
    }

    if existing_link is None:
        existing_link = MarvelCatalogVolumeSource.objects.create(
            confirmed_at=now,
            **link_data,
        )
        return existing_link, "created"

    if existing_link.catalog_volume_id != catalog_volume.id:
        return existing_link, "conflict"

    if existing_link.catalog_run_id != catalog_run.id:
        return existing_link, "conflict"

    if existing_link.comicvine_volume_id != candidate.comicvine_volume_id:
        return existing_link, "conflict"

    update_fields = []

    for field_name, new_value in link_data.items():
        if getattr(existing_link, field_name) != new_value:
            setattr(existing_link, field_name, new_value)
            update_fields.append(field_name)

    if existing_link.source_changed_at is not None:
        existing_link.source_changed_at = None
        update_fields.append("source_changed_at")

    if update_fields:
        existing_link.save(update_fields=dedupe(update_fields))
        return existing_link, "updated"

    return existing_link, "unchanged"


def find_volume_source_link(candidate):
    link = MarvelCatalogVolumeSource.objects.filter(candidate=candidate).first()

    if link is not None:
        return link

    return MarvelCatalogVolumeSource.objects.filter(
        comicvine_volume=candidate.comicvine_volume,
    ).first()


def mark_volume_candidate_applied(
    *,
    candidate,
    catalog_volume,
    now,
):
    update_fields = []

    if candidate.catalog_volume_id != catalog_volume.id:
        candidate.catalog_volume = catalog_volume
        update_fields.append("catalog_volume")

    if candidate.catalog_status != ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED:
        candidate.catalog_status = ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED
        update_fields.append("catalog_status")

    if candidate.catalog_applied_at is None:
        candidate.catalog_applied_at = now
        update_fields.append("catalog_applied_at")

    if update_fields:
        candidate.save(update_fields=dedupe(update_fields))
        return True

    return False


def derive_catalog_volume_title_and_number(*, candidate, run_title):
    source_issue_title = get_single_source_issue_title(candidate)
    display_source = source_issue_title or candidate.title

    volume_number, title = parse_volume_number_and_title(display_source)

    if not title:
        title = clean_text(display_source)

    title = remove_leading_run_title(title, run_title)

    if not title and clean_text(display_source).casefold() == clean_text(run_title).casefold():
        title = ""

    return title, volume_number


def get_single_source_issue_title(candidate):
    source_issues = list(
        ComicVineIssue.objects.filter(volume=candidate.comicvine_volume)
        .order_by("comicvine_id", "id")
    )

    if len(source_issues) != 1:
        return ""

    return clean_text(source_issues[0].issue_title)


def parse_volume_number_and_title(value):
    value = clean_text(value)

    if not value:
        return "", ""

    patterns = [
        r"^vol\.?\s*(?P<number>[0-9]+)\s*[:\-–—]?\s*(?P<title>.*)$",
        r"^volume\s*(?P<number>[0-9]+)\s*[:\-–—]?\s*(?P<title>.*)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, value, flags=re.IGNORECASE)

        if match:
            return (
                clean_text(match.group("number")),
                clean_text(match.group("title")),
            )

    return "", value


def remove_leading_run_title(title, run_title):
    title = clean_text(title)
    run_title = clean_text(run_title)

    if not title or not run_title:
        return title

    if title.casefold().startswith(run_title.casefold()):
        title = title[len(run_title):].strip()
        title = title.lstrip(":;-–— ").strip()

    return title


def copy_image_fields_from_volume_source(catalog_object, source_volume):
    fill_image_fields_from_volume_source(
        catalog_object=catalog_object,
        source_volume=source_volume,
        update_existing_catalog=True,
    )


def fill_image_fields_from_volume_source(
    *,
    catalog_object,
    source_volume,
    update_existing_catalog,
):
    source_to_target = {
        "comicvine_image_icon_url": "image_icon_url",
        "comicvine_image_medium_url": "image_medium_url",
        "comicvine_image_screen_url": "image_screen_url",
        "comicvine_image_screen_large_url": "image_screen_large_url",
        "comicvine_image_small_url": "image_small_url",
        "comicvine_image_super_url": "image_super_url",
        "comicvine_image_thumb_url": "image_thumb_url",
        "comicvine_image_tiny_url": "image_tiny_url",
        "comicvine_image_original_url": "image_original_url",
        "comicvine_image_tags": "image_tags",
        "display_image_url": "display_image_url",
    }

    changed_fields = []

    for source_field, target_field in source_to_target.items():
        source_value = clean_text(getattr(source_volume, source_field, ""))

        if not source_value:
            continue

        current_value = getattr(catalog_object, target_field)

        if update_existing_catalog or not current_value:
            if current_value != source_value:
                setattr(catalog_object, target_field, source_value)
                changed_fields.append(target_field)

    if clean_text(getattr(catalog_object, "display_image_url", "")):
        if (
            catalog_object.display_image_source
            != catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
        ):
            catalog_object.display_image_source = (
                catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
            )
            changed_fields.append("display_image_source")

    return changed_fields


def copy_image_fields_from_issue_source(catalog_issue, source_issue):
    fill_image_fields_from_issue_source(
        catalog_object=catalog_issue,
        source_issue=source_issue,
        update_existing_catalog=True,
    )


def fill_image_fields_from_issue_source(
    *,
    catalog_object,
    source_issue,
    update_existing_catalog,
):
    source_to_target = {
        "comicvine_image_icon_url": "image_icon_url",
        "comicvine_image_medium_url": "image_medium_url",
        "comicvine_image_screen_url": "image_screen_url",
        "comicvine_image_screen_large_url": "image_screen_large_url",
        "comicvine_image_small_url": "image_small_url",
        "comicvine_image_super_url": "image_super_url",
        "comicvine_image_thumb_url": "image_thumb_url",
        "comicvine_image_tiny_url": "image_tiny_url",
        "comicvine_image_original_url": "image_original_url",
        "comicvine_image_tags": "image_tags",
    }

    changed_fields = []

    for source_field, target_field in source_to_target.items():
        source_value = clean_text(getattr(source_issue, source_field, ""))

        if not source_value:
            continue

        current_value = getattr(catalog_object, target_field)

        if update_existing_catalog or not current_value:
            if current_value != source_value:
                setattr(catalog_object, target_field, source_value)
                changed_fields.append(target_field)

    if clean_text(getattr(catalog_object, "image_original_url", "")):
        if not clean_text(getattr(catalog_object, "display_image_url", "")):
            catalog_object.display_image_url = catalog_object.image_original_url
            changed_fields.append("display_image_url")

    if clean_text(getattr(catalog_object, "display_image_url", "")):
        if (
            catalog_object.display_image_source
            != catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
        ):
            catalog_object.display_image_source = (
                catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
            )
            changed_fields.append("display_image_source")

    return changed_fields


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def dedupe(values):
    seen = set()
    deduped_values = []

    for value in values:
        if value in seen:
            continue

        seen.add(value)
        deduped_values.append(value)

    return deduped_values