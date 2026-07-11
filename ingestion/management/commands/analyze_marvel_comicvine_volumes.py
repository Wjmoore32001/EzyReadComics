import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from html import unescape

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from django.utils.html import strip_tags

from comicvine.models import ComicVineIssue, ComicVineVolume
from ingestion.models import ComicVineVolumeCandidate


PUBLISHER_NAME = "Marvel"
ANALYSIS_VERSION = 4

VOLUME_MARKER_TITLE_PATTERN = re.compile(
    r"^\s*(?:volume\b|vol(?:\.|\b))",
    re.IGNORECASE,
)
STANDARD_ISSUE_NUMBER_PATTERN = re.compile(
    r"^#?\s*(?P<number>\d+)(?:[A-Za-z]+|\.[A-Za-z0-9]+)?$"
)


@dataclass
class VolumeFacts:
    volume: ComicVineVolume
    issues: list[ComicVineIssue]
    title: str
    normalized_title: str
    start_year: str
    local_issue_count: int
    expected_issue_count: int | None
    source_date_type: str
    first_issue_date: date | None
    last_issue_date: date | None
    first_issue_number: str
    last_issue_number: str
    source_fingerprint: str
    missing_comicvine_ids: int
    missing_issue_numbers: int
    duplicate_issue_numbers: list[str]
    standard_issue_numbers: list[int]
    longest_number_streak: int
    volume_marker_issue_count: int
    volume_marker_issue_titles: list[str]


@dataclass(frozen=True)
class Classification:
    analysis_status: str
    catalog_status: str
    reason: str


@dataclass
class AnalysisItem:
    facts: VolumeFacts
    classification: Classification
    effective_status: str
    action: str
    source_changed: bool
    manual_classification_preserved: bool = False


@dataclass
class AnalysisResult:
    source_volumes_seen: int = 0
    source_issues_seen: int = 0
    blank_publisher_volumes: int = 0
    candidates_created: int = 0
    candidates_updated: int = 0
    candidates_unchanged: int = 0
    confirmed_runs: int = 0
    collection_like_sources: int = 0
    unresolved_sources: int = 0
    conflicting_sources: int = 0
    insufficient_sources: int = 0
    source_changed: int = 0
    items: list[AnalysisItem] = field(default_factory=list)


class Command(BaseCommand):
    help = (
        "Classify local Marvel Comic Vine volumes as confirmed issue-bearing "
        "runs or unresolved/not-confirmed sources. Collected volumes are not "
        "classified, analyzed, or created."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--comicvine-volume-id",
            type=int,
            action="append",
            dest="comicvine_volume_ids",
            help=(
                "Optional Comic Vine volume ID. Repeat to select multiple volumes. "
                "If omitted, all local Marvel volumes are selected."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Optional maximum number of selected source volumes.",
        )

        mode_group = parser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyze without saving ingestion candidates.",
        )
        mode_group.add_argument(
            "--apply",
            action="store_true",
            help="Save run classifications to existing ingestion candidate rows.",
        )

    def handle(self, *args, **options):
        volume_ids = dedupe(options["comicvine_volume_ids"] or [])
        limit = options["limit"]
        dry_run = options["dry_run"]

        validate_options(volume_ids=volume_ids, limit=limit)
        selected_volumes = list_selected_volumes(volume_ids=volume_ids, limit=limit)

        self.write_header(
            selected_volumes=selected_volumes,
            volume_ids=volume_ids,
            limit=limit,
            dry_run=dry_run,
        )

        with transaction.atomic():
            result = analyze_volumes(selected_volumes)

            if dry_run:
                transaction.set_rollback(True)

        print_result(self, result, dry_run=dry_run)

    def write_header(self, *, selected_volumes, volume_ids, limit, dry_run):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Analyze Marvel Comic Vine runs"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'save candidates'}")
        self.stdout.write("Source: local ComicVineVolume and attached ComicVineIssue rows")
        self.stdout.write("Comic Vine API calls: none")
        self.stdout.write("Catalog writes: none")
        self.stdout.write("Collected-volume classification, analysis, and writes: none")
        self.stdout.write(
            "Run rule: at least two attached local issues, no child issue title "
            "starting with Vol./Volume, and safe issue IDs/numbers"
        )
        self.stdout.write(
            "Unresolved rule: any attached child issue title starting with Vol./Volume "
            "is treated as unsafe/unknown and is not applied as a run"
        )
        self.stdout.write("Comic Vine count_of_issues threshold: not used")
        self.stdout.write("Title/date overlap rule: not used")
        self.stdout.write(f"Selected source volumes: {len(selected_volumes)}")

        if volume_ids:
            self.stdout.write(
                "Selected Comic Vine volume IDs: "
                + ", ".join(str(value) for value in volume_ids)
            )
        else:
            self.stdout.write("Selected Comic Vine volume IDs: all local Marvel volumes")

        self.stdout.write(f"Limit: {limit if limit is not None else 'none'}")


