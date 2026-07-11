import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from html import unescape

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from comicvine.models import ComicVineIssue, ComicVineVolume
from ingestion.models import (
    ComicVineCollectedEditionCandidate,
    ComicVineCollectedEditionIssue,
    ComicVineVolumeCandidate,
)


PUBLISHER_NAME = "Marvel"
ANALYSIS_VERSION = 3

COLLECTION_TITLE_PATTERN = re.compile(
    r"^(?:vol(?:ume)?\.?\s*\d+|tpb\b|hardcover\b|hc\b)",
    flags=re.IGNORECASE,
)
VOLUME_TITLE_PATTERN = re.compile(
    r"^(?:vol(?:ume)?\.?)\s*(?P<number>\d+)\s*[:\-–—]?\s*(?P<title>.*)$",
    flags=re.IGNORECASE,
)
REFERENCE_PATTERN = re.compile(
    r"^(?P<title>.+?)"
    r"(?:\s*\((?P<year>\d{4})\))?"
    r"\s*#?\s*(?P<first>\d+)"
    r"(?:\s*[\-–—]\s*#?\s*(?P<last>\d+))?$",
    flags=re.IGNORECASE,
)


@dataclass
class VolumeFacts:
    volume: ComicVineVolume
    issues: list[ComicVineIssue]
    title: str
    normalized_title: str
    start_year: str
    source_issue_count: int
    source_date_type: str
    first_issue_date: object
    last_issue_date: object
    first_issue_number: str
    last_issue_number: str
    source_fingerprint: str
    explicit_collection_issue_ids: set[int] = field(default_factory=set)
    collection_container: bool = False


@dataclass
class ParsedReference:
    raw_text: str
    title: str
    normalized_title: str
    start_year: str
    first_issue_number: str
    last_issue_number: str
    standalone: bool = False


@dataclass
class ResolvedMembership:
    source_issue: ComicVineIssue
    source_run_candidate: ComicVineVolumeCandidate
    issue_order: int
    primary_run: bool
    reference_text: str


@dataclass
class FallbackDecision:
    collection_issue: ComicVineIssue
    parent_run_facts: VolumeFacts | None
    conflict: bool = False


@dataclass
class AnalysisResult:
    source_volumes_seen: int = 0
    source_issues_seen: int = 0
    blank_publisher_volumes_excluded: int = 0

    run_candidates_created: int = 0
    run_candidates_updated: int = 0
    run_candidates_unchanged: int = 0
    confirmed_runs: int = 0
    collection_containers: int = 0
    unresolved_run_sources: int = 0

    collected_candidates_created: int = 0
    collected_candidates_updated: int = 0
    collected_candidates_unchanged: int = 0
    confirmed_collected_volumes: int = 0
    unresolved_collected_volumes: int = 0
    conflicting_collected_volumes: int = 0
    stale_collected_candidates_invalidated: int = 0

    collected_issue_links_created: int = 0
    source_changed: int = 0


