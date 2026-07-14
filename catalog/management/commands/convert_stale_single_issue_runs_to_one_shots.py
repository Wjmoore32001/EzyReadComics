import calendar
from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from catalog.models import (
    ComicIssueCredit,
    ComicOneShot,
    ComicOneShotCredit,
    ComicRun,
    ComicRunCredit,
    ComicVolumeIssue,
    ComicVolumeOneShot,
    ComicVolumeRun,
)
from reading.models import FollowedRun, IssueProgress


MONTH_THRESHOLD = 3

IMAGE_FIELDS = [
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
    "display_image_url",
]


@dataclass
class ConversionResult:
    run_id: int
    run_title: str
    issue_id: int = None
    issue_number: str = ""
    published_date: object = None

    converted: bool = False
    skipped: bool = False
    skip_reason: str = ""

    one_shot_created: int = 0
    one_shot_reused: int = 0
    one_shot_updated: int = 0

    one_shot_id: int = None
    one_shot_title: str = ""

    run_credits_copied: int = 0
    issue_credits_copied: int = 0
    volume_issue_links_copied: int = 0
    volume_run_links_copied: int = 0

    run_rows_deleted: int = 0
    issue_rows_deleted: int = 0
    run_credit_rows_deleted: int = 0
    issue_credit_rows_deleted: int = 0
    followed_run_rows_deleted: int = 0
    issue_progress_rows_deleted: int = 0
    volume_issue_rows_deleted: int = 0
    volume_run_rows_deleted: int = 0

    deleted_object_count: int = 0
    deleted_object_summary: dict = field(default_factory=dict)