def validate_options(*, volume_ids, limit):
    if any(value < 1 for value in volume_ids):
        raise CommandError("--comicvine-volume-id values must be positive integers.")

    if limit is not None and limit < 1:
        raise CommandError("--limit must be at least 1.")


def list_selected_volumes(*, volume_ids, limit):
    issue_queryset = ComicVineIssue.objects.order_by("id")
    queryset = ComicVineVolume.objects.prefetch_related(
        Prefetch("issues", queryset=issue_queryset, to_attr="analysis_issues")
    )

    if volume_ids:
        selected = list(queryset.filter(comicvine_id__in=volume_ids))
        found_ids = {volume.comicvine_id for volume in selected}
        missing_ids = [value for value in volume_ids if value not in found_ids]

        if missing_ids:
            raise CommandError(
                "Local ComicVineVolume rows were not found for IDs: "
                + ", ".join(str(value) for value in missing_ids)
            )
    else:
        selected = list(queryset.filter(publisher__iexact=PUBLISHER_NAME))

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


def analyze_volumes(volumes):
    result = AnalysisResult(
        source_volumes_seen=len(volumes),
        source_issues_seen=sum(len(volume.analysis_issues) for volume in volumes),
        blank_publisher_volumes=sum(1 for volume in volumes if not clean_text(volume.publisher)),
    )

    for volume in volumes:
        facts = build_volume_facts(volume)
        classification = classify_volume(facts)
        candidate, action, source_changed, manual_preserved = upsert_candidate(
            facts=facts,
            classification=classification,
        )
        item = AnalysisItem(
            facts=facts,
            classification=classification,
            effective_status=candidate.analysis_status,
            action=action,
            source_changed=source_changed,
            manual_classification_preserved=manual_preserved,
        )
        result.items.append(item)
        record_action(result, action)

        if source_changed:
            result.source_changed += 1

        if candidate.analysis_status == candidate.ANALYSIS_STATUS_CONFIRMED_RUN:
            result.confirmed_runs += 1
        elif candidate.analysis_status == candidate.ANALYSIS_STATUS_COLLECTION_CONTAINER:
            result.collection_like_sources += 1
        elif candidate.analysis_status == candidate.ANALYSIS_STATUS_CONFLICT:
            result.conflicting_sources += 1
        elif candidate.analysis_status == candidate.ANALYSIS_STATUS_INSUFFICIENT_DATA:
            result.insufficient_sources += 1
        else:
            result.unresolved_sources += 1

    return result


