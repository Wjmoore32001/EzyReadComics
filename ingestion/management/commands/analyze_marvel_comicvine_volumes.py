import hashlib
import re
from dataclasses import dataclass, field
from html import unescape

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from comicvine.models import ComicVineVolume
from ingestion.models import (
    ComicVineVolumeCandidate,
    MarvelIngestionGroup,
    MarvelVolumeContainment,
)


PUBLISHER_NAME = "Marvel"
ANALYSIS_VERSION = 2


@dataclass
class VolumeFacts:
    volume: ComicVineVolume
    title: str
    normalized_title: str
    start_year: str
    source_issue_count: int
    source_date_type: str
    first_issue_date: object
    last_issue_date: object
    first_issue_number: str
    last_issue_number: str
    source_volume_date_last_updated: object
    source_volume_fingerprint: str
    source_issue_fingerprint: str


@dataclass
class GroupFacts:
    normalized_title: str
    display_title: str
    volume_facts: list[VolumeFacts] = field(default_factory=list)

    @property
    def source_volume_count(self):
        return len(self.volume_facts)

    @property
    def source_issue_count(self):
        return sum(volume.source_issue_count for volume in self.volume_facts)

    @property
    def first_issue_date(self):
        dated_values = [
            volume.first_issue_date
            for volume in self.volume_facts
            if volume.first_issue_date is not None
        ]

        if not dated_values:
            return None

        return min(dated_values)

    @property
    def last_issue_date(self):
        dated_values = [
            volume.last_issue_date
            for volume in self.volume_facts
            if volume.last_issue_date is not None
        ]

        if not dated_values:
            return None

        return max(dated_values)

    @property
    def source_volume_fingerprint(self):
        return hash_lines(
            [
                volume.source_volume_fingerprint
                for volume in sorted(
                    self.volume_facts,
                    key=lambda item: item.volume.comicvine_id,
                )
            ]
        )

    @property
    def source_issue_fingerprint(self):
        return hash_lines(
            [
                volume.source_issue_fingerprint
                for volume in sorted(
                    self.volume_facts,
                    key=lambda item: item.volume.comicvine_id,
                )
            ]
        )


@dataclass
class ContainmentDecision:
    run_volume_id: int
    collected_volume_id: int
    date_type: str
    reason: str


@dataclass
class AnalysisResult:
    volumes_seen: int = 0
    groups_seen: int = 0

    groups_created: int = 0
    groups_updated: int = 0
    groups_unchanged: int = 0

    candidates_created: int = 0
    candidates_updated: int = 0
    candidates_unchanged: int = 0

    containments_created: int = 0
    containments_updated: int = 0
    containments_unchanged: int = 0
    containments_invalidated: int = 0

    confirmed_runs: int = 0
    confirmed_collected_volumes: int = 0
    unresolved: int = 0
    conflicts: int = 0
    insufficient_data: int = 0
    source_changed: int = 0


