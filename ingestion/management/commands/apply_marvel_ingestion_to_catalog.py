from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import (
    ComicIssue,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)
from ingestion.models import (
    ComicVineCollectedEditionCandidate,
    ComicVineVolumeCandidate,
    MarvelCatalogIssueSource,
    MarvelCatalogRunSource,
    MarvelCatalogVolumeSource,
)


PUBLISHER_NAME = "Marvel"


@dataclass
class CandidateSelection:
    run_candidates: list
    collected_candidates: list


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

    volume_issue_links_created: int = 0
    volume_issue_links_updated: int = 0
    volume_issue_links_deleted: int = 0

    candidates_marked_applied: int = 0
    missing_catalog_targets: int = 0
    conflicts: int = 0
    skipped: int = 0


class Command(BaseCommand):
    help = (
        "Apply confirmed Marvel run and per-issue collected-edition candidates "
        "to catalog rows, including explicit collected issue memberships."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            action="append",
            dest="comicvine_volume_ids",
            help=(
                "Optional Comic Vine source volume ID to apply. Can be supplied "
                "multiple times. Required referenced runs are included automatically."
            ),
        )
        parser.add_argument(
            "--comicvine-issue-id",
            type=int,
            action="append",
            dest="comicvine_issue_ids",
            help=(
                "Optional collected-edition Comic Vine issue ID to apply. Can be "
                "supplied multiple times."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help=(
                "Optional maximum number of directly selected candidates. Required "
                "run dependencies do not count against this limit."
            ),
        )
        parser.add_argument(
            "--create-missing-catalog",
            action="store_true",
            help=(
                "Create missing catalog runs, issues, and collected volumes. Without "
                "this flag, only exact existing catalog rows are linked."
            ),
        )
        parser.add_argument(
            "--update-existing-catalog",
            action="store_true",
            help=(
                "Update populated catalog fields from current source data. Without "
                "this flag, only blank existing fields are filled."
            ),
        )
        parser.add_argument(
            "--skip-collected-volumes",
            action="store_true",
            help="Apply confirmed runs and monthly issues only.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Summarize what would happen without saving database changes.",
        )

    def handle(self, *args, **options):
        comicvine_volume_ids = options["comicvine_volume_ids"] or []
        comicvine_issue_ids = options["comicvine_issue_ids"] or []
        limit = options["limit"]
        create_missing_catalog = options["create_missing_catalog"]
        update_existing_catalog = options["update_existing_catalog"]
        skip_collected_volumes = options["skip_collected_volumes"]
        dry_run = options["dry_run"]

        validate_options(
            comicvine_volume_ids=comicvine_volume_ids,
            comicvine_issue_ids=comicvine_issue_ids,
            limit=limit,
        )
        selection = list_selected_candidates(
            comicvine_volume_ids=comicvine_volume_ids,
            comicvine_issue_ids=comicvine_issue_ids,
            limit=limit,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Apply Marvel ingestion to catalog"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")
        self.stdout.write("Source: confirmed local ingestion candidates")
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
        self.stdout.write(
            f"Run candidates selected: {len(selection.run_candidates)}"
        )
        self.stdout.write(
            f"Collected candidates selected: {len(selection.collected_candidates)}"
        )

        if comicvine_volume_ids:
            self.stdout.write(
                "Selected Comic Vine volume IDs: "
                + ", ".join(str(value) for value in comicvine_volume_ids)
            )
        else:
            self.stdout.write("Selected Comic Vine volume IDs: all ready candidates")

        if comicvine_issue_ids:
            self.stdout.write(
                "Selected collected-edition issue IDs: "
                + ", ".join(str(value) for value in comicvine_issue_ids)
            )
        else:
            self.stdout.write("Selected collected-edition issue IDs: all ready candidates")

        self.stdout.write(f"Limit: {limit if limit is not None else 'none'}")

        with transaction.atomic():
            publisher = get_or_create_marvel_publisher()
            result = apply_candidates(
                selection=selection,
                publisher=publisher,
                create_missing_catalog=create_missing_catalog,
                update_existing_catalog=update_existing_catalog,
                skip_collected_volumes=skip_collected_volumes,
            )

            if dry_run:
                transaction.set_rollback(True)

        print_result(self, result, dry_run=dry_run)


def validate_options(*, comicvine_volume_ids, comicvine_issue_ids, limit):
    if any(value < 1 for value in comicvine_volume_ids):
        raise CommandError("--comicvine-volume-id values must be positive integers.")

    if any(value < 1 for value in comicvine_issue_ids):
        raise CommandError("--comicvine-issue-id values must be positive integers.")

    if limit is not None and limit < 1:
        raise CommandError("--limit must be at least 1 when provided.")


def list_selected_candidates(*, comicvine_volume_ids, comicvine_issue_ids, limit):
    allowed_catalog_statuses = [
        ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
        ComicVineVolumeCandidate.CATALOG_STATUS_UPDATE_AVAILABLE,
        ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED,
    ]
    run_base = (
        ComicVineVolumeCandidate.objects.select_related(
            "comicvine_volume",
            "catalog_run",
        )
        .filter(
            publisher_name__iexact=PUBLISHER_NAME,
            analysis_status=(
                ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN
            ),
            catalog_status__in=allowed_catalog_statuses,
        )
        .order_by(
            "normalized_title",
            "start_year",
            "comicvine_volume__comicvine_id",
        )
    )
    collected_base = (
        ComicVineCollectedEditionCandidate.objects.select_related(
            "comicvine_issue",
            "source_collection_volume",
            "proposed_parent_run_candidate__comicvine_volume",
            "catalog_volume",
        )
        .filter(
            publisher_name__iexact=PUBLISHER_NAME,
            analysis_status=(
                ComicVineCollectedEditionCandidate
                .ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
            ),
            catalog_status__in=allowed_catalog_statuses,
        )
        .order_by(
            "source_collection_volume__name",
            "release_date",
            "volume_number",
            "comicvine_issue__comicvine_id",
        )
    )

    filters_supplied = bool(comicvine_volume_ids or comicvine_issue_ids)

    if filters_supplied:
        primary_runs = list(
            run_base.filter(
                comicvine_volume__comicvine_id__in=comicvine_volume_ids,
            )
        )
        collected_filter = Q()

        if comicvine_volume_ids:
            collected_filter |= Q(
                source_collection_volume__comicvine_id__in=comicvine_volume_ids,
            )

        if comicvine_issue_ids:
            collected_filter |= Q(
                comicvine_issue__comicvine_id__in=comicvine_issue_ids,
            )

        primary_collected = list(collected_base.filter(collected_filter))
    else:
        primary_runs = list(run_base)
        primary_collected = list(collected_base)

    if limit is not None:
        combined = [
            (candidate.normalized_title, 0, candidate)
            for candidate in primary_runs
        ] + [
            (
                clean_text(candidate.source_collection_volume.name).casefold(),
                1,
                candidate,
            )
            for candidate in primary_collected
        ]
        combined.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2].pk,
            )
        )
        combined = combined[:limit]
        primary_runs = [item[2] for item in combined if item[1] == 0]
        primary_collected = [item[2] for item in combined if item[1] == 1]

    required_run_candidate_ids = set()

    for candidate in primary_collected:
        if candidate.proposed_parent_run_candidate_id:
            required_run_candidate_ids.add(candidate.proposed_parent_run_candidate_id)

        required_run_candidate_ids.update(
            candidate.source_issue_links.values_list(
                "source_run_candidate_id",
                flat=True,
            )
        )

    run_candidates_by_id = {candidate.id: candidate for candidate in primary_runs}

    for candidate in run_base.filter(id__in=required_run_candidate_ids):
        run_candidates_by_id.setdefault(candidate.id, candidate)

    run_candidates = sorted(
        run_candidates_by_id.values(),
        key=lambda candidate: (
            candidate.normalized_title,
            candidate.start_year,
            candidate.comicvine_volume.comicvine_id,
        ),
    )

    return CandidateSelection(
        run_candidates=run_candidates,
        collected_candidates=primary_collected,
    )


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
    selection,
    publisher,
    create_missing_catalog,
    update_existing_catalog,
    skip_collected_volumes,
):
    result = ApplyResult()

    for candidate in selection.run_candidates:
        result.candidates_seen += 1
        apply_run_candidate(
            candidate=candidate,
            publisher=publisher,
            create_missing_catalog=create_missing_catalog,
            update_existing_catalog=update_existing_catalog,
            result=result,
        )

    if skip_collected_volumes:
        result.skipped += len(selection.collected_candidates)
        return result

    for candidate in selection.collected_candidates:
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
    else:
        result.runs_linked_existing += 1

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
        update_existing_catalog=update_existing_catalog,
    ):
        result.runs_updated += 1

    issues_applied = apply_run_issues(
        candidate=candidate,
        catalog_run=catalog_run,
        run_source=run_source,
        create_missing_catalog=create_missing_catalog,
        update_existing_catalog=update_existing_catalog,
        result=result,
        now=now,
    )

    if issues_applied and mark_run_candidate_applied(
        candidate=candidate,
        catalog_run=catalog_run,
        now=now,
    ):
        result.candidates_marked_applied += 1