class Command(BaseCommand):
    help = (
        "Analyze local Marvel Comic Vine volumes as run sources and individual "
        "Comic Vine issues as collected-edition sources."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            action="append",
            dest="comicvine_volume_ids",
            help=(
                "Optional Comic Vine volume ID to analyze. Can be provided multiple "
                "times. If omitted, all local Marvel volumes are selected."
            ),
        )
        parser.add_argument(
            "--comicvine-issue-id",
            type=int,
            action="append",
            dest="comicvine_issue_ids",
            help=(
                "Optional Comic Vine issue ID for a collected edition. Can be provided "
                "multiple times."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional maximum number of local Marvel source volumes to analyze.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyze and summarize what would happen without saving changes.",
        )

    def handle(self, *args, **options):
        comicvine_volume_ids = options["comicvine_volume_ids"] or []
        comicvine_issue_ids = options["comicvine_issue_ids"] or []
        limit = options["limit"]
        dry_run = options["dry_run"]

        validate_options(
            comicvine_volume_ids=comicvine_volume_ids,
            comicvine_issue_ids=comicvine_issue_ids,
            limit=limit,
        )

        volume_index, blank_publisher_count = build_marvel_volume_index()
        selected_volumes = list_selected_marvel_volumes(
            volume_index=volume_index,
            comicvine_volume_ids=comicvine_volume_ids,
            comicvine_issue_ids=comicvine_issue_ids,
            limit=limit,
        )
        facts_by_volume_id = {}

        def get_facts(volume):
            facts = facts_by_volume_id.get(volume.comicvine_id)
            if facts is None:
                facts = build_volume_facts(volume)
                facts_by_volume_id[volume.comicvine_id] = facts
            return facts

        selected_facts = [get_facts(volume) for volume in selected_volumes]
        fallback_decisions = find_exact_name_date_fallbacks(
            selected_facts=selected_facts,
            volume_index=volume_index,
            get_facts=get_facts,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Analyze Marvel Comic Vine ingestion"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")
        self.stdout.write("Source: local ComicVineVolume and ComicVineIssue rows")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write("Comic Vine API calls: none")
        self.stdout.write(
            "Collected-edition rule: explicit COLLECTING text with exact local resolution"
        )
        self.stdout.write(
            "Fallback rule: one-issue Vol./Volume source inside an exact-name run date range"
        )
        self.stdout.write(f"Local Marvel source volumes selected: {len(selected_facts)}")
        self.stdout.write(
            f"Local volumes excluded because publisher is blank: {blank_publisher_count}"
        )

        if comicvine_volume_ids:
            self.stdout.write(
                "Selected Comic Vine volume IDs: "
                + ", ".join(str(value) for value in comicvine_volume_ids)
            )
        else:
            self.stdout.write("Selected Comic Vine volume IDs: all local Marvel volumes")

        if comicvine_issue_ids:
            self.stdout.write(
                "Selected collected-edition issue IDs: "
                + ", ".join(str(value) for value in comicvine_issue_ids)
            )
        else:
            self.stdout.write("Selected collected-edition issue IDs: all detected")

        self.stdout.write(f"Limit: {limit if limit is not None else 'none'}")

        with transaction.atomic():
            result = analyze_sources(
                selected_facts=selected_facts,
                volume_index=volume_index,
                get_facts=get_facts,
                fallback_decisions=fallback_decisions,
                selected_collection_issue_ids=set(comicvine_issue_ids),
            )
            result.blank_publisher_volumes_excluded = blank_publisher_count

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


def build_marvel_volume_index():
    volume_index = {}

    for volume in ComicVineVolume.objects.filter(
        publisher__iexact=PUBLISHER_NAME,
    ).order_by("name", "start_year", "comicvine_id"):
        normalized_title = normalize_title(volume.name, fallback_id=volume.comicvine_id)
        volume_index.setdefault(normalized_title, []).append(volume)

    blank_publisher_count = ComicVineVolume.objects.filter(publisher="").count()
    return volume_index, blank_publisher_count


def list_selected_marvel_volumes(
    *,
    volume_index,
    comicvine_volume_ids,
    comicvine_issue_ids,
    limit,
):
    all_marvel_volumes = [
        volume
        for volumes in volume_index.values()
        for volume in volumes
    ]
    selected_volume_ids = set(comicvine_volume_ids)

    if comicvine_issue_ids:
        selected_volume_ids.update(
            ComicVineIssue.objects.filter(
                comicvine_id__in=comicvine_issue_ids,
                volume__publisher__iexact=PUBLISHER_NAME,
            ).values_list("volume__comicvine_id", flat=True)
        )

    if selected_volume_ids:
        selected = [
            volume
            for volume in all_marvel_volumes
            if volume.comicvine_id in selected_volume_ids
        ]
    else:
        selected = all_marvel_volumes

    selected.sort(
        key=lambda volume: (
            normalize_title(volume.name, fallback_id=volume.comicvine_id),
            clean_text(volume.start_year),
            volume.comicvine_id,
        )
    )

    if limit is not None:
        selected = selected[:limit]

    return selected


def build_volume_facts(volume):
    issues = list(volume.issues.order_by("comicvine_id", "id"))
    source_date_type, first_issue_date, last_issue_date = choose_source_date_range(
        issues
    )
    title = clean_title(volume.name) or f"Unknown Comic Vine Volume {volume.comicvine_id}"
    explicit_collection_issue_ids = {
        issue.id
        for issue in issues
        if extract_collecting_text(issue.description)
    }
    nonblank_issue_titles = [
        clean_title(issue.issue_title)
        for issue in issues
        if clean_title(issue.issue_title)
    ]
    all_titles_look_collected = (
        len(nonblank_issue_titles) >= 2
        and all(COLLECTION_TITLE_PATTERN.match(title) for title in nonblank_issue_titles)
    )
    collection_container = bool(explicit_collection_issue_ids) or all_titles_look_collected
    source_issue_count = len(issues)

    if volume.count_of_issues is not None:
        source_issue_count = max(source_issue_count, volume.count_of_issues)

    return VolumeFacts(
        volume=volume,
        issues=issues,
        title=title,
        normalized_title=normalize_title(title, fallback_id=volume.comicvine_id),
        start_year=clean_text(volume.start_year),
        source_issue_count=source_issue_count,
        source_date_type=source_date_type,
        first_issue_date=first_issue_date,
        last_issue_date=last_issue_date,
        first_issue_number=derive_first_issue_number(issues),
        last_issue_number=derive_last_issue_number(issues),
        source_fingerprint=build_volume_fingerprint(volume, issues),
        explicit_collection_issue_ids=explicit_collection_issue_ids,
        collection_container=collection_container,
    )


def choose_source_date_range(issues):
    dated_rows = []

    for issue in issues:
        if issue.store_date is not None:
            dated_rows.append((issue.store_date, "store"))
        elif issue.cover_date is not None:
            dated_rows.append((issue.cover_date, "cover"))

    if not dated_rows:
        return ComicVineVolumeCandidate.DATE_TYPE_UNKNOWN, None, None

    date_kinds = {date_kind for _date_value, date_kind in dated_rows}

    if date_kinds == {"store"}:
        date_type = ComicVineVolumeCandidate.DATE_TYPE_STORE_DATE
    elif date_kinds == {"cover"}:
        date_type = ComicVineVolumeCandidate.DATE_TYPE_COVER_DATE
    else:
        date_type = ComicVineVolumeCandidate.DATE_TYPE_BEST_AVAILABLE

    date_values = [date_value for date_value, _date_kind in dated_rows]
    return date_type, min(date_values), max(date_values)


def find_exact_name_date_fallbacks(*, selected_facts, volume_index, get_facts):
    decisions = {}

    for possible_collection in selected_facts:
        source_looks_collected = (
            len(possible_collection.issues) == 1
            or possible_collection.collection_container
        )

        if not source_looks_collected:
            continue

        fallback_found = False

        for collection_issue in possible_collection.issues:
            if extract_collecting_text(collection_issue.description):
                continue

            if not COLLECTION_TITLE_PATTERN.match(
                clean_title(collection_issue.issue_title)
            ):
                continue

            release_date = collection_issue.store_date or collection_issue.cover_date

            if release_date is None:
                continue

            possible_parents = []

            for possible_parent_volume in volume_index.get(
                possible_collection.normalized_title,
                [],
            ):
                if possible_parent_volume.id == possible_collection.volume.id:
                    continue

                possible_parent = get_facts(possible_parent_volume)

                if possible_parent.collection_container:
                    continue

                if possible_parent.source_issue_count <= 1:
                    continue

                if date_range_strictly_contains_date(possible_parent, release_date):
                    possible_parents.append(possible_parent)

            decisions[collection_issue.id] = FallbackDecision(
                collection_issue=collection_issue,
                parent_run_facts=(
                    possible_parents[0] if len(possible_parents) == 1 else None
                ),
                conflict=len(possible_parents) > 1,
            )
            fallback_found = True

        if fallback_found:
            possible_collection.collection_container = True

    return decisions


def date_range_strictly_contains_date(run_facts, release_date):
    if run_facts.first_issue_date is None or run_facts.last_issue_date is None:
        return False

    contained = run_facts.first_issue_date <= release_date <= run_facts.last_issue_date
    strictly_wider = (
        run_facts.first_issue_date < release_date
        or release_date < run_facts.last_issue_date
    )
    return contained and strictly_wider


def analyze_sources(
    *,
    selected_facts,
    volume_index,
    get_facts,
    fallback_decisions,
    selected_collection_issue_ids,
):
    result = AnalysisResult()
    result.source_volumes_seen = len(selected_facts)
    result.source_issues_seen = sum(len(facts.issues) for facts in selected_facts)

    selected_facts_by_id = {
        facts.volume.comicvine_id: facts
        for facts in selected_facts
    }
    run_candidates_by_volume_id = {}

    fallback_parent_ids = {
        decision.parent_run_facts.volume.comicvine_id
        for decision in fallback_decisions.values()
        if decision.parent_run_facts is not None
    }

    for facts in selected_facts:
        classification = classify_volume_source(
            facts,
            forced_run=facts.volume.comicvine_id in fallback_parent_ids,
        )
        candidate, action, source_changed = upsert_run_candidate(
            facts=facts,
            classification=classification,
        )
        run_candidates_by_volume_id[facts.volume.comicvine_id] = candidate
        record_run_candidate_action(result, action)

        if source_changed:
            result.source_changed += 1

    for decision in fallback_decisions.values():
        parent_facts = decision.parent_run_facts

        if parent_facts is None:
            continue

        parent_volume_id = parent_facts.volume.comicvine_id

        if parent_volume_id in run_candidates_by_volume_id:
            continue

        candidate, action, source_changed = upsert_run_candidate(
            facts=parent_facts,
            classification=classify_volume_source(parent_facts, forced_run=True),
        )
        run_candidates_by_volume_id[parent_volume_id] = candidate
        record_run_candidate_action(result, action)

        if source_changed:
            result.source_changed += 1

    processed_collection_issue_ids = set()

    for facts in selected_facts:
        for issue in facts.issues:
            collecting_text = extract_collecting_text(issue.description)
            fallback_decision = fallback_decisions.get(issue.id)

            if not collecting_text and fallback_decision is None:
                continue

            if (
                selected_collection_issue_ids
                and issue.comicvine_id not in selected_collection_issue_ids
            ):
                continue

            processed_collection_issue_ids.add(issue.id)

            if collecting_text:
                analysis = analyze_explicit_collected_edition(
                    issue=issue,
                    collection_facts=facts,
                    collecting_text=collecting_text,
                    volume_index=volume_index,
                    get_facts=get_facts,
                    run_candidates_by_volume_id=run_candidates_by_volume_id,
                    selected_facts_by_id=selected_facts_by_id,
                    result=result,
                )
            else:
                analysis = analyze_fallback_collected_edition(
                    issue=issue,
                    decision=fallback_decision,
                    run_candidates_by_volume_id=run_candidates_by_volume_id,
                )

            candidate, action, source_changed = upsert_collected_candidate(
                issue=issue,
                collection_facts=facts,
                analysis=analysis,
            )
            record_collected_candidate_action(result, action)

            if source_changed:
                result.source_changed += 1

            result.collected_issue_links_created += sync_collected_issue_links(
                candidate=candidate,
                memberships=analysis["memberships"],
            )

            if (
                analysis["analysis_status"]
                == ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
            ):
                result.confirmed_collected_volumes += 1
            elif (
                analysis["analysis_status"]
                == ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_CONFLICT
            ):
                result.conflicting_collected_volumes += 1
            else:
                result.unresolved_collected_volumes += 1

    selected_source_volume_ids = [facts.volume.id for facts in selected_facts]
    stale_candidates = ComicVineCollectedEditionCandidate.objects.filter(
        source_collection_volume_id__in=selected_source_volume_ids,
    ).exclude(comicvine_issue_id__in=processed_collection_issue_ids)

    if selected_collection_issue_ids:
        stale_candidates = stale_candidates.none()

    for candidate in stale_candidates:
        if candidate.determination_source == candidate.DETERMINATION_SOURCE_MANUAL:
            continue

        candidate.analysis_status = candidate.ANALYSIS_STATUS_UNRESOLVED
        candidate.analysis_reason = (
            "This source issue no longer has explicit collecting data or a valid "
            "exact-name date-containment fallback."
        )
        candidate.proposed_parent_run_candidate = None

        if candidate.catalog_status != candidate.CATALOG_STATUS_APPLIED:
            candidate.catalog_status = candidate.CATALOG_STATUS_NOT_READY
        else:
            candidate.catalog_status = candidate.CATALOG_STATUS_UPDATE_AVAILABLE

        candidate.analyzed_at = timezone.now()
        candidate.save(
            update_fields=[
                "analysis_status",
                "analysis_reason",
                "proposed_parent_run_candidate",
                "catalog_status",
                "analyzed_at",
            ]
        )
        candidate.source_issue_links.all().delete()
        result.stale_collected_candidates_invalidated += 1

    final_run_candidates = ComicVineVolumeCandidate.objects.filter(
        comicvine_volume_id__in=[facts.volume.id for facts in selected_facts]
    )
    result.confirmed_runs = final_run_candidates.filter(
        analysis_status=ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN
    ).count()
    result.collection_containers = final_run_candidates.filter(
        analysis_status=ComicVineVolumeCandidate.ANALYSIS_STATUS_COLLECTION_CONTAINER
    ).count()
    result.unresolved_run_sources = (
        final_run_candidates.count()
        - result.confirmed_runs
        - result.collection_containers
    )

    return result


def classify_volume_source(facts, *, forced_run=False):
    if forced_run:
        return {
            "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
            "analysis_reason": (
                "This source is the single exact run referenced by an exact-name "
                "date-contained collected edition."
            ),
        }

    if facts.collection_container:
        return {
            "analysis_status": (
                ComicVineVolumeCandidate.ANALYSIS_STATUS_COLLECTION_CONTAINER
            ),
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_NOT_READY,
            "analysis_reason": (
                "This Comic Vine volume contains individual collected editions; "
                "its issues are analyzed separately."
            ),
        }

    if not facts.issues:
        return {
            "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA,
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_NOT_READY,
            "analysis_reason": "No local source issues were available.",
        }

    if facts.source_issue_count > 1:
        return {
            "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
            "analysis_reason": (
                "This Marvel source contains multiple standard comic issues and no "
                "collected-edition indicators."
            ),
        }

    return {
        "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_UNRESOLVED,
        "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_NOT_READY,
        "analysis_reason": (
            "This one-issue source has no confirmed collected-edition relationship."
        ),
    }


def upsert_run_candidate(*, facts, classification):
    now = timezone.now()
    candidate = ComicVineVolumeCandidate.objects.filter(
        comicvine_volume=facts.volume,
    ).first()
    candidate_data = {
        "publisher_name": PUBLISHER_NAME,
        "title": facts.title,
        "normalized_title": facts.normalized_title,
        "start_year": facts.start_year,
        "source_issue_count": facts.source_issue_count,
        "source_date_type": facts.source_date_type,
        "first_issue_date": facts.first_issue_date,
        "last_issue_date": facts.last_issue_date,
        "first_issue_number": facts.first_issue_number,
        "last_issue_number": facts.last_issue_number,
        "source_volume_date_last_updated": facts.volume.date_last_updated,
        "source_fingerprint": facts.source_fingerprint,
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at": now,
    }

    if candidate is None:
        candidate = ComicVineVolumeCandidate.objects.create(
            comicvine_volume=facts.volume,
            analysis_status=classification["analysis_status"],
            catalog_status=classification["catalog_status"],
            determination_source=(
                ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM
            ),
            analysis_reason=classification["analysis_reason"],
            **candidate_data,
        )
        return candidate, "created", False

    source_changed = candidate.source_fingerprint != facts.source_fingerprint
    update_fields = []

    for field_name, new_value in candidate_data.items():
        if getattr(candidate, field_name) != new_value:
            setattr(candidate, field_name, new_value)
            update_fields.append(field_name)

    algorithm_can_update = (
        candidate.determination_source
        != ComicVineVolumeCandidate.DETERMINATION_SOURCE_MANUAL
        and candidate.review_status
        != ComicVineVolumeCandidate.REVIEW_STATUS_CONFIRMED
    )

    if algorithm_can_update:
        classification_data = {
            "analysis_status": classification["analysis_status"],
            "determination_source": (
                ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM
            ),
            "analysis_reason": classification["analysis_reason"],
        }

        for field_name, new_value in classification_data.items():
            if getattr(candidate, field_name) != new_value:
                setattr(candidate, field_name, new_value)
                update_fields.append(field_name)

        if candidate.catalog_status != candidate.CATALOG_STATUS_APPLIED:
            new_catalog_status = classification["catalog_status"]
            if candidate.catalog_status != new_catalog_status:
                candidate.catalog_status = new_catalog_status
                update_fields.append("catalog_status")

    if source_changed:
        candidate.source_changed_at = now
        update_fields.append("source_changed_at")

        if candidate.catalog_status == candidate.CATALOG_STATUS_APPLIED:
            candidate.catalog_status = candidate.CATALOG_STATUS_UPDATE_AVAILABLE
            update_fields.append("catalog_status")

    if update_fields:
        candidate.save(update_fields=dedupe(update_fields))
        return candidate, "updated", source_changed

    return candidate, "unchanged", source_changed


def analyze_explicit_collected_edition(
    *,
    issue,
    collection_facts,
    collecting_text,
    volume_index,
    get_facts,
    run_candidates_by_volume_id,
    selected_facts_by_id,
    result,
):
    parsed_references, parse_errors = parse_collecting_references(collecting_text)
    memberships = []
    resolution_errors = list(parse_errors)
    conflict = False
    parent_run_candidate = None
    primary_first_issue_number = ""
    primary_last_issue_number = ""
    next_issue_order = 1

    for reference_index, reference in enumerate(parsed_references):
        resolution = resolve_reference(
            reference=reference,
            volume_index=volume_index,
            get_facts=get_facts,
            run_candidates_by_volume_id=run_candidates_by_volume_id,
            selected_facts_by_id=selected_facts_by_id,
            result=result,
        )

        if resolution["conflict"]:
            conflict = True
            resolution_errors.append(resolution["reason"])
            continue

        if resolution["facts"] is None:
            resolution_errors.append(resolution["reason"])
            continue

        run_candidate = resolution["run_candidate"]

        if reference_index == 0:
            parent_run_candidate = run_candidate
            primary_first_issue_number = resolution["source_issues"][0].issue_number
            primary_last_issue_number = resolution["source_issues"][-1].issue_number

        for source_issue in resolution["source_issues"]:
            memberships.append(
                ResolvedMembership(
                    source_issue=source_issue,
                    source_run_candidate=run_candidate,
                    issue_order=next_issue_order,
                    primary_run=reference_index == 0,
                    reference_text=reference.raw_text,
                )
            )
            next_issue_order += 1

    duplicate_source_issue_ids = find_duplicates(
        membership.source_issue.id
        for membership in memberships
    )

    if duplicate_source_issue_ids:
        conflict = True
        resolution_errors.append(
            "The collecting statement resolved the same source issue more than once."
        )

    if conflict:
        analysis_status = ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_CONFLICT
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_BLOCKED
        analysis_reason = "The collecting statement had conflicting local matches."
    elif not parsed_references:
        analysis_status = (
            ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA
        )
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_NOT_READY
        analysis_reason = "No supported source references could be parsed."
    elif resolution_errors:
        analysis_status = ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_UNRESOLVED
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_NOT_READY
        analysis_reason = (
            "At least one item in the collecting statement could not be resolved exactly."
        )
    elif not memberships or parent_run_candidate is None:
        analysis_status = (
            ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA
        )
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_NOT_READY
        analysis_reason = "No collected source issues were resolved."
    else:
        analysis_status = (
            ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
        )
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_READY_TO_APPLY
        analysis_reason = (
            "Every item in the explicit collecting statement resolved to one local "
            "Marvel run and exact source issues."
        )

    volume_number, title = parse_volume_number_and_title(issue.issue_title)

    if not volume_number:
        volume_number = clean_text(issue.issue_number)

    return {
        "volume_number": volume_number,
        "title": title,
        "release_date": issue.store_date or issue.cover_date,
        "collecting_text": collecting_text,
        "unresolved_reference_text": " | ".join(dedupe(resolution_errors)),
        "source_reference_count": len(parsed_references),
        "source_issue_count": len(memberships),
        "primary_first_issue_number": primary_first_issue_number,
        "primary_last_issue_number": primary_last_issue_number,
        "parent_run_candidate": parent_run_candidate,
        "memberships": memberships,
        "analysis_status": analysis_status,
        "catalog_status": catalog_status,
        "analysis_reason": analysis_reason,
    }


def analyze_fallback_collected_edition(
    *,
    issue,
    decision,
    run_candidates_by_volume_id,
):
    volume_number, title = parse_volume_number_and_title(issue.issue_title)

    if not volume_number:
        volume_number = clean_text(issue.issue_number)

    if decision.conflict:
        analysis_status = ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_CONFLICT
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_BLOCKED
        analysis_reason = (
            "The exact-name release date was contained by multiple possible run sources."
        )
        parent_run_candidate = None
        unresolved_text = "Multiple exact-name parent runs matched the release date."
    elif decision.parent_run_facts is None:
        analysis_status = ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_UNRESOLVED
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_NOT_READY
        analysis_reason = "No exact-name parent run contained the release date."
        parent_run_candidate = None
        unresolved_text = "No exact-name parent run matched."
    else:
        analysis_status = (
            ComicVineCollectedEditionCandidate.ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
        )
        catalog_status = ComicVineCollectedEditionCandidate.CATALOG_STATUS_READY_TO_APPLY
        analysis_reason = (
            "This one-issue Vol./Volume source has the exact run name and its release "
            "date is strictly contained inside one run source date range."
        )
        parent_run_candidate = run_candidates_by_volume_id[
            decision.parent_run_facts.volume.comicvine_id
        ]
        unresolved_text = ""

    return {
        "volume_number": volume_number,
        "title": title,
        "release_date": issue.store_date or issue.cover_date,
        "collecting_text": "",
        "unresolved_reference_text": unresolved_text,
        "source_reference_count": 0,
        "source_issue_count": 0,
        "primary_first_issue_number": "",
        "primary_last_issue_number": "",
        "parent_run_candidate": parent_run_candidate,
        "memberships": [],
        "analysis_status": analysis_status,
        "catalog_status": catalog_status,
        "analysis_reason": analysis_reason,
    }


def parse_collecting_references(collecting_text):
    raw_segments = []

    for comma_segment in re.split(r"\s*[,;]\s*", collecting_text):
        raw_segments.extend(
            re.split(
                r"(?<=\d)\s+\band\b\s+(?=(?:material\s+from\s+)?[A-Za-z])",
                comma_segment,
                flags=re.IGNORECASE,
            )
        )
    references = []
    errors = []

    for raw_segment in raw_segments:
        segment = clean_title(raw_segment).strip(" .")
        segment = re.sub(
            r"^(?:and\s+)?(?:material\s+from\s+)?",
            "",
            segment,
            flags=re.IGNORECASE,
        ).strip()

        if not segment:
            continue

        segment_without_note = re.sub(
            r"\s*\((?!\d{4}\))[^)]*\)\s*$",
            "",
            segment,
        ).strip()
        match = REFERENCE_PATTERN.match(segment_without_note)

        if match:
            title = clean_title(match.group("title"))
            start_year = clean_text(match.group("year"))
            first_issue_number = clean_text(match.group("first"))
            last_issue_number = clean_text(match.group("last")) or first_issue_number

            references.append(
                ParsedReference(
                    raw_text=segment,
                    title=title,
                    normalized_title=normalize_title(title, fallback_id=0),
                    start_year=start_year,
                    first_issue_number=first_issue_number,
                    last_issue_number=last_issue_number,
                )
            )
            continue

        if "#" not in segment_without_note and re.search(
            r"[A-Za-z]",
            segment_without_note,
        ):
            title = clean_title(segment_without_note)
            references.append(
                ParsedReference(
                    raw_text=segment,
                    title=title,
                    normalized_title=normalize_title(title, fallback_id=0),
                    start_year="",
                    first_issue_number="",
                    last_issue_number="",
                    standalone=True,
                )
            )
            continue

        errors.append(f"Could not parse: {segment}")

    return references, errors


def resolve_reference(
    *,
    reference,
    volume_index,
    get_facts,
    run_candidates_by_volume_id,
    selected_facts_by_id,
    result,
):
    matching_volumes = list(volume_index.get(reference.normalized_title, []))

    if reference.start_year:
        matching_volumes = [
            volume
            for volume in matching_volumes
            if clean_text(volume.start_year) == reference.start_year
        ]

    if not matching_volumes:
        return {
            "facts": None,
            "run_candidate": None,
            "source_issues": [],
            "conflict": False,
            "reason": (
                f"No local Marvel volume matched {reference.title!r}"
                + (f" ({reference.start_year})" if reference.start_year else "")
                + "."
            ),
        }

    if len(matching_volumes) > 1:
        return {
            "facts": None,
            "run_candidate": None,
            "source_issues": [],
            "conflict": True,
            "reason": (
                f"Multiple local Marvel volumes matched {reference.title!r}"
                + (f" ({reference.start_year})" if reference.start_year else "")
                + "."
            ),
        }

    facts = get_facts(matching_volumes[0])

    if facts.collection_container:
        return {
            "facts": None,
            "run_candidate": None,
            "source_issues": [],
            "conflict": True,
            "reason": f"{reference.title!r} resolved to another collection container.",
        }

    source_issues, issue_error = resolve_reference_issues(reference, facts)

    if issue_error:
        return {
            "facts": None,
            "run_candidate": None,
            "source_issues": [],
            "conflict": "multiple" in issue_error.casefold(),
            "reason": issue_error,
        }

    run_candidate = run_candidates_by_volume_id.get(facts.volume.comicvine_id)

    if run_candidate is None:
        classification = classify_volume_source(facts, forced_run=True)
        run_candidate, action, source_changed = upsert_run_candidate(
            facts=facts,
            classification=classification,
        )
        run_candidates_by_volume_id[facts.volume.comicvine_id] = run_candidate
        selected_facts_by_id[facts.volume.comicvine_id] = facts
        record_run_candidate_action(result, action)

        if source_changed:
            result.source_changed += 1
    else:
        confirm_run_candidate_from_reference(run_candidate)

    if run_candidate.review_status == run_candidate.REVIEW_STATUS_REJECTED:
        return {
            "facts": None,
            "run_candidate": None,
            "source_issues": [],
            "conflict": True,
            "reason": f"The matched run candidate for {reference.title!r} was rejected.",
        }

    return {
        "facts": facts,
        "run_candidate": run_candidate,
        "source_issues": source_issues,
        "conflict": False,
        "reason": "",
    }


def resolve_reference_issues(reference, facts):
    if reference.standalone:
        if len(facts.issues) != 1:
            return [], (
                f"Standalone reference {reference.title!r} matched a source with "
                f"{len(facts.issues)} local issues instead of exactly one."
            )

        return [facts.issues[0]], ""

    first_number = int(reference.first_issue_number)
    last_number = int(reference.last_issue_number)

    if last_number < first_number:
        return [], f"Invalid descending issue range: {reference.raw_text}"

    issues_by_number = {}

    for source_issue in facts.issues:
        normalized_number = normalize_issue_number(source_issue.issue_number)
        issues_by_number.setdefault(normalized_number, []).append(source_issue)

    resolved_issues = []

    for issue_number in range(first_number, last_number + 1):
        matching_issues = issues_by_number.get(str(issue_number), [])

        if not matching_issues:
            return [], (
                f"{facts.title} ({facts.start_year}) is missing local issue "
                f"#{issue_number} required by {reference.raw_text!r}."
            )

        if len(matching_issues) > 1:
            return [], (
                f"{facts.title} ({facts.start_year}) has multiple local issue "
                f"#{issue_number} rows."
            )

        resolved_issues.append(matching_issues[0])

    return resolved_issues, ""


def confirm_run_candidate_from_reference(candidate):
    if (
        candidate.determination_source == candidate.DETERMINATION_SOURCE_MANUAL
        or candidate.review_status == candidate.REVIEW_STATUS_CONFIRMED
    ):
        return

    update_fields = []
    reason = "This source was resolved exactly by an explicit collecting statement."

    if candidate.analysis_status != candidate.ANALYSIS_STATUS_CONFIRMED_RUN:
        candidate.analysis_status = candidate.ANALYSIS_STATUS_CONFIRMED_RUN
        update_fields.append("analysis_status")

    if candidate.analysis_reason != reason:
        candidate.analysis_reason = reason
        update_fields.append("analysis_reason")

    if candidate.determination_source != candidate.DETERMINATION_SOURCE_ALGORITHM:
        candidate.determination_source = candidate.DETERMINATION_SOURCE_ALGORITHM
        update_fields.append("determination_source")

    if candidate.catalog_status != candidate.CATALOG_STATUS_APPLIED:
        if candidate.catalog_status != candidate.CATALOG_STATUS_READY_TO_APPLY:
            candidate.catalog_status = candidate.CATALOG_STATUS_READY_TO_APPLY
            update_fields.append("catalog_status")

    if update_fields:
        candidate.save(update_fields=update_fields)


def upsert_collected_candidate(*, issue, collection_facts, analysis):
    now = timezone.now()
    candidate = ComicVineCollectedEditionCandidate.objects.filter(
        comicvine_issue=issue,
    ).first()
    source_fingerprint = build_collected_issue_fingerprint(
        issue=issue,
        collection_facts=collection_facts,
        analysis=analysis,
    )
    candidate_data = {
        "source_collection_volume": collection_facts.volume,
        "publisher_name": PUBLISHER_NAME,
        "source_title": clean_title(issue.issue_title),
        "volume_number": analysis["volume_number"],
        "title": analysis["title"],
        "release_date": analysis["release_date"],
        "collecting_text": analysis["collecting_text"],
        "unresolved_reference_text": analysis["unresolved_reference_text"],
        "source_reference_count": analysis["source_reference_count"],
        "source_issue_count": analysis["source_issue_count"],
        "primary_first_issue_number": analysis["primary_first_issue_number"],
        "primary_last_issue_number": analysis["primary_last_issue_number"],
        "source_issue_date_last_updated": issue.date_last_updated,
        "source_fingerprint": source_fingerprint,
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at": now,
    }

    if candidate is None:
        candidate = ComicVineCollectedEditionCandidate.objects.create(
            comicvine_issue=issue,
            proposed_parent_run_candidate=analysis["parent_run_candidate"],
            analysis_status=analysis["analysis_status"],
            catalog_status=analysis["catalog_status"],
            determination_source=(
                ComicVineCollectedEditionCandidate.DETERMINATION_SOURCE_ALGORITHM
            ),
            analysis_reason=analysis["analysis_reason"],
            **candidate_data,
        )
        return candidate, "created", False

    source_changed = candidate.source_fingerprint != source_fingerprint
    update_fields = []

    for field_name, new_value in candidate_data.items():
        if getattr(candidate, field_name) != new_value:
            setattr(candidate, field_name, new_value)
            update_fields.append(field_name)

    algorithm_can_update = (
        candidate.determination_source
        != ComicVineCollectedEditionCandidate.DETERMINATION_SOURCE_MANUAL
        and candidate.review_status
        != ComicVineCollectedEditionCandidate.REVIEW_STATUS_CONFIRMED
    )

    if algorithm_can_update:
        algorithm_data = {
            "proposed_parent_run_candidate": analysis["parent_run_candidate"],
            "analysis_status": analysis["analysis_status"],
            "determination_source": (
                ComicVineCollectedEditionCandidate.DETERMINATION_SOURCE_ALGORITHM
            ),
            "analysis_reason": analysis["analysis_reason"],
        }

        for field_name, new_value in algorithm_data.items():
            if getattr(candidate, field_name) != new_value:
                setattr(candidate, field_name, new_value)
                update_fields.append(field_name)

        if candidate.catalog_status != candidate.CATALOG_STATUS_APPLIED:
            if candidate.catalog_status != analysis["catalog_status"]:
                candidate.catalog_status = analysis["catalog_status"]
                update_fields.append("catalog_status")

    if source_changed:
        candidate.source_changed_at = now
        update_fields.append("source_changed_at")

        if candidate.catalog_status == candidate.CATALOG_STATUS_APPLIED:
            candidate.catalog_status = candidate.CATALOG_STATUS_UPDATE_AVAILABLE
            update_fields.append("catalog_status")

    if update_fields:
        candidate.save(update_fields=dedupe(update_fields))
        return candidate, "updated", source_changed

    return candidate, "unchanged", source_changed


def sync_collected_issue_links(*, candidate, memberships):
    if (
        candidate.determination_source
        == ComicVineCollectedEditionCandidate.DETERMINATION_SOURCE_MANUAL
        or candidate.review_status
        == ComicVineCollectedEditionCandidate.REVIEW_STATUS_CONFIRMED
    ):
        return 0

    candidate.source_issue_links.all().delete()

    if not memberships:
        return 0

    ComicVineCollectedEditionIssue.objects.bulk_create(
        [
            ComicVineCollectedEditionIssue(
                candidate=candidate,
                source_issue=membership.source_issue,
                source_run_candidate=membership.source_run_candidate,
                issue_order=membership.issue_order,
                primary_run=membership.primary_run,
                reference_text=membership.reference_text,
            )
            for membership in memberships
        ]
    )
    return len(memberships)


def extract_collecting_text(description):
    description = clean_html_text(description)
    match = re.search(r"\bcollecting\s*:?\s*", description, flags=re.IGNORECASE)

    if not match:
        return ""

    collecting_text = description[match.end():].strip()
    sentence_end = re.search(r"\.(?:\s|$)", collecting_text)

    if sentence_end:
        collecting_text = collecting_text[: sentence_end.start()]

    return clean_title(collecting_text).strip(" .")


def parse_volume_number_and_title(value):
    value = clean_title(value)

    if not value:
        return "", ""

    match = VOLUME_TITLE_PATTERN.match(value)

    if not match:
        return "", value

    return clean_text(match.group("number")), clean_title(match.group("title"))


def derive_first_issue_number(issues):
    dated_issues = sorted(
        issues,
        key=lambda issue: (
            issue.store_date or issue.cover_date or date.max,
            issue.comicvine_id or 0,
        ),
    )

    for issue in dated_issues:
        issue_number = clean_text(issue.issue_number)
        if issue_number:
            return issue_number

    return ""


def derive_last_issue_number(issues):
    dated_issues = sorted(
        issues,
        key=lambda issue: (
            issue.store_date or issue.cover_date or date.min,
            issue.comicvine_id or 0,
        ),
        reverse=True,
    )

    for issue in dated_issues:
        issue_number = clean_text(issue.issue_number)
        if issue_number:
            return issue_number

    return ""


def build_volume_fingerprint(volume, issues):
    lines = [
        f"comicvine_id={volume.comicvine_id}",
        f"name={clean_text(volume.name)}",
        f"publisher={clean_text(volume.publisher)}",
        f"start_year={clean_text(volume.start_year)}",
        f"count_of_issues={volume.count_of_issues or ''}",
        f"date_last_updated={volume.date_last_updated or ''}",
    ]

    for issue in issues:
        lines.append(
            "|".join(
                [
                    f"id={issue.id}",
                    f"comicvine_id={issue.comicvine_id or ''}",
                    f"issue_number={clean_text(issue.issue_number)}",
                    f"title={clean_text(issue.issue_title)}",
                    f"store_date={issue.store_date or ''}",
                    f"cover_date={issue.cover_date or ''}",
                    f"date_last_updated={issue.date_last_updated or ''}",
                    f"collecting={extract_collecting_text(issue.description)}",
                ]
            )
        )

    return hash_lines(lines)


def build_collected_issue_fingerprint(*, issue, collection_facts, analysis):
    membership_lines = [
        "|".join(
            [
                str(membership.source_issue.comicvine_id or ""),
                str(membership.source_run_candidate.comicvine_volume.comicvine_id),
                str(membership.issue_order),
                str(membership.primary_run),
            ]
        )
        for membership in analysis["memberships"]
    ]
    return hash_lines(
        [
            f"comicvine_issue_id={issue.comicvine_id or ''}",
            f"source_volume_id={collection_facts.volume.comicvine_id}",
            f"issue_number={clean_text(issue.issue_number)}",
            f"title={clean_text(issue.issue_title)}",
            f"store_date={issue.store_date or ''}",
            f"cover_date={issue.cover_date or ''}",
            f"date_last_updated={issue.date_last_updated or ''}",
            f"collecting_text={analysis['collecting_text']}",
            f"unresolved={analysis['unresolved_reference_text']}",
            *membership_lines,
        ]
    )


def hash_lines(lines):
    payload = "\n".join(clean_text(line) for line in lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_title(title, *, fallback_id):
    title = clean_title(title)

    if not title:
        title = f"Unknown Comic Vine Volume {fallback_id}"

    title = title.casefold().replace("&", " and ")
    title = re.sub(r"[^a-z0-9]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    if title.startswith("the "):
        title = title[4:].strip()

    return title or f"unknown comic vine volume {fallback_id}"


def normalize_issue_number(value):
    value = clean_text(value).casefold().lstrip("#").strip()

    if value.isdigit():
        return str(int(value))

    return value


def clean_html_text(value):
    value = unescape(clean_text(value))
    value = strip_tags(value)
    return re.sub(r"\s+", " ", value).strip()


def clean_title(value):
    value = unescape(clean_text(value))
    return re.sub(r"\s+", " ", value).strip()


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def find_duplicates(values):
    seen = set()
    duplicates = set()

    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)

    return duplicates


def dedupe(values):
    seen = set()
    result = []

    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)

    return result


def record_run_candidate_action(result, action):
    if action == "created":
        result.run_candidates_created += 1
    elif action == "updated":
        result.run_candidates_updated += 1
    else:
        result.run_candidates_unchanged += 1


def record_collected_candidate_action(result, action):
    if action == "created":
        result.collected_candidates_created += 1
    elif action == "updated":
        result.collected_candidates_updated += 1
    else:
        result.collected_candidates_unchanged += 1


def print_result(command, result, *, dry_run):
    prefix = "Would " if dry_run else ""
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Run complete."))
    command.stdout.write("=" * 60)
    command.stdout.write(f"Source volumes seen: {result.source_volumes_seen}")
    command.stdout.write(f"Source issues seen: {result.source_issues_seen}")
    command.stdout.write(
        "Blank-publisher volumes excluded: "
        f"{result.blank_publisher_volumes_excluded}"
    )
    command.stdout.write("")
    command.stdout.write(
        f"{prefix}run candidates created: {result.run_candidates_created}"
    )
    command.stdout.write(
        f"{prefix}run candidates updated: {result.run_candidates_updated}"
    )
    command.stdout.write(
        f"{prefix}run candidates unchanged: {result.run_candidates_unchanged}"
    )
    command.stdout.write(f"Confirmed runs: {result.confirmed_runs}")
    command.stdout.write(f"Collection containers: {result.collection_containers}")
    command.stdout.write(f"Unresolved run sources: {result.unresolved_run_sources}")
    command.stdout.write("")
    command.stdout.write(
        f"{prefix}collected candidates created: "
        f"{result.collected_candidates_created}"
    )
    command.stdout.write(
        f"{prefix}collected candidates updated: "
        f"{result.collected_candidates_updated}"
    )
    command.stdout.write(
        f"{prefix}collected candidates unchanged: "
        f"{result.collected_candidates_unchanged}"
    )
    command.stdout.write(
        f"Confirmed collected volumes: {result.confirmed_collected_volumes}"
    )
    command.stdout.write(
        f"Unresolved collected volumes: {result.unresolved_collected_volumes}"
    )
    command.stdout.write(
        f"Conflicting collected volumes: {result.conflicting_collected_volumes}"
    )
    command.stdout.write(
        f"{prefix}stale collected candidates invalidated: "
        f"{result.stale_collected_candidates_invalidated}"
    )
    command.stdout.write(
        f"{prefix}resolved collected issue links rebuilt: "
        f"{result.collected_issue_links_created}"
    )
    command.stdout.write(f"Source changed since last analysis: {result.source_changed}")

    if dry_run:
        command.stdout.write("")
        command.stdout.write("Dry run only. No database changes were saved.")