def build_volume_facts(volume):
    issues = list(volume.analysis_issues)
    normalized_issue_numbers = [
        normalize_issue_number(issue.issue_number)
        for issue in issues
        if normalize_issue_number(issue.issue_number)
    ]
    duplicate_issue_numbers = sorted(find_duplicates(normalized_issue_numbers))
    standard_issue_numbers = sorted(
        {
            parsed_number
            for issue in issues
            if (parsed_number := parse_standard_issue_number(issue.issue_number))
            is not None
        }
    )
    source_date_type, first_issue_date, last_issue_date = choose_source_dates(issues)
    volume_marker_issue_titles = [
        clean_html_text(issue.issue_title)
        for issue in issues
        if child_issue_title_starts_with_volume_marker(issue.issue_title)
    ]

    return VolumeFacts(
        volume=volume,
        issues=issues,
        title=(
            clean_html_text(volume.name)
            or f"Unknown Comic Vine Volume {volume.comicvine_id}"
        ),
        normalized_title=normalize_title(volume.name, fallback_id=volume.comicvine_id),
        start_year=clean_text(volume.start_year),
        local_issue_count=len(issues),
        expected_issue_count=volume.count_of_issues,
        source_date_type=source_date_type,
        first_issue_date=first_issue_date,
        last_issue_date=last_issue_date,
        first_issue_number=derive_boundary_issue_number(issues, first=True),
        last_issue_number=derive_boundary_issue_number(issues, first=False),
        source_fingerprint=build_source_fingerprint(volume, issues),
        missing_comicvine_ids=sum(1 for issue in issues if not issue.comicvine_id),
        missing_issue_numbers=sum(
            1 for issue in issues if not normalize_issue_number(issue.issue_number)
        ),
        duplicate_issue_numbers=duplicate_issue_numbers,
        standard_issue_numbers=standard_issue_numbers,
        longest_number_streak=longest_consecutive_streak(standard_issue_numbers),
        volume_marker_issue_count=len(volume_marker_issue_titles),
        volume_marker_issue_titles=volume_marker_issue_titles,
    )


def classify_volume(facts):
    not_ready = ComicVineVolumeCandidate.CATALOG_STATUS_NOT_READY

    if clean_text(facts.volume.publisher).casefold() != PUBLISHER_NAME.casefold():
        publisher = clean_text(facts.volume.publisher) or "blank"
        return Classification(
            ComicVineVolumeCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA,
            not_ready,
            f"Publisher is {publisher!r}, not an exact local Marvel value.",
        )

    if not facts.issues:
        return Classification(
            ComicVineVolumeCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA,
            not_ready,
            "No local Comic Vine issues are attached to this volume.",
        )

    if not facts.start_year:
        return Classification(
            ComicVineVolumeCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA,
            not_ready,
            "The Comic Vine volume has no local start year, so it cannot be safely keyed as a catalog run.",
        )

    if facts.volume_marker_issue_count:
        samples = ", ".join(repr(title) for title in facts.volume_marker_issue_titles[:3])
        extra = "" if facts.volume_marker_issue_count <= 3 else ", ..."
        return Classification(
            ComicVineVolumeCandidate.ANALYSIS_STATUS_UNRESOLVED,
            not_ready,
            "Unsafe to confirm as a run: "
            f"{facts.volume_marker_issue_count} child issue title(s) start with Vol./Volume "
            f"({samples}{extra}). This may be a collected-volume/product source, "
            "but this command does not classify collections.",
        )

    if facts.missing_comicvine_ids or facts.missing_issue_numbers:
        return Classification(
            ComicVineVolumeCandidate.ANALYSIS_STATUS_INSUFFICIENT_DATA,
            not_ready,
            "One or more child issues lack a Comic Vine ID or issue number.",
        )

    if facts.duplicate_issue_numbers:
        return Classification(
            ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFLICT,
            not_ready,
            "Duplicate normalized issue numbers prevent a safe run import: "
            + ", ".join(facts.duplicate_issue_numbers),
        )

    if facts.local_issue_count < 2:
        return Classification(
            ComicVineVolumeCandidate.ANALYSIS_STATUS_UNRESOLVED,
            not_ready,
            "Unsafe to confirm as a run: only one local Comic Vine issue is attached. "
            "This may be a one-shot, special, facsimile, collected product record, or a run "
            "that has not been fully hydrated yet.",
        )

    return Classification(
        ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
        ComicVineVolumeCandidate.CATALOG_STATUS_READY_TO_APPLY,
        "Confirmed from attached Comic Vine issue rows: at least two child issues exist, "
        "no child issue title starts with Vol./Volume, and child issue IDs/numbers are usable and unique.",
    )