class Command(BaseCommand):
    help = (
        "Convert stale catalog runs with exactly one attached issue into one-shot rows. "
        "The base command applies changes. Use --dry-run to preview only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview only. Without this flag, the command writes changes.",
        )
        parser.add_argument(
            "--today",
            help=(
                "Override today's date for testing, YYYY-MM-DD. "
                "Default: Django timezone.localdate()."
            ),
        )
        parser.add_argument(
            "--publisher",
            help="Optional publisher name filter, case-insensitive.",
        )
        parser.add_argument(
            "--run-id",
            dest="run_ids",
            action="append",
            type=int,
            help="Optional run ID to check. Can be passed more than once.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Optional maximum number of single-issue runs to scan.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each converted row.",
        )
        parser.add_argument(
            "--show-all-skips",
            action="store_true",
            help="Print every skipped row, including rows that are not older than the cutoff.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today = parse_today(options["today"]) if options["today"] else timezone.localdate()
        cutoff_date = subtract_months(today, MONTH_THRESHOLD)

        queryset = (
            ComicRun.objects.annotate(single_issue_count=Count("issues", distinct=True))
            .filter(single_issue_count=1)
            .select_related("publisher")
            .order_by("publisher__name", "title", "start_year", "id")
        )

        if options["publisher"]:
            queryset = queryset.filter(publisher__name__iexact=options["publisher"].strip())

        if options["run_ids"]:
            queryset = queryset.filter(id__in=options["run_ids"])

        if options["limit"] is not None:
            queryset = queryset[: options["limit"]]

        run_ids = list(queryset.values_list("id", flat=True))

        totals = {
            "scanned": 0,
            "converted": 0,
            "skipped": 0,
            "one_shots_created": 0,
            "one_shots_reused": 0,
            "one_shots_updated": 0,
            "run_credits_copied": 0,
            "issue_credits_copied": 0,
            "volume_issue_links_copied": 0,
            "volume_run_links_copied": 0,
            "run_rows_deleted": 0,
            "issue_rows_deleted": 0,
            "run_credit_rows_deleted": 0,
            "issue_credit_rows_deleted": 0,
            "followed_run_rows_deleted": 0,
            "issue_progress_rows_deleted": 0,
            "volume_issue_rows_deleted": 0,
            "volume_run_rows_deleted": 0,
            "deleted_object_count": 0,
        }

        self.stdout.write("Stale single-issue run to one-shot conversion")
        self.stdout.write(f"Mode: {'dry-run' if dry_run else 'apply'}")
        self.stdout.write(f"Today: {today.isoformat()}")
        self.stdout.write(
            f"Cutoff: published before {cutoff_date.isoformat()} "
            f"is more than {MONTH_THRESHOLD} months old"
        )
        self.stdout.write(f"Single-issue runs found: {len(run_ids)}")
        self.stdout.write("")

        for run_id in run_ids:
            totals["scanned"] += 1

            try:
                result = convert_run(
                    run_id=run_id,
                    cutoff_date=cutoff_date,
                    dry_run=dry_run,
                )
            except Exception as exc:
                result = ConversionResult(
                    run_id=run_id,
                    run_title=f"Run ID {run_id}",
                    skipped=True,
                    skip_reason=f"Unexpected conversion error: {exc}",
                )

            if result.converted:
                totals["converted"] += 1
                totals["one_shots_created"] += result.one_shot_created
                totals["one_shots_reused"] += result.one_shot_reused
                totals["one_shots_updated"] += result.one_shot_updated
                totals["run_credits_copied"] += result.run_credits_copied
                totals["issue_credits_copied"] += result.issue_credits_copied
                totals["volume_issue_links_copied"] += result.volume_issue_links_copied
                totals["volume_run_links_copied"] += result.volume_run_links_copied
                totals["run_rows_deleted"] += result.run_rows_deleted
                totals["issue_rows_deleted"] += result.issue_rows_deleted
                totals["run_credit_rows_deleted"] += result.run_credit_rows_deleted
                totals["issue_credit_rows_deleted"] += result.issue_credit_rows_deleted
                totals["followed_run_rows_deleted"] += result.followed_run_rows_deleted
                totals["issue_progress_rows_deleted"] += result.issue_progress_rows_deleted
                totals["volume_issue_rows_deleted"] += result.volume_issue_rows_deleted
                totals["volume_run_rows_deleted"] += result.volume_run_rows_deleted
                totals["deleted_object_count"] += result.deleted_object_count

                if options["verbose"]:
                    self.print_converted_result(result, dry_run=dry_run)

            if result.skipped:
                totals["skipped"] += 1

                if options["show_all_skips"] or should_always_print_skip(result):
                    self.print_skipped_result(result)

        self.print_summary(totals, dry_run=dry_run)

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. Re-run without --dry-run to create one-shots and delete the stale run/issue rows."
                )
            )

    def print_converted_result(self, result, *, dry_run):
        prefix = "WOULD CONVERT" if dry_run else "CONVERTED"
        self.stdout.write(
            f"{prefix}: {result.run_title} "
            f"(run id={result.run_id}, issue #{result.issue_number}, "
            f"published={format_date(result.published_date)})"
        )
        self.stdout.write(f"  One-shot: {result.one_shot_title}")
        if result.one_shot_id:
            self.stdout.write(f"  One-shot ID: {result.one_shot_id}")

    def print_skipped_result(self, result):
        self.stdout.write(
            self.style.WARNING(
                f"SKIPPED: {result.run_title} "
                f"(run id={result.run_id})"
            )
        )
        self.stdout.write(f"  Reason: {result.skip_reason}")
        if result.issue_id:
            self.stdout.write(
                f"  Issue: id={result.issue_id}, "
                f"#{result.issue_number}, "
                f"published={format_date(result.published_date)}"
            )

    def print_summary(self, totals, *, dry_run):
        label = "Would convert" if dry_run else "Converted"
        delete_label = "Would delete" if dry_run else "Deleted"

        self.stdout.write("")
        self.stdout.write("Summary")
        self.stdout.write(f"Scanned single-issue runs: {totals['scanned']}")
        self.stdout.write(f"{label} runs to one-shots: {totals['converted']}")
        self.stdout.write(f"Skipped runs: {totals['skipped']}")
        self.stdout.write(f"One-shots created: {totals['one_shots_created']}")
        self.stdout.write(f"Existing one-shots reused: {totals['one_shots_reused']}")
        self.stdout.write(f"Existing one-shots updated: {totals['one_shots_updated']}")
        self.stdout.write(f"Run credits copied to one-shots: {totals['run_credits_copied']}")
        self.stdout.write(f"Issue credits copied to one-shots: {totals['issue_credits_copied']}")
        self.stdout.write(f"Volume issue links copied to one-shots: {totals['volume_issue_links_copied']}")
        self.stdout.write(f"Volume run links copied to one-shots: {totals['volume_run_links_copied']}")
        self.stdout.write(f"{delete_label} run rows: {totals['run_rows_deleted']}")
        self.stdout.write(f"{delete_label} issue rows: {totals['issue_rows_deleted']}")
        self.stdout.write(f"{delete_label} run credit rows: {totals['run_credit_rows_deleted']}")
        self.stdout.write(f"{delete_label} issue credit rows: {totals['issue_credit_rows_deleted']}")
        self.stdout.write(f"{delete_label} followed-run rows: {totals['followed_run_rows_deleted']}")
        self.stdout.write(f"{delete_label} issue-progress rows: {totals['issue_progress_rows_deleted']}")
        self.stdout.write(f"{delete_label} volume-issue rows: {totals['volume_issue_rows_deleted']}")
        self.stdout.write(f"{delete_label} volume-run rows: {totals['volume_run_rows_deleted']}")
        self.stdout.write(f"{delete_label} total cascade objects: {totals['deleted_object_count']}")