class Command(BaseCommand):
    help = (
        "Analyze local Marvel Comic Vine volumes into ingestion groups using exact "
        "source volume-name matching first, then date containment."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            action="append",
            dest="comicvine_volume_ids",
            help=(
                "Optional Comic Vine volume ID to analyze. Can be provided multiple times. "
                "If omitted, all local Marvel Comic Vine volumes are selected."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional maximum number of local Marvel Comic Vine volumes to analyze.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyze and summarize what would happen without saving changes.",
        )

    def handle(self, *args, **options):
        comicvine_volume_ids = options["comicvine_volume_ids"] or []
        limit = options["limit"]
        dry_run = options["dry_run"]

        validate_options(
            comicvine_volume_ids=comicvine_volume_ids,
            limit=limit,
        )

        selected_volumes = list_selected_marvel_volumes(
            comicvine_volume_ids=comicvine_volume_ids,
            limit=limit,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Analyze Marvel Comic Vine volumes"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")
        self.stdout.write("Source: local ComicVineVolume and ComicVineIssue rows")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write("Comic Vine API calls: none")
        self.stdout.write("Relationship rule: exact/simple ComicVineVolume.name match first")
        self.stdout.write("Date rule: strict containment inside same-name group")

        if comicvine_volume_ids:
            self.stdout.write(
                "Selected Comic Vine volume IDs: "
                + ", ".join(str(volume_id) for volume_id in comicvine_volume_ids)
            )
        else:
            self.stdout.write("Selected Comic Vine volume IDs: all local Marvel volumes")

        self.stdout.write(f"Limit: {limit if limit is not None else 'none'}")
        self.stdout.write(f"Local Marvel volumes selected: {len(selected_volumes)}")

        volume_facts = [build_volume_facts(volume) for volume in selected_volumes]
        group_facts_list = build_group_facts_list(volume_facts)

        with transaction.atomic():
            result = analyze_groups(group_facts_list)

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Run complete."))
        self.stdout.write("=" * 60)

        prefix = "Would " if dry_run else ""

        self.stdout.write(f"Volumes seen: {result.volumes_seen}")
        self.stdout.write(f"Groups seen: {result.groups_seen}")
        self.stdout.write("")
        self.stdout.write(f"{prefix}groups created: {result.groups_created}")
        self.stdout.write(f"{prefix}groups updated: {result.groups_updated}")
        self.stdout.write(f"{prefix}groups unchanged: {result.groups_unchanged}")
        self.stdout.write("")
        self.stdout.write(f"{prefix}candidates created: {result.candidates_created}")
        self.stdout.write(f"{prefix}candidates updated: {result.candidates_updated}")
        self.stdout.write(f"{prefix}candidates unchanged: {result.candidates_unchanged}")
        self.stdout.write("")
        self.stdout.write(f"{prefix}containments created: {result.containments_created}")
        self.stdout.write(f"{prefix}containments updated: {result.containments_updated}")
        self.stdout.write(
            f"{prefix}containments unchanged: {result.containments_unchanged}"
        )
        self.stdout.write(
            f"{prefix}containments invalidated: {result.containments_invalidated}"
        )
        self.stdout.write("")
        self.stdout.write(f"Confirmed runs: {result.confirmed_runs}")
        self.stdout.write(
            f"Confirmed collected volumes: {result.confirmed_collected_volumes}"
        )
        self.stdout.write(f"Unresolved: {result.unresolved}")
        self.stdout.write(f"Conflicts: {result.conflicts}")
        self.stdout.write(f"Insufficient data: {result.insufficient_data}")
        self.stdout.write(f"Source changed since last analysis: {result.source_changed}")

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


def list_selected_marvel_volumes(*, comicvine_volume_ids, limit):
    queryset = ComicVineVolume.objects.filter(
        publisher__iexact=PUBLISHER_NAME,
    ).order_by(
        "name",
        "start_year",
        "comicvine_id",
    )

    if comicvine_volume_ids:
        queryset = queryset.filter(comicvine_id__in=comicvine_volume_ids)

    if limit is not None:
        queryset = queryset[:limit]

    return list(queryset)


def build_volume_facts(volume):
    issue_rows = list(
        volume.issues.order_by("comicvine_id", "id").values(
            "id",
            "comicvine_id",
            "issue_number",
            "store_date",
            "cover_date",
            "date_last_updated",
        )
    )

    source_date_type, first_issue_date, last_issue_date = choose_source_date_range(
        issue_rows
    )

    title = clean_title(volume.name)

    if not title:
        title = f"Unknown Comic Vine Volume {volume.comicvine_id}"

    normalized_title = normalize_volume_name_for_exact_grouping(
        title,
        fallback_id=volume.comicvine_id,
    )

    first_issue_number = clean_text(volume.first_issue_number)
    last_issue_number = clean_text(volume.last_issue_number)

    if not first_issue_number:
        first_issue_number = derive_first_issue_number(issue_rows)

    if not last_issue_number:
        last_issue_number = derive_last_issue_number(issue_rows)

    source_issue_count = len(issue_rows)

    if volume.count_of_issues is not None:
        source_issue_count = max(source_issue_count, volume.count_of_issues)

    return VolumeFacts(
        volume=volume,
        title=title,
        normalized_title=normalized_title,
        start_year=clean_text(volume.start_year),
        source_issue_count=source_issue_count,
        source_date_type=source_date_type,
        first_issue_date=first_issue_date,
        last_issue_date=last_issue_date,
        first_issue_number=first_issue_number,
        last_issue_number=last_issue_number,
        source_volume_date_last_updated=volume.date_last_updated,
        source_volume_fingerprint=build_volume_fingerprint(volume),
        source_issue_fingerprint=build_issue_fingerprint(issue_rows),
    )


def choose_source_date_range(issue_rows):
    store_dates = [
        issue["store_date"]
        for issue in issue_rows
        if issue["store_date"] is not None
    ]

    if store_dates:
        return (
            ComicVineVolumeCandidate.DATE_TYPE_STORE_DATE,
            min(store_dates),
            max(store_dates),
        )

    cover_dates = [
        issue["cover_date"]
        for issue in issue_rows
        if issue["cover_date"] is not None
    ]

    if cover_dates:
        return (
            ComicVineVolumeCandidate.DATE_TYPE_COVER_DATE,
            min(cover_dates),
            max(cover_dates),
        )

    return (
        ComicVineVolumeCandidate.DATE_TYPE_UNKNOWN,
        None,
        None,
    )


def build_volume_fingerprint(volume):
    return hash_lines(
        [
            f"comicvine_id={volume.comicvine_id}",
            f"name={clean_text(volume.name)}",
            f"publisher={clean_text(volume.publisher)}",
            f"start_year={clean_text(volume.start_year)}",
            f"count_of_issues={volume.count_of_issues or ''}",
            f"date_last_updated={volume.date_last_updated or ''}",
            f"first_issue_comicvine_id={volume.first_issue_comicvine_id or ''}",
            f"first_issue_number={clean_text(volume.first_issue_number)}",
            f"last_issue_comicvine_id={volume.last_issue_comicvine_id or ''}",
            f"last_issue_number={clean_text(volume.last_issue_number)}",
        ]
    )


def build_issue_fingerprint(issue_rows):
    lines = []

    for issue in issue_rows:
        lines.append(
            "|".join(
                [
                    f"id={issue['id']}",
                    f"comicvine_id={issue['comicvine_id'] or ''}",
                    f"issue_number={clean_text(issue['issue_number'])}",
                    f"store_date={issue['store_date'] or ''}",
                    f"cover_date={issue['cover_date'] or ''}",
                    f"date_last_updated={issue['date_last_updated'] or ''}",
                ]
            )
        )

    return hash_lines(lines)


def hash_lines(lines):
    normalized_lines = [clean_text(line) for line in lines]
    payload = "\n".join(normalized_lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_first_issue_number(issue_rows):
    for issue in issue_rows:
        issue_number = clean_text(issue["issue_number"])

        if issue_number:
            return issue_number

    return ""


def derive_last_issue_number(issue_rows):
    for issue in reversed(issue_rows):
        issue_number = clean_text(issue["issue_number"])

        if issue_number:
            return issue_number

    return ""


def build_group_facts_list(volume_facts):
    groups_by_normalized_title = {}

    for facts in volume_facts:
        if facts.normalized_title not in groups_by_normalized_title:
            groups_by_normalized_title[facts.normalized_title] = GroupFacts(
                normalized_title=facts.normalized_title,
                display_title=facts.title,
            )

        groups_by_normalized_title[facts.normalized_title].volume_facts.append(facts)

    return sorted(
        groups_by_normalized_title.values(),
        key=lambda group: group.normalized_title,
    )


def analyze_groups(group_facts_list):
    result = AnalysisResult()

    for group_facts in group_facts_list:
        result.groups_seen += 1
        result.volumes_seen += len(group_facts.volume_facts)

        group, group_action, group_source_changed = upsert_group(group_facts)

        if group_action == "created":
            result.groups_created += 1
        elif group_action == "updated":
            result.groups_updated += 1
        else:
            result.groups_unchanged += 1

        if group_source_changed:
            result.source_changed += 1

        candidates_by_volume_id = {}

        for facts in group_facts.volume_facts:
            candidate, candidate_action, candidate_source_changed = upsert_candidate(
                group=group,
                facts=facts,
            )
            candidates_by_volume_id[facts.volume.comicvine_id] = candidate

            if candidate_action == "created":
                result.candidates_created += 1
            elif candidate_action == "updated":
                result.candidates_updated += 1
            else:
                result.candidates_unchanged += 1

            if candidate_source_changed:
                result.source_changed += 1

        containment_decisions = find_containment_decisions(group_facts.volume_facts)

        current_pair_keys = set()

        for decision in containment_decisions:
            run_candidate = candidates_by_volume_id[decision.run_volume_id]
            collected_candidate = candidates_by_volume_id[decision.collected_volume_id]

            containment, containment_action = upsert_containment(
                group=group,
                run_candidate=run_candidate,
                collected_candidate=collected_candidate,
                decision=decision,
            )

            current_pair_keys.add(
                (
                    containment.run_candidate_id,
                    containment.collected_volume_candidate_id,
                )
            )

            if containment_action == "created":
                result.containments_created += 1
            elif containment_action == "updated":
                result.containments_updated += 1
            else:
                result.containments_unchanged += 1

        result.containments_invalidated += invalidate_stale_algorithm_containments(
            group=group,
            current_pair_keys=current_pair_keys,
        )

        candidate_status_counts = classify_group_candidates(
            group=group,
            group_facts=group_facts,
            candidates_by_volume_id=candidates_by_volume_id,
            containment_decisions=containment_decisions,
        )

        result.confirmed_runs += candidate_status_counts["confirmed_runs"]
        result.confirmed_collected_volumes += candidate_status_counts[
            "confirmed_collected_volumes"
        ]
        result.unresolved += candidate_status_counts["unresolved"]
        result.conflicts += candidate_status_counts["conflicts"]
        result.insufficient_data += candidate_status_counts["insufficient_data"]

        update_group_analysis_status(
            group=group,
            candidate_status_counts=candidate_status_counts,
            containment_decisions=containment_decisions,
        )

    return result


def upsert_group(group_facts):
    now = timezone.now()

    group = MarvelIngestionGroup.objects.filter(
        publisher_name=PUBLISHER_NAME,
        normalized_title=group_facts.normalized_title,
    ).first()

    group_data = {
        "display_title": group_facts.display_title,
        "source_volume_count": group_facts.source_volume_count,
        "source_issue_count": group_facts.source_issue_count,
        "first_issue_date": group_facts.first_issue_date,
        "last_issue_date": group_facts.last_issue_date,
        "source_volume_fingerprint": group_facts.source_volume_fingerprint,
        "source_issue_fingerprint": group_facts.source_issue_fingerprint,
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at": now,
    }

    if group is None:
        group = MarvelIngestionGroup.objects.create(
            publisher_name=PUBLISHER_NAME,
            normalized_title=group_facts.normalized_title,
            **group_data,
        )
        return group, "created", False

    source_changed = (
        group.source_volume_fingerprint != group_data["source_volume_fingerprint"]
        or group.source_issue_fingerprint != group_data["source_issue_fingerprint"]
    )

    update_fields = []

    for field_name, new_value in group_data.items():
        if getattr(group, field_name) != new_value:
            setattr(group, field_name, new_value)
            update_fields.append(field_name)

    if source_changed:
        group.source_changed_at = now
        update_fields.append("source_changed_at")

        if group.catalog_status == MarvelIngestionGroup.CATALOG_STATUS_APPLIED:
            group.catalog_status = MarvelIngestionGroup.CATALOG_STATUS_UPDATE_AVAILABLE
            update_fields.append("catalog_status")

    if update_fields:
        group.save(update_fields=dedupe(update_fields))
        return group, "updated", source_changed

    return group, "unchanged", source_changed


def upsert_candidate(*, group, facts):
    now = timezone.now()

    candidate = ComicVineVolumeCandidate.objects.filter(
        comicvine_volume=facts.volume,
    ).first()

    candidate_data = {
        "group": group,
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
        "source_volume_date_last_updated": facts.source_volume_date_last_updated,
        "source_issue_fingerprint": facts.source_issue_fingerprint,
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at": now,
    }

    if candidate is None:
        candidate = ComicVineVolumeCandidate.objects.create(
            comicvine_volume=facts.volume,
            **candidate_data,
        )
        return candidate, "created", False

    source_changed = (
        candidate.source_volume_date_last_updated
        != candidate_data["source_volume_date_last_updated"]
        or candidate.source_issue_fingerprint != candidate_data["source_issue_fingerprint"]
    )

    update_fields = []

    for field_name, new_value in candidate_data.items():
        if getattr(candidate, field_name) != new_value:
            setattr(candidate, field_name, new_value)
            update_fields.append(field_name)

    if source_changed:
        candidate.source_changed_at = now
        update_fields.append("source_changed_at")

        if candidate.catalog_status == ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED:
            candidate.catalog_status = (
                ComicVineVolumeCandidate.CATALOG_STATUS_UPDATE_AVAILABLE
            )
            update_fields.append("catalog_status")

    if update_fields:
        candidate.save(update_fields=dedupe(update_fields))
        return candidate, "updated", source_changed

    return candidate, "unchanged", source_changed


def find_containment_decisions(volume_facts_list):
    decisions = []

    for possible_run in volume_facts_list:
        for possible_collected_volume in volume_facts_list:
            if possible_run.volume.comicvine_id == possible_collected_volume.volume.comicvine_id:
                continue

            if not has_comparable_date_range(possible_run, possible_collected_volume):
                continue

            if strictly_contains(possible_run, possible_collected_volume):
                decisions.append(
                    ContainmentDecision(
                        run_volume_id=possible_run.volume.comicvine_id,
                        collected_volume_id=possible_collected_volume.volume.comicvine_id,
                        date_type=possible_run.source_date_type,
                        reason=(
                            "Source date range is strictly contained inside another "
                            "Marvel source volume with the exact same source volume name."
                        ),
                    )
                )

    return decisions


def has_comparable_date_range(possible_run, possible_collected_volume):
    if possible_run.source_date_type == ComicVineVolumeCandidate.DATE_TYPE_UNKNOWN:
        return False

    if possible_collected_volume.source_date_type == ComicVineVolumeCandidate.DATE_TYPE_UNKNOWN:
        return False

    if possible_run.source_date_type != possible_collected_volume.source_date_type:
        return False

    required_dates = [
        possible_run.first_issue_date,
        possible_run.last_issue_date,
        possible_collected_volume.first_issue_date,
        possible_collected_volume.last_issue_date,
    ]

    return all(date_value is not None for date_value in required_dates)


def strictly_contains(possible_run, possible_collected_volume):
    contains_range = (
        possible_collected_volume.first_issue_date >= possible_run.first_issue_date
        and possible_collected_volume.last_issue_date <= possible_run.last_issue_date
    )
    strictly_wider = (
        possible_collected_volume.first_issue_date > possible_run.first_issue_date
        or possible_collected_volume.last_issue_date < possible_run.last_issue_date
    )

    return contains_range and strictly_wider


def upsert_containment(*, group, run_candidate, collected_candidate, decision):
    now = timezone.now()

    containment = MarvelVolumeContainment.objects.filter(
        run_candidate=run_candidate,
        collected_volume_candidate=collected_candidate,
    ).first()

    containment_data = {
        "group": group,
        "date_type": decision.date_type,
        "run_first_issue_date": run_candidate.first_issue_date,
        "run_last_issue_date": run_candidate.last_issue_date,
        "collected_first_issue_date": collected_candidate.first_issue_date,
        "collected_last_issue_date": collected_candidate.last_issue_date,
        "analysis_version": ANALYSIS_VERSION,
        "status": MarvelVolumeContainment.STATUS_CONFIRMED_BY_RULE,
        "determination_source": MarvelVolumeContainment.DETERMINATION_SOURCE_ALGORITHM,
        "determination_reason": decision.reason,
        "run_source_issue_fingerprint": run_candidate.source_issue_fingerprint,
        "collected_source_issue_fingerprint": collected_candidate.source_issue_fingerprint,
        "analyzed_at": now,
    }

    if containment is None:
        containment = MarvelVolumeContainment.objects.create(
            run_candidate=run_candidate,
            collected_volume_candidate=collected_candidate,
            **containment_data,
        )
        return containment, "created"

    update_fields = []

    for field_name, new_value in containment_data.items():
        if getattr(containment, field_name) != new_value:
            setattr(containment, field_name, new_value)
            update_fields.append(field_name)

    if update_fields:
        containment.save(update_fields=dedupe(update_fields))
        return containment, "updated"

    return containment, "unchanged"


def invalidate_stale_algorithm_containments(*, group, current_pair_keys):
    now = timezone.now()
    invalidated_count = 0

    stale_containments = MarvelVolumeContainment.objects.filter(
        group=group,
        determination_source=MarvelVolumeContainment.DETERMINATION_SOURCE_ALGORITHM,
    ).exclude(
        status=MarvelVolumeContainment.STATUS_INVALIDATED_BY_SOURCE_CHANGE,
    )

    for containment in stale_containments:
        pair_key = (
            containment.run_candidate_id,
            containment.collected_volume_candidate_id,
        )

        if pair_key in current_pair_keys:
            continue

        containment.status = MarvelVolumeContainment.STATUS_INVALIDATED_BY_SOURCE_CHANGE
        containment.source_changed_at = now
        containment.determination_reason = (
            "This relationship was not confirmed by the latest exact-name analysis."
        )
        containment.save(
            update_fields=[
                "status",
                "source_changed_at",
                "determination_reason",
            ]
        )
        invalidated_count += 1

    return invalidated_count


def classify_group_candidates(
    *,
    group,
    group_facts,
    candidates_by_volume_id,
    containment_decisions,
):
    now = timezone.now()

    contained_by = {}
    contains_children = {}

    for decision in containment_decisions:
        contained_by.setdefault(decision.collected_volume_id, set()).add(
            decision.run_volume_id
        )
        contains_children.setdefault(decision.run_volume_id, set()).add(
            decision.collected_volume_id
        )

    counts = {
        "confirmed_runs": 0,
        "confirmed_collected_volumes": 0,
        "unresolved": 0,
        "conflicts": 0,
        "insufficient_data": 0,
    }

    for facts in group_facts.volume_facts:
        candidate = candidates_by_volume_id[facts.volume.comicvine_id]
        parent_ids = contained_by.get(facts.volume.comicvine_id, set())
        child_ids = contains_children.get(facts.volume.comicvine_id, set())

        classification = classify_candidate(
            facts=facts,
            group_facts=group_facts,
            parent_ids=parent_ids,
            child_ids=child_ids,
        )

        apply_candidate_classification(
            candidate=candidate,
            classification=classification,
            parent_ids=parent_ids,
            candidates_by_volume_id=candidates_by_volume_id,
            now=now,
        )

        counts[classification["count_key"]] += 1

    return counts


def classify_candidate(*, facts, group_facts, parent_ids, child_ids):
    if not has_usable_date_range(facts):
        return {
            "suggested_kind": ComicVineVolumeCandidate.KIND_UNKNOWN,
            "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA,
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_NOT_READY,
            "determination_source": ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
            "analysis_reason": "No usable issue date range was available.",
            "count_key": "insufficient_data",
        }

    if len(parent_ids) > 1:
        return {
            "suggested_kind": ComicVineVolumeCandidate.KIND_UNKNOWN,
            "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFLICT,
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_BLOCKED,
            "determination_source": ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
            "analysis_reason": (
                "This source range is strictly contained by multiple possible run sources "
                "with the exact same source volume name."
            ),
            "count_key": "conflicts",
        }

    if len(parent_ids) == 1:
        return {
            "suggested_kind": ComicVineVolumeCandidate.KIND_COLLECTED_VOLUME,
            "analysis_status": (
                ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
            ),
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
            "determination_source": ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
            "analysis_reason": (
                "This source range is strictly contained inside one broader source range "
                "with the exact same source volume name."
            ),
            "count_key": "confirmed_collected_volumes",
        }

    if child_ids:
        return {
            "suggested_kind": ComicVineVolumeCandidate.KIND_RUN,
            "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
            "determination_source": ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
            "analysis_reason": (
                "This source range strictly contains one or more related source ranges "
                "with the exact same source volume name."
            ),
            "count_key": "confirmed_runs",
        }

    if group_facts.source_volume_count > 1 and facts.source_issue_count > 1:
        return {
            "suggested_kind": ComicVineVolumeCandidate.KIND_RUN,
            "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
            "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
            "determination_source": ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
            "analysis_reason": (
                "This source shares an exact source volume name with other records and "
                "has multiple issues, so it is treated as a run source."
            ),
            "count_key": "confirmed_runs",
        }

    return {
        "suggested_kind": ComicVineVolumeCandidate.KIND_UNKNOWN,
        "analysis_status": ComicVineVolumeCandidate.ANALYSIS_STATUS_UNRESOLVED,
        "catalog_status": ComicVineVolumeCandidate.CATALOG_STATUS_NOT_READY,
        "determination_source": ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
        "analysis_reason": (
            "A usable issue date range exists, but no exact-name strict containment "
            "relationship was found."
        ),
        "count_key": "unresolved",
    }


def apply_candidate_classification(
    *,
    candidate,
    classification,
    parent_ids,
    candidates_by_volume_id,
    now,
):
    update_fields = []

    parent_candidate = None

    if len(parent_ids) == 1:
        parent_volume_id = next(iter(parent_ids))
        parent_candidate = candidates_by_volume_id[parent_volume_id]

    algorithm_can_update = (
        candidate.determination_source
        != ComicVineVolumeCandidate.DETERMINATION_SOURCE_MANUAL
        and candidate.review_status
        != ComicVineVolumeCandidate.REVIEW_STATUS_CONFIRMED
    )

    if algorithm_can_update:
        algorithm_fields = {
            "suggested_kind": classification["suggested_kind"],
            "analysis_status": classification["analysis_status"],
            "determination_source": classification["determination_source"],
            "analysis_reason": classification["analysis_reason"],
            "proposed_parent_run_candidate": parent_candidate,
        }

        for field_name, new_value in algorithm_fields.items():
            if getattr(candidate, field_name) != new_value:
                setattr(candidate, field_name, new_value)
                update_fields.append(field_name)

        if candidate.catalog_status != ComicVineVolumeCandidate.CATALOG_STATUS_APPLIED:
            if candidate.catalog_status != classification["catalog_status"]:
                candidate.catalog_status = classification["catalog_status"]
                update_fields.append("catalog_status")

    candidate.analyzed_at = now
    update_fields.append("analyzed_at")

    if update_fields:
        candidate.save(update_fields=dedupe(update_fields))


def update_group_analysis_status(
    *,
    group,
    candidate_status_counts,
    containment_decisions,
):
    now = timezone.now()

    if candidate_status_counts["conflicts"]:
        analysis_status = MarvelIngestionGroup.ANALYSIS_STATUS_CONFLICT
        catalog_status = MarvelIngestionGroup.CATALOG_STATUS_BLOCKED
        reason = "One or more volume candidates had conflicting containment results."
    elif containment_decisions:
        analysis_status = MarvelIngestionGroup.ANALYSIS_STATUS_CONFIRMED
        catalog_status = MarvelIngestionGroup.CATALOG_STATUS_READY_TO_APPLY
        reason = "At least one exact-name strict containment relationship was confirmed."
    elif candidate_status_counts["confirmed_runs"]:
        analysis_status = MarvelIngestionGroup.ANALYSIS_STATUS_CONFIRMED
        catalog_status = MarvelIngestionGroup.CATALOG_STATUS_READY_TO_APPLY
        reason = "One or more exact-name grouped run sources were confirmed."
    elif (
        candidate_status_counts["insufficient_data"]
        and not candidate_status_counts["unresolved"]
    ):
        analysis_status = MarvelIngestionGroup.ANALYSIS_STATUS_INSUFFICIENT_DATA
        catalog_status = MarvelIngestionGroup.CATALOG_STATUS_NOT_READY
        reason = "No candidates in this group had enough date data for containment."
    else:
        analysis_status = MarvelIngestionGroup.ANALYSIS_STATUS_UNRESOLVED
        catalog_status = MarvelIngestionGroup.CATALOG_STATUS_NOT_READY
        reason = "No exact-name strict containment relationship was confirmed for this group."

    update_fields = []

    if group.analysis_status != analysis_status:
        group.analysis_status = analysis_status
        update_fields.append("analysis_status")

    if group.catalog_status != MarvelIngestionGroup.CATALOG_STATUS_APPLIED:
        if group.catalog_status != catalog_status:
            group.catalog_status = catalog_status
            update_fields.append("catalog_status")

    if group.determination_source != MarvelIngestionGroup.DETERMINATION_SOURCE_ALGORITHM:
        group.determination_source = MarvelIngestionGroup.DETERMINATION_SOURCE_ALGORITHM
        update_fields.append("determination_source")

    if group.analysis_reason != reason:
        group.analysis_reason = reason
        update_fields.append("analysis_reason")

    group.analyzed_at = now
    update_fields.append("analyzed_at")

    if update_fields:
        group.save(update_fields=dedupe(update_fields))


def has_usable_date_range(facts):
    return (
        facts.source_date_type != ComicVineVolumeCandidate.DATE_TYPE_UNKNOWN
        and facts.first_issue_date is not None
        and facts.last_issue_date is not None
    )


def normalize_volume_name_for_exact_grouping(title, *, fallback_id):
    title = clean_title(title)

    if not title:
        title = f"Unknown Comic Vine Volume {fallback_id}"

    title = title.casefold()
    title = title.replace("&", " and ")
    title = re.sub(r"[^a-z0-9]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    if title.startswith("the "):
        title = title[4:].strip()

    if not title:
        return f"unknown comic vine volume {fallback_id}"

    return title


def clean_title(value):
    value = clean_text(value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


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