def upsert_candidate(*, facts, classification):
    now = timezone.now()
    candidate = ComicVineVolumeCandidate.objects.filter(
        comicvine_volume=facts.volume
    ).first()
    candidate_data = {
        "publisher_name": clean_text(facts.volume.publisher),
        "title": facts.title,
        "normalized_title": facts.normalized_title,
        "start_year": facts.start_year,
        "source_issue_count": facts.local_issue_count,
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
            analysis_status=classification.analysis_status,
            catalog_status=classification.catalog_status,
            determination_source=ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
            analysis_reason=classification.reason,
            **candidate_data,
        )
        return candidate, "created", False, False

    source_changed = candidate.source_fingerprint != facts.source_fingerprint
    manual_preserved = (
        candidate.determination_source
        == ComicVineVolumeCandidate.DETERMINATION_SOURCE_MANUAL
        or candidate.review_status == ComicVineVolumeCandidate.REVIEW_STATUS_CONFIRMED
    )
    old_analysis_status = candidate.analysis_status
    update_fields = assign_changed_fields(candidate, candidate_data)

    if not manual_preserved:
        update_fields.extend(
            assign_changed_fields(
                candidate,
                {
                    "analysis_status": classification.analysis_status,
                    "analysis_reason": classification.reason,
                    "determination_source": ComicVineVolumeCandidate.DETERMINATION_SOURCE_ALGORITHM,
                },
            )
        )

        classification_changed = old_analysis_status != classification.analysis_status

        if candidate.catalog_status == candidate.CATALOG_STATUS_APPLIED:
            if source_changed or classification_changed:
                candidate.catalog_status = candidate.CATALOG_STATUS_UPDATE_AVAILABLE
                update_fields.append("catalog_status")
        else:
            update_fields.extend(
                assign_changed_fields(
                    candidate,
                    {"catalog_status": classification.catalog_status},
                )
            )
    elif source_changed and candidate.catalog_status == candidate.CATALOG_STATUS_APPLIED:
        candidate.catalog_status = candidate.CATALOG_STATUS_UPDATE_AVAILABLE
        update_fields.append("catalog_status")

    if source_changed:
        candidate.source_changed_at = now
        update_fields.append("source_changed_at")

    update_fields = dedupe(update_fields)

    if update_fields:
        candidate.save(update_fields=update_fields)
        return candidate, "updated", source_changed, manual_preserved

    return candidate, "unchanged", source_changed, manual_preserved


def choose_source_dates(issues):
    dated_rows = []

    for issue in issues:
        if issue.store_date:
            dated_rows.append((issue.store_date, "store"))
        elif issue.cover_date:
            dated_rows.append((issue.cover_date, "cover"))

    if not dated_rows:
        return ComicVineVolumeCandidate.DATE_TYPE_UNKNOWN, None, None

    kinds = {kind for _value, kind in dated_rows}
    if kinds == {"store"}:
        date_type = ComicVineVolumeCandidate.DATE_TYPE_STORE_DATE
    elif kinds == {"cover"}:
        date_type = ComicVineVolumeCandidate.DATE_TYPE_COVER_DATE
    else:
        date_type = ComicVineVolumeCandidate.DATE_TYPE_BEST_AVAILABLE

    values = [value for value, _kind in dated_rows]
    return date_type, min(values), max(values)


def derive_boundary_issue_number(issues, *, first):
    numbered = []

    for issue in issues:
        value = clean_issue_number(issue.issue_number)
        parsed = parse_standard_issue_number(value)
        if value:
            numbered.append((parsed is None, parsed if parsed is not None else 0, value))

    if not numbered:
        return ""

    numbered.sort()
    return numbered[0 if first else -1][2]


def parse_standard_issue_number(value):
    match = STANDARD_ISSUE_NUMBER_PATTERN.match(clean_text(value))
    return int(match.group("number")) if match else None


def longest_consecutive_streak(numbers):
    if not numbers:
        return 0

    longest = 1
    current = 1

    for previous, value in zip(numbers, numbers[1:]):
        if value == previous + 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1

    return longest