def convert_run(*, run_id, cutoff_date, dry_run):
    if dry_run:
        return convert_run_without_writes(run_id=run_id, cutoff_date=cutoff_date)

    with transaction.atomic():
        return convert_run_with_writes(run_id=run_id, cutoff_date=cutoff_date)


def convert_run_without_writes(*, run_id, cutoff_date):
    run = get_run_for_conversion(run_id=run_id, lock=False)
    return build_conversion_result(run=run, cutoff_date=cutoff_date, dry_run=True)


def convert_run_with_writes(*, run_id, cutoff_date):
    run = get_run_for_conversion(run_id=run_id, lock=True)
    return build_conversion_result(run=run, cutoff_date=cutoff_date, dry_run=False)


def get_run_for_conversion(*, run_id, lock):
    queryset = ComicRun.objects.select_related("publisher")

    if lock:
        queryset = queryset.select_for_update()

    return queryset.get(id=run_id)


def build_conversion_result(*, run, cutoff_date, dry_run):
    issues = list(run.issues.all().order_by("id"))

    result = ConversionResult(
        run_id=run.id,
        run_title=str(run),
    )

    if len(issues) != 1:
        result.skipped = True
        result.skip_reason = f"Run has {len(issues)} attached issues, not exactly 1."
        return result

    issue = issues[0]
    result.issue_id = issue.id
    result.issue_number = issue.issue_number
    result.published_date = issue.published_date

    if not issue.published_date:
        result.skipped = True
        result.skip_reason = "Single issue has no published_date."
        return result

    if issue.published_date >= cutoff_date:
        result.skipped = True
        result.skip_reason = (
            f"Single issue is not more than {MONTH_THRESHOLD} months old. "
            f"Published date {issue.published_date.isoformat()} is not before cutoff "
            f"{cutoff_date.isoformat()}."
        )
        return result

    primary_volume_count = run.volumes.count()

    if primary_volume_count:
        result.skipped = True
        result.skip_reason = (
            f"Run is the primary run for {primary_volume_count} collected volume(s). "
            "Deleting this run would cascade-delete those volume rows, so this needs manual review."
        )
        return result

    one_shot_values = build_one_shot_values(run=run, issue=issue)
    existing_one_shot = find_existing_one_shot(
        publisher=run.publisher,
        title=one_shot_values["title"],
        start_year=one_shot_values["start_year"],
    )
    conflict_reason = get_existing_one_shot_conflict_reason(
        existing_one_shot=existing_one_shot,
        one_shot_values=one_shot_values,
    )

    if conflict_reason:
        result.skipped = True
        result.skip_reason = conflict_reason
        return result

    result.run_credit_rows_deleted = run.credits.count()
    result.issue_credit_rows_deleted = issue.credits.count()
    result.followed_run_rows_deleted = FollowedRun.objects.filter(run=run).count()
    result.issue_progress_rows_deleted = IssueProgress.objects.filter(issue=issue).count()
    result.volume_issue_rows_deleted = ComicVolumeIssue.objects.filter(issue=issue).count()
    result.volume_run_rows_deleted = ComicVolumeRun.objects.filter(run=run).count()

    if existing_one_shot:
        one_shot = existing_one_shot
        result.one_shot_reused = 1
        result.one_shot_updated = update_existing_one_shot(
            one_shot=one_shot,
            one_shot_values=one_shot_values,
            dry_run=dry_run,
        )
    else:
        result.one_shot_created = 1
        one_shot = create_one_shot(
            one_shot_values=one_shot_values,
            dry_run=dry_run,
        )

    result.one_shot_id = getattr(one_shot, "id", None)
    result.one_shot_title = str(one_shot)

    seen_credit_keys = existing_one_shot_credit_keys(one_shot=one_shot, dry_run=dry_run)

    result.issue_credits_copied = copy_credits_to_one_shot(
        source_credits=ComicIssueCredit.objects.filter(issue=issue)
        .select_related("person", "role")
        .order_by("role__display_order", "credit_order", "person__name", "id"),
        one_shot=one_shot,
        seen_credit_keys=seen_credit_keys,
        dry_run=dry_run,
    )
    result.run_credits_copied = copy_credits_to_one_shot(
        source_credits=ComicRunCredit.objects.filter(run=run)
        .select_related("person", "role")
        .order_by("role__display_order", "credit_order", "person__name", "id"),
        one_shot=one_shot,
        seen_credit_keys=seen_credit_keys,
        dry_run=dry_run,
    )

    seen_volume_ids = existing_one_shot_volume_ids(one_shot=one_shot, dry_run=dry_run)

    result.volume_issue_links_copied = copy_volume_issue_links_to_one_shot(
        issue=issue,
        one_shot=one_shot,
        seen_volume_ids=seen_volume_ids,
        dry_run=dry_run,
    )
    result.volume_run_links_copied = copy_volume_run_links_to_one_shot(
        run=run,
        one_shot=one_shot,
        seen_volume_ids=seen_volume_ids,
        dry_run=dry_run,
    )

    result.run_rows_deleted = 1
    result.issue_rows_deleted = 1

    if dry_run:
        result.deleted_object_count = (
            result.run_rows_deleted
            + result.issue_rows_deleted
            + result.run_credit_rows_deleted
            + result.issue_credit_rows_deleted
            + result.followed_run_rows_deleted
            + result.issue_progress_rows_deleted
            + result.volume_issue_rows_deleted
            + result.volume_run_rows_deleted
        )
    else:
        deleted_count, deleted_summary = run.delete()
        result.deleted_object_count = deleted_count
        result.deleted_object_summary = deleted_summary

    result.converted = True
    return result