def resolve_catalog_run(*, candidate, publisher, create_missing_catalog):
    source_link, source_link_conflict = find_run_source_link(candidate)

    if source_link_conflict:
        return None, "conflict"

    if source_link is not None:
        if (
            candidate.catalog_run_id
            and candidate.catalog_run_id != source_link.catalog_run_id
        ):
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


def find_run_source_link(candidate):
    links = list(
        MarvelCatalogRunSource.objects.filter(
            Q(candidate=candidate) | Q(comicvine_volume=candidate.comicvine_volume)
        ).distinct()
    )

    if len(links) > 1:
        return None, True

    return (links[0] if links else None), False


def upsert_run_source_link(*, candidate, catalog_run, now):
    existing_link, conflict = find_run_source_link(candidate)

    if conflict:
        return None, "conflict"

    target_link = MarvelCatalogRunSource.objects.filter(
        catalog_run=catalog_run,
    ).exclude(candidate=candidate).first()

    if target_link is not None:
        return target_link, "conflict"

    link_data = {
        "catalog_run": catalog_run,
        "comicvine_volume": candidate.comicvine_volume,
        "candidate": candidate,
        "source_volume_date_last_updated": candidate.source_volume_date_last_updated,
        "source_fingerprint": candidate.source_fingerprint,
        "last_processed_at": now,
    }

    if existing_link is None:
        return (
            MarvelCatalogRunSource.objects.create(
                confirmed_at=now,
                **link_data,
            ),
            "created",
        )

    if (
        existing_link.catalog_run_id != catalog_run.id
        or existing_link.comicvine_volume_id != candidate.comicvine_volume_id
        or existing_link.candidate_id != candidate.id
    ):
        return existing_link, "conflict"

    update_fields = assign_changed_fields(existing_link, link_data)

    if existing_link.source_changed_at is not None:
        existing_link.source_changed_at = None
        update_fields.append("source_changed_at")

    if update_fields:
        existing_link.save(update_fields=dedupe(update_fields))
        return existing_link, "updated"

    return existing_link, "unchanged"