def child_issue_title_starts_with_volume_marker(value):
    return bool(VOLUME_MARKER_TITLE_PATTERN.match(clean_html_text(value)))


def build_source_fingerprint(volume, issues):
    lines = [
        str(volume.comicvine_id),
        clean_text(volume.name),
        clean_text(volume.publisher),
        clean_text(volume.start_year),
        clean_text(volume.count_of_issues),
        clean_text(volume.date_last_updated),
        clean_text(volume.description),
        clean_text(volume.display_image_url),
    ]

    for issue in sorted(issues, key=lambda item: (item.comicvine_id or 0, item.id)):
        lines.extend(
            [
                clean_text(issue.comicvine_id),
                clean_text(issue.issue_number),
                clean_text(issue.issue_title),
                clean_text(issue.store_date),
                clean_text(issue.cover_date),
                clean_text(issue.date_last_updated),
                clean_text(issue.description),
                clean_text(getattr(issue, "display_image_url", "")),
            ]
        )

    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def assign_changed_fields(instance, values):
    changed_fields = []
    for field_name, value in values.items():
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed_fields.append(field_name)
    return changed_fields


def normalize_title(value, *, fallback_id):
    title = clean_html_text(value).casefold()
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    return title or f"comic-vine-{fallback_id}"


def normalize_issue_number(value):
    return clean_issue_number(value).casefold()


def clean_issue_number(value):
    return re.sub(r"\s+", "", clean_text(value).lstrip("#"))


def clean_html_text(value):
    if value is None:
        return ""
    return " ".join(unescape(strip_tags(str(value))).split())


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


def record_action(result, action):
    if action == "created":
        result.candidates_created += 1
    elif action == "updated":
        result.candidates_updated += 1
    else:
        result.candidates_unchanged += 1


def print_result(command, result, *, dry_run):
    prefix = "Would " if dry_run else ""
    command.stdout.write("")
    command.stdout.write("Per-volume decisions:")

    for item in result.items:
        facts = item.facts
        manual_note = " | manual classification preserved" if item.manual_classification_preserved else ""
        command.stdout.write(
            f"  CV {facts.volume.comicvine_id}: {facts.title} ({facts.start_year or 'unknown'}) "
            f"-> {item.effective_status} [{item.action}]{manual_note}"
        )
        command.stdout.write(
            "    Evidence: "
            f"local/expected issues={facts.local_issue_count}/{facts.expected_issue_count or 'unknown'}, "
            f"missing ids={facts.missing_comicvine_ids}, "
            f"missing numbers={facts.missing_issue_numbers}, "
            f"duplicate numbers={len(facts.duplicate_issue_numbers)}, "
            f"Vol./Volume child titles={facts.volume_marker_issue_count}"
        )
        command.stdout.write(f"    Reason: {item.classification.reason}")

    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Run complete."))
    command.stdout.write("=" * 60)
    command.stdout.write(f"Source volumes seen: {result.source_volumes_seen}")
    command.stdout.write(f"Source issues seen: {result.source_issues_seen}")
    command.stdout.write(f"Selected volumes with blank publisher: {result.blank_publisher_volumes}")
    command.stdout.write(f"{prefix}run candidates created: {result.candidates_created}")
    command.stdout.write(f"{prefix}run candidates updated: {result.candidates_updated}")
    command.stdout.write(f"{prefix}run candidates unchanged: {result.candidates_unchanged}")
    command.stdout.write(f"Confirmed runs: {result.confirmed_runs}")
    command.stdout.write(f"Collection-container sources: {result.collection_like_sources}")
    command.stdout.write(f"Unresolved / unsafe sources: {result.unresolved_sources}")
    command.stdout.write(f"Conflicting sources: {result.conflicting_sources}")
    command.stdout.write(f"Insufficient-data sources: {result.insufficient_sources}")
    command.stdout.write(f"Source changed since last analysis: {result.source_changed}")
    command.stdout.write("Collected candidates analyzed or changed: 0")

    if dry_run:
        command.stdout.write("")
        command.stdout.write("Dry run only. No database changes were saved.")