def build_one_shot_values(*, run, issue):
    values = {
        "publisher": run.publisher,
        "title": clean_text(run.title),
        "start_year": one_shot_start_year(run=run, issue=issue),
        "official_source_key": first_clean_text(
            issue.official_source_key,
            run.official_source_key,
        ),
        "official_source_url": first_clean_text(
            issue.official_source_url,
            run.official_source_url,
        ),
        "published_date": issue.published_date or run.first_issue_date or run.last_issue_date,
        "description": first_clean_text(
            issue.description,
            run.description,
        ),
    }

    for field_name in IMAGE_FIELDS:
        values[field_name] = first_clean_text(
            getattr(issue, field_name, ""),
            getattr(run, field_name, ""),
        )

    if values["display_image_url"]:
        if clean_text(getattr(issue, "display_image_url", "")):
            values["display_image_source"] = issue.display_image_source
        elif clean_text(getattr(run, "display_image_url", "")):
            values["display_image_source"] = run.display_image_source

    return values


def one_shot_start_year(*, run, issue):
    if clean_text(run.start_year):
        return clean_text(run.start_year)

    if issue.published_date:
        return str(issue.published_date.year)

    return ""


def find_existing_one_shot(*, publisher, title, start_year):
    return (
        ComicOneShot.objects.filter(
            publisher=publisher,
            title__iexact=title,
            start_year=start_year,
        )
        .order_by("id")
        .first()
    )


def get_existing_one_shot_conflict_reason(*, existing_one_shot, one_shot_values):
    if not existing_one_shot:
        return ""

    existing_key = clean_text(existing_one_shot.official_source_key)
    new_key = clean_text(one_shot_values.get("official_source_key"))

    if existing_key and new_key and existing_key != new_key:
        return (
            "Existing one-shot with the same publisher/title/start_year has a different "
            f"official_source_key: existing={existing_key}, new={new_key}."
        )

    existing_url = clean_text(existing_one_shot.official_source_url)
    new_url = clean_text(one_shot_values.get("official_source_url"))

    if existing_url and new_url and existing_url != new_url:
        return (
            "Existing one-shot with the same publisher/title/start_year has a different "
            f"official_source_url: existing={existing_url}, new={new_url}."
        )

    return ""


def create_one_shot(*, one_shot_values, dry_run):
    if dry_run:
        return PreviewOneShot(
            title=one_shot_values["title"],
            start_year=one_shot_values["start_year"],
        )

    return ComicOneShot.objects.create(**one_shot_values)