def update_catalog_run_from_source(
    *,
    catalog_run,
    candidate,
    update_existing_catalog,
):
    update_fields = fill_catalog_fields(
        catalog_object=catalog_run,
        field_values={
            "first_issue_date": candidate.first_issue_date,
            "last_issue_date": candidate.last_issue_date,
            "issue_count": candidate.source_issue_count,
            "description": clean_text(candidate.comicvine_volume.description),
        },
        update_existing_catalog=update_existing_catalog,
    )
    update_fields.extend(
        fill_image_fields_from_volume_source(
            catalog_object=catalog_run,
            source_volume=candidate.comicvine_volume,
            update_existing_catalog=update_existing_catalog,
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
    create_missing_catalog,
    update_existing_catalog,
    result,
    now,
):
    source_issues = candidate.comicvine_volume.issues.order_by(
        "store_date",
        "cover_date",
        "issue_number",
        "comicvine_id",
        "id",
    )
    all_applied = source_issues.exists()

    for source_issue in source_issues:
        result.issues_seen += 1

        if not clean_text(source_issue.issue_number):
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

        if issue_link is None:
            all_applied = False
            continue

        if update_catalog_issue_from_source(
            catalog_issue=catalog_issue,
            source_issue=source_issue,
            update_existing_catalog=update_existing_catalog,
        ):
            result.issues_updated += 1

    return all_applied


def resolve_catalog_issue(*, catalog_run, source_issue, create_missing_catalog):
    source_link = MarvelCatalogIssueSource.objects.filter(
        comicvine_issue=source_issue,
    ).first()

    if source_link is not None:
        if source_link.catalog_run_id != catalog_run.id:
            return None, "conflict"

        return source_link.catalog_issue, "existing"

    issue_number = clean_text(source_issue.issue_number)
    matching_issues = list(
        ComicIssue.objects.filter(
            run=catalog_run,
            issue_number=issue_number,
        )
    )

    if len(matching_issues) == 1:
        return matching_issues[0], "existing"

    if len(matching_issues) > 1:
        return None, "conflict"

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
    link_by_catalog = MarvelCatalogIssueSource.objects.filter(
        catalog_issue=catalog_issue,
    ).first()

    if (
        link_by_source is not None
        and link_by_catalog is not None
        and link_by_source.id != link_by_catalog.id
    ):
        return None, "conflict"

    existing_link = link_by_source or link_by_catalog

    if existing_link is not None and (
        existing_link.catalog_issue_id != catalog_issue.id
        or existing_link.catalog_run_id != catalog_run.id
        or existing_link.comicvine_issue_id != source_issue.id
        or existing_link.comicvine_volume_id != source_volume.id
    ):
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
        return (
            MarvelCatalogIssueSource.objects.create(
                confirmed_at=now,
                **link_data,
            ),
            "created",
        )

    update_fields = assign_changed_fields(existing_link, link_data)

    if existing_link.source_changed_at is not None:
        existing_link.source_changed_at = None
        update_fields.append("source_changed_at")

    if update_fields:
        existing_link.save(update_fields=dedupe(update_fields))
        return existing_link, "updated"

    return existing_link, "unchanged"


def update_catalog_issue_from_source(
    *,
    catalog_issue,
    source_issue,
    update_existing_catalog,
):
    update_fields = fill_catalog_fields(
        catalog_object=catalog_issue,
        field_values={
            "title": clean_text(source_issue.issue_title),
            "cover_date": source_issue.cover_date,
            "store_date": source_issue.store_date,
            "description": clean_text(source_issue.description),
        },
        update_existing_catalog=update_existing_catalog,
    )
    update_fields.extend(
        fill_image_fields_from_issue_source(
            catalog_object=catalog_issue,
            source_issue=source_issue,
            update_existing_catalog=update_existing_catalog,
        )
    )

    if not update_fields:
        return False

    catalog_issue.save(update_fields=dedupe(update_fields))
    return True


def mark_run_candidate_applied(*, candidate, catalog_run, now):
    update_fields = []

    if candidate.catalog_run_id != catalog_run.id:
        candidate.catalog_run = catalog_run
        update_fields.append("catalog_run")

    if candidate.catalog_status != candidate.CATALOG_STATUS_APPLIED:
        candidate.catalog_status = candidate.CATALOG_STATUS_APPLIED
        update_fields.append("catalog_status")

    candidate.catalog_applied_at = now
    update_fields.append("catalog_applied_at")
    candidate.save(update_fields=dedupe(update_fields))
    return True


def apply_collected_volume_candidate(
    *,
    candidate,
    publisher,
    create_missing_catalog,
    update_existing_catalog,
    result,
):
    now = timezone.now()
    parent_run = resolve_parent_catalog_run(candidate)

    if parent_run is None:
        result.missing_catalog_targets += 1
        return

    resolved_memberships, membership_status = preflight_collected_memberships(
        candidate
    )

    if membership_status == "conflict":
        result.conflicts += 1
        return

    if membership_status == "missing":
        result.missing_catalog_targets += 1
        return

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
    else:
        result.volumes_linked_existing += 1

    volume_source, link_status = upsert_volume_source_link(
        candidate=candidate,
        catalog_volume=catalog_volume,
        catalog_run=parent_run,
        now=now,
    )

    if link_status == "conflict":
        result.conflicts += 1
        return

    if link_status == "created":
        result.volume_source_links_created += 1
    elif link_status == "updated":
        result.volume_source_links_updated += 1

    if volume_source is None:
        result.conflicts += 1
        return

    if update_catalog_volume_from_source(
        catalog_volume=catalog_volume,
        candidate=candidate,
        parent_run=parent_run,
        update_existing_catalog=update_existing_catalog,
    ):
        result.volumes_updated += 1

    sync_result = sync_catalog_volume_issues(
        candidate=candidate,
        catalog_volume=catalog_volume,
        resolved_memberships=resolved_memberships,
    )
    result.volume_issue_links_created += sync_result["created"]
    result.volume_issue_links_updated += sync_result["updated"]
    result.volume_issue_links_deleted += sync_result["deleted"]

    if mark_collected_candidate_applied(
        candidate=candidate,
        catalog_volume=catalog_volume,
        now=now,
    ):
        result.candidates_marked_applied += 1


def resolve_parent_catalog_run(candidate):
    parent_candidate = candidate.proposed_parent_run_candidate

    if parent_candidate is None:
        return None

    source_link, conflict = find_run_source_link(parent_candidate)

    if conflict or source_link is None:
        return None

    if (
        parent_candidate.catalog_run_id
        and parent_candidate.catalog_run_id != source_link.catalog_run_id
    ):
        return None

    return source_link.catalog_run


def preflight_collected_memberships(candidate):
    memberships = list(
        candidate.source_issue_links.select_related(
            "source_issue",
            "source_run_candidate__comicvine_volume",
        ).order_by("issue_order", "id")
    )

    if candidate.source_reference_count == 0:
        if memberships:
            return [], "conflict"
        return [], "ready"

    if not memberships or len(memberships) != candidate.source_issue_count:
        return [], "missing"

    resolved = []

    for membership in memberships:
        run_source, conflict = find_run_source_link(membership.source_run_candidate)

        if conflict or run_source is None:
            return [], "missing"

        issue_source = MarvelCatalogIssueSource.objects.filter(
            comicvine_issue=membership.source_issue,
        ).select_related("catalog_issue").first()

        if issue_source is None:
            return [], "missing"

        if (
            issue_source.catalog_run_id != run_source.catalog_run_id
            or issue_source.run_source_id != run_source.id
        ):
            return [], "conflict"

        resolved.append((membership, issue_source.catalog_issue))

    return resolved, "ready"


def resolve_catalog_volume(
    *,
    candidate,
    publisher,
    parent_run,
    create_missing_catalog,
):
    source_link, source_link_conflict = find_volume_source_link(candidate)

    if source_link_conflict:
        return None, "conflict"

    if source_link is not None:
        if (
            candidate.catalog_volume_id
            and candidate.catalog_volume_id != source_link.catalog_volume_id
        ):
            return None, "conflict"

        if source_link.catalog_run_id != parent_run.id:
            return None, "conflict"

        return source_link.catalog_volume, "existing"

    if candidate.catalog_volume_id:
        if candidate.catalog_volume.run_id != parent_run.id:
            return None, "conflict"
        return candidate.catalog_volume, "existing"

    title = derive_catalog_volume_title(candidate, parent_run)
    matching_volumes = list(
        ComicVolume.objects.filter(
            publisher=publisher,
            run=parent_run,
            title=title,
            volume_number=candidate.volume_number,
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
        title=title,
        volume_number=candidate.volume_number,
        first_issue_number=(
            candidate.primary_first_issue_number
            if candidate.source_reference_count
            else ""
        ),
        last_issue_number=(
            candidate.primary_last_issue_number
            if candidate.source_reference_count
            else ""
        ),
        release_date=candidate.release_date,
        issue_count=(candidate.source_issue_count or None),
        description=clean_text(candidate.comicvine_issue.description),
    )
    copy_image_fields_from_issue_source(catalog_volume, candidate.comicvine_issue)
    catalog_volume.save()
    return catalog_volume, "created"


def derive_catalog_volume_title(candidate, parent_run):
    title = clean_text(candidate.title)

    if not title and not clean_text(candidate.volume_number):
        title = clean_text(candidate.source_title)

    run_title = clean_text(parent_run.title)

    if title.casefold() == run_title.casefold():
        return ""

    if title.casefold().startswith(run_title.casefold()):
        suffix = title[len(run_title):].lstrip(" :;-–—")
        if suffix:
            return suffix

    return title


def find_volume_source_link(candidate):
    links = list(
        MarvelCatalogVolumeSource.objects.filter(
            Q(candidate=candidate) | Q(comicvine_issue=candidate.comicvine_issue)
        ).distinct()
    )

    if len(links) > 1:
        return None, True

    return (links[0] if links else None), False


def upsert_volume_source_link(
    *,
    candidate,
    catalog_volume,
    catalog_run,
    now,
):
    existing_link, conflict = find_volume_source_link(candidate)

    if conflict:
        return None, "conflict"

    target_link = MarvelCatalogVolumeSource.objects.filter(
        catalog_volume=catalog_volume,
    ).exclude(candidate=candidate).first()

    if target_link is not None:
        return target_link, "conflict"

    link_data = {
        "catalog_volume": catalog_volume,
        "catalog_run": catalog_run,
        "comicvine_issue": candidate.comicvine_issue,
        "candidate": candidate,
        "source_issue_date_last_updated": candidate.source_issue_date_last_updated,
        "source_fingerprint": candidate.source_fingerprint,
        "last_processed_at": now,
    }

    if existing_link is None:
        return (
            MarvelCatalogVolumeSource.objects.create(
                confirmed_at=now,
                **link_data,
            ),
            "created",
        )

    if (
        existing_link.catalog_volume_id != catalog_volume.id
        or existing_link.catalog_run_id != catalog_run.id
        or existing_link.comicvine_issue_id != candidate.comicvine_issue_id
        or existing_link.candidate_id != candidate.id
    ):
        return existing_link, "conflict"

    update_fields = assign_changed_fields(existing_link, link_data)

    if existing_link.source_changed_at is not None:
        existing_link.source_changed_at = None
        update_fields.append("source_changed_at")

    if update_fields:
        existing_link.save(update_fields=dedupe(update_fields))
        return existing_link, "updated"

    return existing_link, "unchanged"


def update_catalog_volume_from_source(
    *,
    catalog_volume,
    candidate,
    parent_run,
    update_existing_catalog,
):
    explicit_source = candidate.source_reference_count > 0
    update_fields = fill_catalog_fields(
        catalog_object=catalog_volume,
        field_values={
            "title": derive_catalog_volume_title(candidate, parent_run),
            "volume_number": candidate.volume_number,
            "first_issue_number": (
                candidate.primary_first_issue_number if explicit_source else ""
            ),
            "last_issue_number": (
                candidate.primary_last_issue_number if explicit_source else ""
            ),
            "release_date": candidate.release_date,
            "issue_count": candidate.source_issue_count if explicit_source else None,
            "description": clean_text(candidate.comicvine_issue.description),
        },
        update_existing_catalog=update_existing_catalog,
    )
    update_fields.extend(
        fill_image_fields_from_issue_source(
            catalog_object=catalog_volume,
            source_issue=candidate.comicvine_issue,
            update_existing_catalog=update_existing_catalog,
        )
    )

    if not update_fields:
        return False

    catalog_volume.save(update_fields=dedupe(update_fields))
    return True


def sync_catalog_volume_issues(
    *,
    candidate,
    catalog_volume,
    resolved_memberships,
):
    result = {"created": 0, "updated": 0, "deleted": 0}

    if candidate.source_reference_count == 0:
        return result

    desired_issue_ids = set()

    for membership, catalog_issue in resolved_memberships:
        desired_issue_ids.add(catalog_issue.id)
        volume_issue, created = ComicVolumeIssue.objects.get_or_create(
            volume=catalog_volume,
            issue=catalog_issue,
            defaults={"issue_order": membership.issue_order},
        )

        if created:
            result["created"] += 1
        elif volume_issue.issue_order != membership.issue_order:
            volume_issue.issue_order = membership.issue_order
            volume_issue.save(update_fields=["issue_order"])
            result["updated"] += 1

    stale_links = ComicVolumeIssue.objects.filter(volume=catalog_volume).exclude(
        issue_id__in=desired_issue_ids,
    )
    result["deleted"] = stale_links.count()
    stale_links.delete()
    return result


def mark_collected_candidate_applied(*, candidate, catalog_volume, now):
    update_fields = []

    if candidate.catalog_volume_id != catalog_volume.id:
        candidate.catalog_volume = catalog_volume
        update_fields.append("catalog_volume")

    if candidate.catalog_status != candidate.CATALOG_STATUS_APPLIED:
        candidate.catalog_status = candidate.CATALOG_STATUS_APPLIED
        update_fields.append("catalog_status")

    candidate.catalog_applied_at = now
    update_fields.append("catalog_applied_at")
    candidate.save(update_fields=dedupe(update_fields))
    return True


def fill_catalog_fields(
    *,
    catalog_object,
    field_values,
    update_existing_catalog,
):
    changed_fields = []

    for field_name, source_value in field_values.items():
        if source_value in [None, ""]:
            continue

        current_value = getattr(catalog_object, field_name)

        if update_existing_catalog or current_value in [None, ""]:
            if current_value != source_value:
                setattr(catalog_object, field_name, source_value)
                changed_fields.append(field_name)

    return changed_fields


def assign_changed_fields(instance, field_values):
    update_fields = []

    for field_name, new_value in field_values.items():
        if getattr(instance, field_name) != new_value:
            setattr(instance, field_name, new_value)
            update_fields.append(field_name)

    return update_fields


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
    changed_fields = copy_image_field_mapping(
        catalog_object=catalog_object,
        source_object=source_volume,
        source_to_target=source_to_target,
        update_existing_catalog=update_existing_catalog,
    )

    if clean_text(catalog_object.display_image_url) and (
        catalog_object.display_image_source
        != catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
    ):
        catalog_object.display_image_source = (
            catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
        )
        changed_fields.append("display_image_source")

    return changed_fields


def copy_image_fields_from_issue_source(catalog_object, source_issue):
    fill_image_fields_from_issue_source(
        catalog_object=catalog_object,
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
    changed_fields = copy_image_field_mapping(
        catalog_object=catalog_object,
        source_object=source_issue,
        source_to_target=source_to_target,
        update_existing_catalog=update_existing_catalog,
    )

    if clean_text(catalog_object.image_original_url) and not clean_text(
        catalog_object.display_image_url
    ):
        catalog_object.display_image_url = catalog_object.image_original_url
        changed_fields.append("display_image_url")

    if clean_text(catalog_object.display_image_url) and (
        catalog_object.display_image_source
        != catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
    ):
        catalog_object.display_image_source = (
            catalog_object.DISPLAY_IMAGE_SOURCE_SOURCE_DATA
        )
        changed_fields.append("display_image_source")

    return changed_fields


def copy_image_field_mapping(
    *,
    catalog_object,
    source_object,
    source_to_target,
    update_existing_catalog,
):
    changed_fields = []

    for source_field, target_field in source_to_target.items():
        source_value = clean_text(getattr(source_object, source_field, ""))

        if not source_value:
            continue

        current_value = getattr(catalog_object, target_field)

        if update_existing_catalog or not current_value:
            if current_value != source_value:
                setattr(catalog_object, target_field, source_value)
                changed_fields.append(target_field)

    return changed_fields


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


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
    command.stdout.write(f"Candidates seen: {result.candidates_seen}")
    command.stdout.write("")
    command.stdout.write(f"{prefix}runs created: {result.runs_created}")
    command.stdout.write(f"{prefix}runs linked existing: {result.runs_linked_existing}")
    command.stdout.write(f"{prefix}runs updated: {result.runs_updated}")
    command.stdout.write(
        f"{prefix}run source links created: {result.run_source_links_created}"
    )
    command.stdout.write(
        f"{prefix}run source links updated: {result.run_source_links_updated}"
    )
    command.stdout.write("")
    command.stdout.write(f"Issues seen: {result.issues_seen}")
    command.stdout.write(f"{prefix}issues created: {result.issues_created}")
    command.stdout.write(
        f"{prefix}issues linked existing: {result.issues_linked_existing}"
    )
    command.stdout.write(f"{prefix}issues updated: {result.issues_updated}")
    command.stdout.write(
        f"{prefix}issue source links created: {result.issue_source_links_created}"
    )
    command.stdout.write(
        f"{prefix}issue source links updated: {result.issue_source_links_updated}"
    )
    command.stdout.write(f"Issues skipped: {result.issues_skipped}")
    command.stdout.write("")
    command.stdout.write(f"{prefix}volumes created: {result.volumes_created}")
    command.stdout.write(
        f"{prefix}volumes linked existing: {result.volumes_linked_existing}"
    )
    command.stdout.write(f"{prefix}volumes updated: {result.volumes_updated}")
    command.stdout.write(
        f"{prefix}volume source links created: {result.volume_source_links_created}"
    )
    command.stdout.write(
        f"{prefix}volume source links updated: {result.volume_source_links_updated}"
    )
    command.stdout.write(
        f"{prefix}volume issue links created: {result.volume_issue_links_created}"
    )
    command.stdout.write(
        f"{prefix}volume issue links updated: {result.volume_issue_links_updated}"
    )
    command.stdout.write(
        f"{prefix}volume issue links deleted: {result.volume_issue_links_deleted}"
    )
    command.stdout.write("")
    command.stdout.write(
        f"{prefix}candidates marked applied: {result.candidates_marked_applied}"
    )
    command.stdout.write(f"Missing catalog targets: {result.missing_catalog_targets}")
    command.stdout.write(f"Conflicts: {result.conflicts}")
    command.stdout.write(f"Skipped: {result.skipped}")

    if dry_run:
        command.stdout.write("")
        command.stdout.write("Dry run only. No database changes were saved.")