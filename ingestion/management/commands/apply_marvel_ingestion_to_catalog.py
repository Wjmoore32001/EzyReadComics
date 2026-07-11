from dataclasses import dataclass
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import ComicIssue, ComicPublisher, ComicRun
from ingestion.management.commands.analyze_marvel_comicvine_volumes import (
    ANALYSIS_VERSION,
    build_source_fingerprint,
    clean_issue_number,
    clean_html_text,
    clean_text,
    normalize_issue_number,
    parse_standard_issue_number,
)
from ingestion.models import (
    ComicVineVolumeCandidate,
    MarvelCatalogIssueSource,
    MarvelCatalogRunSource,
)


PUBLISHER_NAME = "Marvel"


@dataclass
class ApplyResult:
    candidates_seen: int = 0
    stale_candidates: int = 0
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
    candidates_marked_applied: int = 0
    missing_catalog_targets: int = 0
    conflicts: int = 0


class Command(BaseCommand):
    help = (
        "Apply confirmed Comic Vine runs and their directly attached issues to the "
        "catalog. Collected volumes are never selected or changed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            action="append",
            dest="comicvine_volume_ids",
            help=(
                "Optional confirmed Comic Vine run volume ID. Repeat to select "
                "multiple runs. If omitted, all ready confirmed runs are selected."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Optional maximum number of confirmed run candidates.",
        )
        parser.add_argument(
            "--create-missing-catalog",
            action="store_true",
            help="Create missing catalog runs and issues.",
        )
        parser.add_argument(
            "--update-existing-catalog",
            action="store_true",
            help=(
                "Overwrite populated run/issue fields with current nonblank Comic "
                "Vine values. Missing source values never clear catalog data."
            ),
        )

        mode_group = parser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument(
            "--dry-run",
            action="store_true",
            help="Summarize catalog changes without saving them.",
        )
        mode_group.add_argument(
            "--apply",
            action="store_true",
            help="Save confirmed run and issue changes.",
        )

    def handle(self, *args, **options):
        volume_ids = dedupe(options["comicvine_volume_ids"] or [])
        limit = options["limit"]
        create_missing_catalog = options["create_missing_catalog"]
        update_existing_catalog = options["update_existing_catalog"]
        dry_run = options["dry_run"]

        validate_options(volume_ids=volume_ids, limit=limit)
        candidates = list_selected_candidates(volume_ids=volume_ids, limit=limit)

        self.write_header(
            candidates=candidates,
            volume_ids=volume_ids,
            limit=limit,
            create_missing_catalog=create_missing_catalog,
            update_existing_catalog=update_existing_catalog,
            dry_run=dry_run,
        )

        with transaction.atomic():
            publisher = get_or_create_marvel_publisher()
            result = apply_candidates(
                candidates=candidates,
                publisher=publisher,
                create_missing_catalog=create_missing_catalog,
                update_existing_catalog=update_existing_catalog,
            )

            if dry_run:
                transaction.set_rollback(True)

        print_result(self, result, dry_run=dry_run)

    def write_header(
        self,
        *,
        candidates,
        volume_ids,
        limit,
        create_missing_catalog,
        update_existing_catalog,
        dry_run,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Apply Marvel Comic Vine runs and issues"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'write catalog rows'}")
        self.stdout.write("Source: confirmed local ComicVineVolumeCandidate rows")
        self.stdout.write("Comic Vine API calls: none")
        self.stdout.write("Collected-volume candidates queried: no")
        self.stdout.write("ComicVolume and ComicVolumeIssue writes: none")
        self.stdout.write(
            f"Create missing catalog rows: {'yes' if create_missing_catalog else 'no'}"
        )
        self.stdout.write(
            "Existing catalog fields: "
            + (
                "update from nonblank source values"
                if update_existing_catalog
                else "fill blank fields only"
            )
        )
        self.stdout.write(f"Confirmed run candidates selected: {len(candidates)}")

        if volume_ids:
            self.stdout.write(
                "Selected Comic Vine volume IDs: "
                + ", ".join(str(value) for value in volume_ids)
            )
        else:
            self.stdout.write("Selected Comic Vine volume IDs: all ready confirmed runs")

        self.stdout.write(f"Limit: {limit if limit is not None else 'none'}")


def validate_options(*, volume_ids, limit):
    if any(value < 1 for value in volume_ids):
        raise CommandError("--comicvine-volume-id values must be positive integers.")

    if limit is not None and limit < 1:
        raise CommandError("--limit must be at least 1.")


def list_selected_candidates(*, volume_ids, limit):
    allowed_catalog_statuses = [
        ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
        ComicVineVolumeCandidate.CATALOG_STATUS_UPDATE_AVAILABLE,
        ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED,
    ]
    base = ComicVineVolumeCandidate.objects.select_related(
        "comicvine_volume",
        "catalog_run",
    ).filter(
        publisher_name__iexact=PUBLISHER_NAME,
        analysis_version=ANALYSIS_VERSION,
        analysis_status=ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
        catalog_status__in=allowed_catalog_statuses,
    )

    if volume_ids:
        all_requested = list(
            ComicVineVolumeCandidate.objects.select_related("comicvine_volume").filter(
                comicvine_volume__comicvine_id__in=volume_ids
            )
        )
        by_volume_id = {
            candidate.comicvine_volume.comicvine_id: candidate
            for candidate in all_requested
        }
        missing = [value for value in volume_ids if value not in by_volume_id]
        not_ready = [
            f"{value} ({by_volume_id[value].analysis_status}, analysis v{by_volume_id[value].analysis_version})"
            for value in volume_ids
            if value in by_volume_id
            and (
                by_volume_id[value].analysis_status
                != ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN
                or by_volume_id[value].analysis_version != ANALYSIS_VERSION
                or by_volume_id[value].catalog_status not in allowed_catalog_statuses
            )
        ]

        if missing:
            raise CommandError(
                "Run analysis candidates are missing for Comic Vine volume IDs: "
                + ", ".join(str(value) for value in missing)
            )

        if not_ready:
            raise CommandError(
                "Requested Comic Vine volumes are not ready confirmed runs: "
                + ", ".join(not_ready)
            )

        base = base.filter(comicvine_volume__comicvine_id__in=volume_ids)

    candidates = list(
        base.order_by(
            "normalized_title",
            "start_year",
            "comicvine_volume__comicvine_id",
        )
    )

    if limit is not None:
        candidates = candidates[:limit]

    return candidates


def get_or_create_marvel_publisher():
    publisher = ComicPublisher.objects.filter(slug="marvel").first()
    if publisher:
        return publisher

    publisher = ComicPublisher.objects.filter(name__iexact=PUBLISHER_NAME).first()
    if publisher:
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
):
    result = ApplyResult()

    for candidate in candidates:
        result.candidates_seen += 1
        apply_run_candidate(
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
    source_issues = list(candidate.comicvine_volume.issues.all())
    current_fingerprint = build_source_fingerprint(
        candidate.comicvine_volume,
        source_issues,
    )

    if current_fingerprint != candidate.source_fingerprint:
        result.stale_candidates += 1
        return

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
    else:
        result.runs_linked_existing += 1

    now = timezone.now()
    run_source, link_status = upsert_run_source_link(
        candidate=candidate,
        catalog_run=catalog_run,
        now=now,
    )

    if link_status == "conflict":
        result.conflicts += 1
        return

    if link_status == "created":
        result.run_source_links_created += 1
    elif link_status == "updated":
        result.run_source_links_updated += 1

    if update_catalog_run_from_source(
        catalog_run=catalog_run,
        candidate=candidate,
        overwrite=update_existing_catalog,
    ):
        result.runs_updated += 1

    all_issues_applied = apply_run_issues(
        candidate=candidate,
        catalog_run=catalog_run,
        run_source=run_source,
        source_issues=source_issues,
        create_missing_catalog=create_missing_catalog,
        update_existing_catalog=update_existing_catalog,
        result=result,
        now=now,
    )

    if all_issues_applied:
        mark_candidate_applied(candidate=candidate, catalog_run=catalog_run, now=now)
        result.candidates_marked_applied += 1


def resolve_catalog_run(*, candidate, publisher, create_missing_catalog):
    source_links = list(
        MarvelCatalogRunSource.objects.filter(
            Q(candidate=candidate) | Q(comicvine_volume=candidate.comicvine_volume)
        ).distinct()
    )

    if len(source_links) > 1:
        return None, "conflict"

    if source_links:
        source_link = source_links[0]
        if candidate.catalog_run_id and candidate.catalog_run_id != source_link.catalog_run_id:
            return None, "conflict"
        return source_link.catalog_run, "existing"

    if candidate.catalog_run_id:
        return candidate.catalog_run, "existing"

    matching_runs = list(
        ComicRun.objects.filter(
            publisher=publisher,
            title=candidate.title,
            start_year=candidate.start_year,
        )
    )

    if len(matching_runs) > 1:
        return None, "conflict"
    if matching_runs:
        return matching_runs[0], "existing"
    if not create_missing_catalog:
        return None, "missing"

    catalog_run = ComicRun.objects.create(
        publisher=publisher,
        title=candidate.title,
        start_year=candidate.start_year,
        first_issue_date=candidate.first_issue_date,
        last_issue_date=candidate.last_issue_date,
        status=map_run_status(candidate.comicvine_volume.run_status),
        issue_count=candidate.source_issue_count,
        description=clean_html_text(candidate.comicvine_volume.description),
    )
    update_image_fields(
        target=catalog_run,
        source=candidate.comicvine_volume,
        source_prefix="comicvine_",
        overwrite=True,
    )
    catalog_run.save()
    return catalog_run, "created"


def upsert_run_source_link(*, candidate, catalog_run, now):
    links = list(
        MarvelCatalogRunSource.objects.filter(
            Q(candidate=candidate) | Q(comicvine_volume=candidate.comicvine_volume)
        ).distinct()
    )
    if len(links) > 1:
        return None, "conflict"

    catalog_conflict = MarvelCatalogRunSource.objects.filter(
        catalog_run=catalog_run
    ).exclude(candidate=candidate).exists()
    if catalog_conflict:
        return None, "conflict"

    values = {
        "catalog_run": catalog_run,
        "comicvine_volume": candidate.comicvine_volume,
        "candidate": candidate,
        "source_volume_date_last_updated": candidate.source_volume_date_last_updated,
        "source_fingerprint": candidate.source_fingerprint,
        "last_processed_at": now,
        "source_changed_at": None,
    }

    if not links:
        return MarvelCatalogRunSource.objects.create(confirmed_at=now, **values), "created"

    link = links[0]
    if (
        link.catalog_run_id != catalog_run.id
        or link.comicvine_volume_id != candidate.comicvine_volume_id
        or link.candidate_id != candidate.id
    ):
        return link, "conflict"

    update_fields = assign_changed_fields(link, values)
    if update_fields:
        link.save(update_fields=dedupe(update_fields))
        return link, "updated"
    return link, "unchanged"


def update_catalog_run_from_source(*, catalog_run, candidate, overwrite):
    values = {
        "title": candidate.title,
        "start_year": candidate.start_year,
        "first_issue_date": candidate.first_issue_date,
        "last_issue_date": candidate.last_issue_date,
        "status": map_run_status(candidate.comicvine_volume.run_status),
        "issue_count": candidate.source_issue_count,
        "description": clean_html_text(candidate.comicvine_volume.description),
    }
    update_fields = update_source_fields(catalog_run, values, overwrite=overwrite)
    update_fields.extend(
        update_image_fields(
            target=catalog_run,
            source=candidate.comicvine_volume,
            source_prefix="comicvine_",
            overwrite=overwrite,
        )
    )
    if not update_fields:
        return False
    catalog_run.save(update_fields=dedupe(update_fields))
    return True


def apply_run_issues(
    *,
    candidate,
    catalog_run,
    run_source,
    source_issues,
    create_missing_catalog,
    update_existing_catalog,
    result,
    now,
):
    source_issues.sort(key=issue_sort_key)
    all_applied = bool(source_issues)

    for source_issue in source_issues:
        result.issues_seen += 1
        issue_number = normalize_issue_number(source_issue.issue_number)

        if not source_issue.comicvine_id or not issue_number:
            result.issues_skipped += 1
            all_applied = False
            continue

        catalog_issue, issue_status = resolve_catalog_issue(
            catalog_run=catalog_run,
            source_issue=source_issue,
            create_missing_catalog=create_missing_catalog,
        )

        if issue_status == "conflict":
            result.conflicts += 1
            all_applied = False
            continue
        if catalog_issue is None:
            result.missing_catalog_targets += 1
            all_applied = False
            continue

        if issue_status == "created":
            result.issues_created += 1
        else:
            result.issues_linked_existing += 1

        issue_link, link_status = upsert_issue_source_link(
            catalog_issue=catalog_issue,
            catalog_run=catalog_run,
            source_issue=source_issue,
            source_volume=candidate.comicvine_volume,
            run_source=run_source,
            now=now,
        )

        if link_status == "conflict":
            result.conflicts += 1
            all_applied = False
            continue
        if link_status == "created":
            result.issue_source_links_created += 1
        elif link_status == "updated":
            result.issue_source_links_updated += 1

        if update_catalog_issue_from_source(
            catalog_issue=catalog_issue,
            source_issue=source_issue,
            overwrite=update_existing_catalog,
        ):
            result.issues_updated += 1

    return all_applied


def resolve_catalog_issue(*, catalog_run, source_issue, create_missing_catalog):
    source_link = MarvelCatalogIssueSource.objects.filter(
        comicvine_issue=source_issue
    ).first()
    if source_link:
        if source_link.catalog_run_id != catalog_run.id:
            return None, "conflict"
        return source_link.catalog_issue, "existing"

    issue_number = clean_issue_number(source_issue.issue_number)
    matching = list(
        ComicIssue.objects.filter(run=catalog_run, issue_number=issue_number)
    )
    if len(matching) > 1:
        return None, "conflict"
    if matching:
        return matching[0], "existing"
    if not create_missing_catalog:
        return None, "missing"

    catalog_issue = ComicIssue.objects.create(
        run=catalog_run,
        issue_number=issue_number,
        title=clean_html_text(source_issue.issue_title),
        cover_date=source_issue.cover_date,
        store_date=source_issue.store_date,
        description=clean_html_text(source_issue.description),
    )
    update_image_fields(
        target=catalog_issue,
        source=source_issue,
        source_prefix="comicvine_",
        overwrite=True,
    )
    catalog_issue.save()
    return catalog_issue, "created"


def upsert_issue_source_link(
    *,
    catalog_issue,
    catalog_run,
    source_issue,
    source_volume,
    run_source,
    now,
):
    by_source = MarvelCatalogIssueSource.objects.filter(
        comicvine_issue=source_issue
    ).first()
    by_catalog = MarvelCatalogIssueSource.objects.filter(
        catalog_issue=catalog_issue
    ).first()
    if by_source and by_catalog and by_source.id != by_catalog.id:
        return None, "conflict"

    link = by_source or by_catalog
    values = {
        "catalog_issue": catalog_issue,
        "catalog_run": catalog_run,
        "comicvine_issue": source_issue,
        "comicvine_volume": source_volume,
        "run_source": run_source,
        "source_issue_date_last_updated": source_issue.date_last_updated,
        "last_processed_at": now,
        "source_changed_at": None,
    }

    if link is None:
        return MarvelCatalogIssueSource.objects.create(confirmed_at=now, **values), "created"

    if (
        link.catalog_issue_id != catalog_issue.id
        or link.catalog_run_id != catalog_run.id
        or link.comicvine_issue_id != source_issue.id
        or link.comicvine_volume_id != source_volume.id
    ):
        return link, "conflict"

    update_fields = assign_changed_fields(link, values)
    if update_fields:
        link.save(update_fields=dedupe(update_fields))
        return link, "updated"
    return link, "unchanged"


def update_catalog_issue_from_source(*, catalog_issue, source_issue, overwrite):
    values = {
        "issue_number": clean_issue_number(source_issue.issue_number),
        "title": clean_html_text(source_issue.issue_title),
        "cover_date": source_issue.cover_date,
        "store_date": source_issue.store_date,
        "description": clean_html_text(source_issue.description),
    }
    update_fields = update_source_fields(catalog_issue, values, overwrite=overwrite)
    update_fields.extend(
        update_image_fields(
            target=catalog_issue,
            source=source_issue,
            source_prefix="comicvine_",
            overwrite=overwrite,
        )
    )
    if not update_fields:
        return False
    catalog_issue.save(update_fields=dedupe(update_fields))
    return True


def mark_candidate_applied(*, candidate, catalog_run, now):
    values = {
        "catalog_run": catalog_run,
        "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED,
        "catalog_applied_at": now,
    }
    update_fields = assign_changed_fields(candidate, values)
    if update_fields:
        candidate.save(update_fields=dedupe(update_fields))


def update_source_fields(instance, values, *, overwrite):
    update_fields = []
    for field_name, source_value in values.items():
        if source_value in (None, ""):
            continue
        current_value = getattr(instance, field_name)
        current_blank = current_value in (None, "")
        if current_blank or (overwrite and current_value != source_value):
            setattr(instance, field_name, source_value)
            update_fields.append(field_name)
    return update_fields


def update_image_fields(*, target, source, source_prefix, overwrite):
    update_fields = []
    for suffix in (
        "image_icon_url",
        "image_medium_url",
        "image_screen_url",
        "image_screen_large_url",
        "image_small_url",
        "image_super_url",
        "image_thumb_url",
        "image_tiny_url",
        "image_original_url",
        "image_tags",
    ):
        source_field = f"{source_prefix}{suffix}"
        source_value = getattr(source, source_field, "")
        if source_value in (None, ""):
            continue
        current_value = getattr(target, suffix)
        if current_value in (None, "") or (overwrite and current_value != source_value):
            setattr(target, suffix, source_value)
            update_fields.append(suffix)

    display_url = clean_text(getattr(source, "display_image_url", "")) or clean_text(
        getattr(source, f"{source_prefix}image_original_url", "")
    )
    if display_url and (
        not target.display_image_url
        or (overwrite and target.display_image_url != display_url)
    ):
        target.display_image_url = display_url
        target.display_image_source = target.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
        update_fields.extend(["display_image_url", "display_image_source"])

    return update_fields


def map_run_status(source_status):
    if source_status in {
        "likely_ongoing",
        "manual_ongoing",
    }:
        return ComicRun.STATUS_ONGOING
    if source_status in {
        "likely_ended",
        "manual_ended",
    }:
        return ComicRun.STATUS_ENDED
    return ComicRun.STATUS_UNKNOWN


def issue_sort_key(issue):
    parsed_number = parse_standard_issue_number(issue.issue_number)
    return (
        parsed_number is None,
        parsed_number if parsed_number is not None else 0,
        normalize_issue_number(issue.issue_number),
        issue.comicvine_id or 0,
    )


def assign_changed_fields(instance, values):
    changed_fields = []
    for field_name, value in values.items():
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed_fields.append(field_name)
    return changed_fields


def dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def print_result(command, result, *, dry_run):
    prefix = "Would " if dry_run else ""
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Run complete."))
    command.stdout.write("=" * 60)
    command.stdout.write(f"Confirmed run candidates seen: {result.candidates_seen}")
    command.stdout.write(f"Stale candidates refused: {result.stale_candidates}")
    command.stdout.write(f"{prefix}runs created: {result.runs_created}")
    command.stdout.write(f"{prefix}runs linked existing: {result.runs_linked_existing}")
    command.stdout.write(f"{prefix}runs updated: {result.runs_updated}")
    command.stdout.write(f"{prefix}run source links created: {result.run_source_links_created}")
    command.stdout.write(f"{prefix}run source links updated: {result.run_source_links_updated}")
    command.stdout.write(f"Issues seen: {result.issues_seen}")
    command.stdout.write(f"{prefix}issues created: {result.issues_created}")
    command.stdout.write(f"{prefix}issues linked existing: {result.issues_linked_existing}")
    command.stdout.write(f"{prefix}issues updated: {result.issues_updated}")
    command.stdout.write(f"{prefix}issue source links created: {result.issue_source_links_created}")
    command.stdout.write(f"{prefix}issue source links updated: {result.issue_source_links_updated}")
    command.stdout.write(f"Issues skipped: {result.issues_skipped}")
    command.stdout.write(f"{prefix}candidates marked applied: {result.candidates_marked_applied}")
    command.stdout.write(f"Missing catalog targets: {result.missing_catalog_targets}")
    command.stdout.write(f"Conflicts: {result.conflicts}")
    command.stdout.write("Collected-volume candidates selected: 0")
    command.stdout.write("ComicVolume or ComicVolumeIssue rows changed: 0")

    if dry_run:
        command.stdout.write("")
        command.stdout.write("Dry run only. No database changes were saved.")