def update_existing_one_shot(*, one_shot, one_shot_values, dry_run):
    changed = False
    had_display_image_url = bool(clean_text(one_shot.display_image_url))

    fields_to_fill_if_blank = [
        "official_source_key",
        "official_source_url",
        "published_date",
        "description",
        *IMAGE_FIELDS,
    ]

    for field_name in fields_to_fill_if_blank:
        new_value = one_shot_values.get(field_name)

        if new_value and not getattr(one_shot, field_name):
            setattr(one_shot, field_name, new_value)
            changed = True

    new_display_image_source = one_shot_values.get("display_image_source")

    if new_display_image_source and (
        not had_display_image_url
        or one_shot.display_image_source == ComicOneShot.DISPLAY_IMAGE_SOURCE_UNKNOWN
    ):
        one_shot.display_image_source = new_display_image_source
        changed = True

    if changed and not dry_run:
        one_shot.save()

    return 1 if changed else 0


def existing_one_shot_credit_keys(*, one_shot, dry_run):
    if dry_run or not getattr(one_shot, "pk", None):
        return set()

    return set(
        ComicOneShotCredit.objects.filter(one_shot=one_shot).values_list(
            "person_id",
            "role_id",
        )
    )


def copy_credits_to_one_shot(*, source_credits, one_shot, seen_credit_keys, dry_run):
    copied = 0

    for credit in source_credits:
        key = (credit.person_id, credit.role_id)

        if key in seen_credit_keys:
            continue

        seen_credit_keys.add(key)
        copied += 1

        if dry_run:
            continue

        ComicOneShotCredit.objects.create(
            one_shot=one_shot,
            person=credit.person,
            role=credit.role,
            credit_order=credit.credit_order,
        )

    return copied


def existing_one_shot_volume_ids(*, one_shot, dry_run):
    if dry_run or not getattr(one_shot, "pk", None):
        return set()

    return set(
        ComicVolumeOneShot.objects.filter(one_shot=one_shot).values_list(
            "volume_id",
            flat=True,
        )
    )


def copy_volume_issue_links_to_one_shot(*, issue, one_shot, seen_volume_ids, dry_run):
    copied = 0

    links = (
        ComicVolumeIssue.objects.filter(issue=issue)
        .select_related("volume")
        .order_by("issue_order", "volume_id", "id")
    )

    for link in links:
        if link.volume_id in seen_volume_ids:
            continue

        seen_volume_ids.add(link.volume_id)
        copied += 1

        if dry_run:
            continue

        ComicVolumeOneShot.objects.create(
            volume=link.volume,
            one_shot=one_shot,
            item_order=link.issue_order,
        )

    return copied


def copy_volume_run_links_to_one_shot(*, run, one_shot, seen_volume_ids, dry_run):
    copied = 0

    links = (
        ComicVolumeRun.objects.filter(run=run)
        .select_related("volume")
        .order_by("item_order", "volume_id", "id")
    )

    for link in links:
        if link.volume_id in seen_volume_ids:
            continue

        seen_volume_ids.add(link.volume_id)
        copied += 1

        if dry_run:
            continue

        ComicVolumeOneShot.objects.create(
            volume=link.volume,
            one_shot=one_shot,
            item_order=link.item_order,
        )

    return copied


def subtract_months(value, months):
    year = value.year
    month = value.month - months

    while month <= 0:
        month += 12
        year -= 1

    day = min(value.day, calendar.monthrange(year, month)[1])

    return value.replace(year=year, month=month, day=day)


def parse_today(value):
    try:
        year, month, day = [int(part) for part in value.split("-")]
        return timezone.datetime(year, month, day).date()
    except Exception as exc:
        raise CommandError("--today must be in YYYY-MM-DD format.") from exc


def clean_text(value):
    return str(value or "").strip()


def first_clean_text(*values):
    for value in values:
        text = clean_text(value)

        if text:
            return text

    return ""


def format_date(value):
    if not value:
        return "none"

    return value.isoformat()


def should_always_print_skip(result):
    if not result.skip_reason:
        return False

    quiet_fragments = [
        "not more than",
    ]

    reason = result.skip_reason.casefold()

    return not any(fragment in reason for fragment in quiet_fragments)


class PreviewOneShot:
    id = None
    pk = None

    def __init__(self, *, title, start_year):
        self.title = title
        self.start_year = start_year

    def __str__(self):
        if self.start_year:
            return f"{self.title} ({self.start_year})"

        return self.title