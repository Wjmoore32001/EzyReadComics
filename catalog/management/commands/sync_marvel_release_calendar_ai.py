from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from catalog.marvel.browser import (
    DEFAULT_CALENDAR_TIMEOUT_MS,
    DEFAULT_DETAIL_TIMEOUT_MS,
    MARVEL_CALENDAR_TIME_ZONE,
    ensure_playwright,
    marvel_browser_context,
)
from catalog.marvel.calendar import (
    current_marvel_date,
    build_release_calendar_url,
    read_release_calendar_page,
    extract_release_calendar_issues as extract_release_calendar_issues_dataclasses,
)
from catalog.marvel.credits import normalize_credit_list
from catalog.marvel.issues import (
    empty_issue_detail,
    get_detail_value,
    get_issue_missing_fields,
    issue_from_detail_url,
    read_issue_detail_page as read_shared_issue_detail_page,
)
from catalog.marvel.series import (
    read_issue_page_series_url,
    read_series_page,
)
from catalog.marvel.sync_planner import build_series_sync_plan
from catalog.marvel.text import (
    canonical_issue_number,
    clean_text,
    issue_number_sort_key,
    normalize_issue_number,
    normalize_title,
    pure_integer_issue_number,
)
from catalog.marvel.urls import parse_marvel_issue_url
from catalog.marvel.writer import (
    WriteResult,
    find_existing_issue,
    find_existing_run,
    issue_has_complete_details,
    issue_has_suspicious_credits,
    upsert_issue_from_series_issue,
    upsert_run_from_series,
)


DEFAULT_LIMIT = None
DEFAULT_MISSING_ISSUE_LIMIT = None

SKIP_KEYWORDS = ()


@dataclass
class SeriesReadRecord:
    seed_issue: object
    series_url: str
    series: object = None
    error: str = ""


class Command(BaseCommand):
    help = (
        "Sync current Marvel release calendar issues from Marvel.com. "
        "Series-first flow: release calendar issue -> Back to Series -> full series issue map -> needed issue details. "
        "No AI calls. No Comic Vine calls."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help="Maximum kept calendar issues to use as series seeds. Default: unlimited.",
        )
        parser.add_argument(
            "--calendar-timeout",
            type=int,
            default=DEFAULT_CALENDAR_TIMEOUT_MS,
            help=(
                "Maximum Playwright wait time in milliseconds for the release calendar page. "
                f"Default: {DEFAULT_CALENDAR_TIMEOUT_MS}."
            ),
        )
        parser.add_argument(
            "--detail-timeout",
            type=int,
            default=DEFAULT_DETAIL_TIMEOUT_MS,
            help=(
                "Maximum Playwright wait time in milliseconds per issue/series/detail page. "
                f"Default: {DEFAULT_DETAIL_TIMEOUT_MS}."
            ),
        )
        parser.add_argument(
            "--detail-limit",
            type=int,
            default=None,
            help="Maximum planned issue detail pages to read. Default: unlimited.",
        )
        parser.add_argument(
            "--missing-issue-limit",
            type=int,
            default=DEFAULT_MISSING_ISSUE_LIMIT,
            help=(
                "Compatibility flag. Series-first sync does not walk previous links; "
                "the series page supplies the full issue map. Default: unlimited."
            ),
        )
        parser.add_argument(
            "--skip-missing-issues",
            action="store_true",
            help=(
                "Only read detail pages for calendar seed issues and existing incomplete/local-ID repair issues. "
                "Default reads missing local issues from the full series page."
            ),
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--skip-details",
            action="store_true",
            help="Read calendar and series pages only. Do not open issue detail pages.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not create or update catalog data.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print rendered calendar and series/debug data.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each series and issue-level action.",
        )

    def handle(self, *args, **options):
        ensure_playwright()

        limit = options["limit"]
        calendar_timeout = options["calendar_timeout"]
        detail_timeout = options["detail_timeout"]
        detail_limit = options["detail_limit"]
        missing_issue_limit = options["missing_issue_limit"]

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1 when provided.")

        if calendar_timeout < 1000:
            raise CommandError("--calendar-timeout must be at least 1000 milliseconds.")

        if detail_timeout < 1000:
            raise CommandError("--detail-timeout must be at least 1000 milliseconds.")

        if detail_limit is not None and detail_limit < 1:
            raise CommandError("--detail-limit must be at least 1 when provided.")

        if missing_issue_limit is not None and missing_issue_limit < 0:
            raise CommandError("--missing-issue-limit cannot be negative.")

        calendar_start_date = current_marvel_date()
        calendar_end_date = calendar_start_date + timedelta(days=6)
        calendar_url = build_release_calendar_url(
            start_date=calendar_start_date,
            end_date=calendar_end_date,
        )

        dry_run = options["dry_run"]
        raw = options["raw"]
        verbose = options["verbose"]
        skip_details = options["skip_details"]
        skip_missing_issues = options["skip_missing_issues"] or skip_details
        headed = options["headed"]

        self.write_header(
            dry_run=dry_run,
            limit=limit,
            detail_limit=detail_limit,
            skip_details=skip_details,
            skip_missing_issues=skip_missing_issues,
            missing_issue_limit=missing_issue_limit,
            calendar_start_date=calendar_start_date,
            calendar_end_date=calendar_end_date,
            calendar_url=calendar_url,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
        )

        totals = new_totals()

        read_result = read_calendar_and_series_pages(
            calendar_url=calendar_url,
            limit=limit,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
        )

        rendered_calendar = read_result["rendered_calendar"]
        calendar_issues = read_result["calendar_issues"]
        kept_calendar_issues = read_result["kept_calendar_issues"]
        keyword_skipped_issues = read_result["keyword_skipped_issues"]
        series_records = read_result["series_records"]

        totals["calendar_browser_reads"] = 1
        totals["calendar_found"] = len(calendar_issues)
        totals["calendar_incomplete_skipped"] = read_result["incomplete_count"]
        totals["keyword_skipped"] = len(keyword_skipped_issues)
        totals["limit_skipped"] = read_result["limit_skipped"]
        totals["calendar_processed"] = len(kept_calendar_issues)
        totals["series_page_reads"] = read_result["series_page_reads"]
        totals["series_found"] = len(
            [
                record
                for record in series_records
                if record.series is not None and not record.series.errors
            ]
        )
        totals["series_read_failures"] = len(
            [
                record
                for record in series_records
                if record.error or (record.series is not None and record.series.errors)
            ]
        )
        totals["duplicate_series_seeds"] = read_result["duplicate_series_seeds"]
        totals["raw_series_issue_links"] = sum(
            record.series.raw_issue_link_count
            for record in series_records
            if record.series is not None
        )
        totals["unique_series_issue_links"] = sum(
            len(record.series.issues)
            for record in series_records
            if record.series is not None
        )
        totals["load_more_clicks"] = sum(
            record.series.load_more_clicks
            for record in series_records
            if record.series is not None
        )

        if raw:
            self.print_raw_calendar(rendered_calendar)

        if verbose and calendar_issues:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Calendar issues parsed"))

            for issue in calendar_issues:
                self.stdout.write(format_calendar_issue(issue))

        if verbose and keyword_skipped_issues:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Skipped by keyword"))

            for issue in keyword_skipped_issues:
                self.stdout.write(format_calendar_issue(issue))

        series_plans = []
        seed_issue_identities = {
            issue_number_identity(issue)
            for issue in kept_calendar_issues
        }

        close_old_connections()

        for record in series_records:
            if record.error:
                continue

            if record.series is None:
                continue

            if record.series.errors:
                continue

            series_plan = build_series_sync_plan(record.series)

            if skip_missing_issues:
                series_plan.issue_detail_plans = [
                    issue_plan
                    for issue_plan in series_plan.issue_detail_plans
                    if (
                        issue_plan.reason != "missing local issue"
                        or issue_number_identity(issue_plan.series_issue) in seed_issue_identities
                    )
                ]

            series_plans.append(series_plan)

        detail_targets = []

        if not skip_details:
            for series_plan in series_plans:
                detail_targets.extend(series_plan.issue_detail_plans)

        totals["planned_issue_detail_reads"] = len(detail_targets)

        if detail_limit is not None and len(detail_targets) > detail_limit:
            totals["detail_limit_skipped"] = len(detail_targets) - detail_limit
            detail_targets = detail_targets[:detail_limit]

        detail_map = {}

        if detail_targets:
            detail_map = read_planned_issue_details(
                detail_targets=detail_targets,
                headed=headed,
                timeout_ms=detail_timeout,
            )

        totals["detail_browser_reads"] = len(detail_map)

        for detail in detail_map.values():
            if get_detail_value(detail, "error"):
                totals["detail_read_failures"] += 1

            missing_fields = get_detail_missing_fields(detail)

            if missing_fields:
                totals["incomplete_details"] += 1
            else:
                totals["complete_details"] += 1

            if "description" in missing_fields:
                totals["missing_description"] += 1

            if "writer" in missing_fields:
                totals["missing_writer"] += 1

        for series_plan in series_plans:
            close_old_connections()

            series = series_plan.series
            run, run_result = upsert_run_from_series(
                series=series,
                dry_run=dry_run,
            )
            merge_write_result(totals, run_result)

            if verbose:
                self.print_series_result(
                    series=series,
                    series_plan=series_plan,
                    run_result=run_result,
                    dry_run=dry_run,
                )

            for issue_plan in series_plan.issue_detail_plans:
                detail = detail_map.get(series_issue_key(issue_plan.series_issue))

                if skip_details:
                    continue

                if detail is None:
                    continue

                if should_skip_issue_write_for_failed_missing_detail(
                    issue_plan=issue_plan,
                    detail=detail,
                ):
                    totals["issue_writes_skipped_no_detail"] += 1

                    if verbose:
                        self.print_issue_skipped(
                            issue_plan=issue_plan,
                            detail=detail,
                        )

                    continue

                _, issue_result = upsert_issue_from_series_issue(
                    run=run,
                    series_issue=issue_plan.series_issue,
                    detail=detail,
                    dry_run=dry_run,
                )
                merge_write_result(totals, issue_result)

                if verbose:
                    self.print_issue_result(
                        issue_plan=issue_plan,
                        detail=detail,
                        issue_result=issue_result,
                        dry_run=dry_run,
                    )

        self.print_summary(totals=totals, dry_run=dry_run)

    def write_header(
        self,
        *,
        dry_run,
        limit,
        detail_limit,
        skip_details,
        skip_missing_issues,
        missing_issue_limit,
        calendar_start_date,
        calendar_end_date,
        calendar_url,
        headed,
        calendar_timeout,
        detail_timeout,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar sync"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write(f"Source: {calendar_url}")
        self.stdout.write(
            "Date range: "
            f"{calendar_start_date.isoformat()} to {calendar_end_date.isoformat()}"
        )
        self.stdout.write(f"Calendar timezone: {MARVEL_CALENDAR_TIME_ZONE}")
        self.stdout.write("Reader: Playwright Chromium")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Calendar timeout: {calendar_timeout} ms")
        self.stdout.write(f"Detail/series timeout: {detail_timeout} ms")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write("Navigation: release calendar issue -> Back to Series -> full series issue map")
        self.stdout.write(
            "Calendar seed limit: "
            + (str(limit) if limit is not None else "unlimited")
        )
        self.stdout.write(
            "Issue detail read limit: "
            + (str(detail_limit) if detail_limit is not None else "unlimited")
        )
        self.stdout.write(f"Detail lookup: {'off' if skip_details else 'on'}")
        self.stdout.write(
            f"Full-series missing issue fill: {'off' if skip_missing_issues else 'on'}"
        )
        self.stdout.write(
            "Compatibility missing issue limit: "
            + (str(missing_issue_limit) if missing_issue_limit is not None else "unlimited")
        )
        self.stdout.write("Skip keywords: " + (", ".join(SKIP_KEYWORDS) if SKIP_KEYWORDS else "none"))
        self.stdout.write("Creates collections: no")
        self.stdout.write("Uses Comic Vine: no")
        self.stdout.write("")

    def print_raw_calendar(self, rendered_calendar):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Rendered Marvel calendar page"))
        self.stdout.write(f"Page title: {rendered_calendar['title']}")
        self.stdout.write(f"HTTP status: {rendered_calendar['status']}")
        self.stdout.write(f"Text length: {len(rendered_calendar['text'])}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Rendered text preview"))
        self.stdout.write(rendered_calendar["text"][:5000])

        if rendered_calendar["links"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Rendered issue-like links"))

            for link in rendered_calendar["links"][:50]:
                self.stdout.write(f"- {link['text']} -> {link['href']}")

    def print_series_result(self, *, series, series_plan, run_result, dry_run):
        action_prefix = "Would" if dry_run else "Did"
        reason_counts = Counter(
            issue_plan.reason
            for issue_plan in series_plan.issue_detail_plans
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{series.title} ({series.start_year})"))
        self.stdout.write(f"  Series URL: {series.url}")
        self.stdout.write(f"  Marvel series ID: {series.marvel_series_id or 'none'}")
        self.stdout.write(f"  Series status: {series.status}")
        self.stdout.write(f"  Load More clicks: {series.load_more_clicks}")
        self.stdout.write(f"  Raw issue links: {series.raw_issue_link_count}")
        self.stdout.write(f"  Unique issue links: {len(series.issues)}")
        self.stdout.write(f"  Planned detail reads: {len(series_plan.issue_detail_plans)}")

        if reason_counts:
            self.stdout.write(
                "  Detail reasons: "
                + ", ".join(
                    f"{reason}: {count}"
                    for reason, count in sorted(reason_counts.items())
                )
            )

        if run_result.run_created:
            self.stdout.write(f"  {action_prefix} create run")

        if run_result.run_updated:
            self.stdout.write(f"  {action_prefix} update run")

    def print_issue_result(self, *, issue_plan, detail, issue_result, dry_run):
        action_prefix = "Would" if dry_run else "Did"
        missing_fields = get_detail_missing_fields(detail)

        self.stdout.write("")
        self.stdout.write(f"  {format_series_issue(issue_plan.series_issue)}")
        self.stdout.write(f"    Reason: {issue_plan.reason}")
        self.stdout.write("    Detail lookup: checked")
        self.stdout.write(
            "    Detail complete: "
            + ("yes" if not missing_fields else "no")
        )

        if missing_fields:
            self.stdout.write("    Missing: " + ", ".join(missing_fields))

        if get_detail_value(detail, "error"):
            self.stdout.write("    Detail error: " + get_detail_value(detail, "error"))

        if issue_result.issue_created:
            self.stdout.write(f"    {action_prefix} create issue")

        if issue_result.issue_updated:
            self.stdout.write(f"    {action_prefix} update issue")

        if issue_result.credits_added:
            self.stdout.write(f"    Credits added: {issue_result.credits_added}")

    def print_issue_skipped(self, *, issue_plan, detail):
        self.stdout.write("")
        self.stdout.write(f"  {format_series_issue(issue_plan.series_issue)}")
        self.stdout.write(f"    Reason: {issue_plan.reason}")
        self.stdout.write("    Skipped write: missing local issue and detail read failed/incomplete enough to avoid skeleton issue")
        self.stdout.write(f"    Detail error: {get_detail_value(detail, 'error') or 'none'}")

    def print_summary(self, *, totals, dry_run):
        created_label = "Would create" if dry_run else "Created"
        updated_label = "Would update" if dry_run else "Updated"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar sync complete."))
        self.stdout.write(f"Calendar browser reads: {totals['calendar_browser_reads']}")
        self.stdout.write(f"Series page reads: {totals['series_page_reads']}")
        self.stdout.write(f"Issue detail browser reads: {totals['detail_browser_reads']}")
        self.stdout.write(f"Issue detail read failures: {totals['detail_read_failures']}")
        self.stdout.write("AI calls: 0")
        self.stdout.write(f"Calendar issues found: {totals['calendar_found']}")
        self.stdout.write(
            f"Skipped incomplete calendar rows: {totals['calendar_incomplete_skipped']}"
        )
        self.stdout.write(f"Skipped by keyword: {totals['keyword_skipped']}")
        self.stdout.write(f"Skipped by calendar seed limit: {totals['limit_skipped']}")
        self.stdout.write(f"Calendar issues used as seeds: {totals['calendar_processed']}")
        self.stdout.write(f"Duplicate series seeds skipped: {totals['duplicate_series_seeds']}")
        self.stdout.write(f"Series found: {totals['series_found']}")
        self.stdout.write(f"Series read failures: {totals['series_read_failures']}")
        self.stdout.write(f"Load More clicks: {totals['load_more_clicks']}")
        self.stdout.write(f"Raw series issue links: {totals['raw_series_issue_links']}")
        self.stdout.write(f"Unique series issue links: {totals['unique_series_issue_links']}")
        self.stdout.write(f"Planned issue detail reads: {totals['planned_issue_detail_reads']}")
        self.stdout.write(f"Skipped by detail limit: {totals['detail_limit_skipped']}")
        self.stdout.write(f"Issues with complete details: {totals['complete_details']}")
        self.stdout.write(f"Issues with incomplete details: {totals['incomplete_details']}")
        self.stdout.write(f"Issues missing description: {totals['missing_description']}")
        self.stdout.write(f"Issues missing Writer: {totals['missing_writer']}")
        self.stdout.write(f"Issue writes skipped because detail failed: {totals['issue_writes_skipped_no_detail']}")
        self.stdout.write(f"{created_label} runs: {totals['runs_created']}")
        self.stdout.write(f"{updated_label} runs: {totals['runs_updated']}")
        self.stdout.write(f"{created_label} issues: {totals['issues_created']}")
        self.stdout.write(f"{updated_label} issues: {totals['issues_updated']}")
        self.stdout.write(f"Credits added: {totals['credits_added']}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog data was created or updated.")


def read_calendar_and_series_pages(
    *,
    calendar_url,
    limit,
    headed,
    calendar_timeout,
    detail_timeout,
):
    with marvel_browser_context(headed=headed) as context:
        rendered_calendar = read_release_calendar_page(
            context=context,
            calendar_url=calendar_url,
            timeout_ms=calendar_timeout,
        )

        calendar_issues, incomplete_count = extract_release_calendar_issues_dataclasses(
            rendered_calendar=rendered_calendar,
        )
        calendar_issues = sorted(calendar_issues, key=calendar_issue_sort_key)

        kept_calendar_issues, keyword_skipped_issues = filter_skipped_calendar_issues(
            calendar_issues
        )

        limit_skipped = 0

        if limit is not None and len(kept_calendar_issues) > limit:
            limit_skipped = len(kept_calendar_issues) - limit
            kept_calendar_issues = kept_calendar_issues[:limit]

        series_records = []
        seen_series_keys = set()
        duplicate_series_seeds = 0
        series_page_reads = 0

        for calendar_issue in kept_calendar_issues:
            if not clean_text(calendar_issue.detail_url):
                series_records.append(
                    SeriesReadRecord(
                        seed_issue=calendar_issue,
                        series_url="",
                        error="calendar issue is missing detail URL",
                    )
                )
                continue

            series_url = read_issue_page_series_url(
                context=context,
                issue_url=calendar_issue.detail_url,
                timeout_ms=detail_timeout,
            )

            if not series_url:
                series_records.append(
                    SeriesReadRecord(
                        seed_issue=calendar_issue,
                        series_url="",
                        error="issue page did not expose Back to Series URL",
                    )
                )
                continue

            series_key = normalize_series_url_key(series_url)

            if series_key in seen_series_keys:
                duplicate_series_seeds += 1
                continue

            seen_series_keys.add(series_key)

            series = read_series_page(
                context=context,
                series_url=series_url,
                timeout_ms=detail_timeout,
            )
            series_page_reads += 1

            series_records.append(
                SeriesReadRecord(
                    seed_issue=calendar_issue,
                    series_url=series_url,
                    series=series,
                    error="",
                )
            )

        return {
            "rendered_calendar": rendered_calendar,
            "calendar_issues": calendar_issues,
            "kept_calendar_issues": kept_calendar_issues,
            "keyword_skipped_issues": keyword_skipped_issues,
            "incomplete_count": incomplete_count,
            "limit_skipped": limit_skipped,
            "series_records": series_records,
            "duplicate_series_seeds": duplicate_series_seeds,
            "series_page_reads": series_page_reads,
        }


def read_planned_issue_details(*, detail_targets, headed, timeout_ms):
    detail_map = {}

    with marvel_browser_context(headed=headed) as context:
        for issue_plan in detail_targets:
            detail = read_issue_detail_page(
                context=context,
                calendar_issue=issue_plan.series_issue,
                timeout_ms=timeout_ms,
            )
            detail_map[series_issue_key(issue_plan.series_issue)] = detail

    return detail_map


def should_skip_issue_write_for_failed_missing_detail(*, issue_plan, detail):
    if issue_plan.existing_issue is not None:
        return False

    if get_detail_value(detail, "error"):
        return True

    if not get_detail_value(detail, "published_date"):
        return True

    return False


def merge_write_result(totals, result):
    if result is None:
        return

    totals["runs_created"] += result.run_created
    totals["runs_updated"] += result.run_updated
    totals["issues_created"] += result.issue_created
    totals["issues_updated"] += result.issue_updated
    totals["credits_added"] += result.credits_added


def new_totals():
    return {
        "calendar_browser_reads": 0,
        "series_page_reads": 0,
        "detail_browser_reads": 0,
        "detail_read_failures": 0,
        "calendar_found": 0,
        "calendar_incomplete_skipped": 0,
        "keyword_skipped": 0,
        "limit_skipped": 0,
        "calendar_processed": 0,
        "duplicate_series_seeds": 0,
        "series_found": 0,
        "series_read_failures": 0,
        "load_more_clicks": 0,
        "raw_series_issue_links": 0,
        "unique_series_issue_links": 0,
        "planned_issue_detail_reads": 0,
        "detail_limit_skipped": 0,
        "complete_details": 0,
        "incomplete_details": 0,
        "missing_description": 0,
        "missing_writer": 0,
        "issue_writes_skipped_no_detail": 0,
        "runs_created": 0,
        "runs_updated": 0,
        "issues_created": 0,
        "issues_updated": 0,
        "credits_added": 0,
    }


def normalize_series_url_key(series_url):
    series_url = clean_text(series_url)

    if not series_url:
        return ""

    pieces = series_url.split("/comics/series/", 1)

    if len(pieces) == 2:
        return pieces[1].split("?", 1)[0].split("#", 1)[0].strip("/").casefold()

    return series_url.casefold()


def calendar_issue_sort_key(issue):
    return (
        issue.published_date,
        normalize_title(issue.run_title),
        issue_number_sort_key(issue.issue_number),
    )


def series_issue_key(series_issue):
    marvel_issue_id = clean_text(get_object_value(series_issue, "marvel_issue_id"))

    if marvel_issue_id:
        return ("id", marvel_issue_id)

    detail_url = clean_text(get_object_value(series_issue, "detail_url"))

    if detail_url:
        return ("url", detail_url)

    return (
        "number",
        normalize_title(get_object_value(series_issue, "run_title")),
        clean_text(get_object_value(series_issue, "start_year")),
        normalize_issue_number(get_object_value(series_issue, "issue_number")),
    )


def issue_number_identity(issue):
    return (
        normalize_title(get_object_value(issue, "run_title")),
        clean_text(get_object_value(issue, "start_year")),
        normalize_issue_number(get_object_value(issue, "issue_number")),
    )


def get_object_value(value, name):
    if isinstance(value, dict):
        return value.get(name)

    return getattr(value, name, None)


def format_calendar_issue(issue):
    published_date = get_object_value(issue, "published_date")
    date_text = published_date.isoformat() if published_date else "no date"

    return (
        f"{get_object_value(issue, 'run_title')} "
        f"({get_object_value(issue, 'start_year')}) "
        f"#{get_object_value(issue, 'issue_number')} "
        f"[{date_text}]"
    )


def format_series_issue(series_issue):
    return (
        f"{get_object_value(series_issue, 'run_title')} "
        f"({get_object_value(series_issue, 'start_year')}) "
        f"#{get_object_value(series_issue, 'issue_number')} "
        f"[id={get_object_value(series_issue, 'marvel_issue_id') or 'none'}]"
    )


def format_calendar_issue_without_date(issue):
    return (
        f"{get_object_value(issue, 'run_title')} "
        f"({get_object_value(issue, 'start_year')}) "
        f"#{get_object_value(issue, 'issue_number')}"
    )


def format_credits(credits):
    normalized_credits = normalize_credit_list(credits)

    return "; ".join(
        f"{credit['role']}: {credit['name']}"
        for credit in normalized_credits
    )


def filter_skipped_calendar_issues(calendar_issues):
    kept = []
    skipped = []

    for issue in calendar_issues:
        if should_skip_calendar_issue(issue):
            skipped.append(issue)
        else:
            kept.append(issue)

    return kept, skipped


def should_skip_calendar_issue(calendar_issue):
    return contains_skip_keyword(
        get_object_value(calendar_issue, "run_title"),
        get_object_value(calendar_issue, "start_year"),
        get_object_value(calendar_issue, "issue_number"),
    )


def contains_skip_keyword(*values):
    text = " ".join(clean_text(value) for value in values).casefold()

    return any(keyword.casefold() in text for keyword in SKIP_KEYWORDS)


def get_detail_missing_fields(detail):
    return get_issue_missing_fields(detail)


def get_preview_missing_fields(*, issue, detail):
    missing_fields = []
    detail_missing_fields = get_issue_missing_fields(detail)

    has_description = "description" not in detail_missing_fields
    has_writer = "writer" not in detail_missing_fields

    if issue is not None and clean_text(issue.description):
        has_description = True

    if issue is not None:
        try:
            has_writer = has_writer or any(
                credit.role.name.casefold() == "writer"
                for credit in issue.credits.select_related("role").all()
            )
        except Exception:
            pass

    if not has_description:
        missing_fields.append("description")

    if not has_writer:
        missing_fields.append("writer")

    return missing_fields


def empty_detail():
    return issue_detail_to_dict(empty_issue_detail())


def issue_detail_to_dict(detail):
    return {
        "checked": get_detail_value(detail, "checked"),
        "read_attempted": get_detail_value(detail, "read_attempted"),
        "error": get_detail_value(detail, "error") or "",
        "published_date": get_detail_value(detail, "published_date"),
        "description": get_detail_value(detail, "description") or "",
        "credits": get_detail_value(detail, "credits") or [],
        "issue_links": get_detail_value(detail, "issue_links") or [],
        "text_preview": get_detail_value(detail, "text_preview") or "",
    }


def read_issue_detail_page(*, context, calendar_issue, timeout_ms):
    detail = read_shared_issue_detail_page(
        context=context,
        issue=calendar_issue,
        timeout_ms=timeout_ms,
    )
    return issue_detail_to_dict(detail)


def read_calendar_with_playwright(*, calendar_url, headed, timeout_ms):
    with marvel_browser_context(headed=headed) as context:
        return read_release_calendar_page(
            context=context,
            calendar_url=calendar_url,
            timeout_ms=timeout_ms,
        )


def extract_calendar_issues(*, rendered_calendar):
    issues, incomplete_count = extract_release_calendar_issues_dataclasses(
        rendered_calendar=rendered_calendar,
    )

    return [calendar_issue_to_dict(issue) for issue in issues], incomplete_count


def calendar_issue_to_dict(issue):
    return {
        "run_title": issue.run_title,
        "start_year": issue.start_year,
        "issue_number": issue.issue_number,
        "published_date": issue.published_date,
        "detail_url": issue.detail_url,
        "marvel_issue_id": issue.official_source_key,
        "issue_slug": issue.issue_slug,
    }


def build_calendar_url(*, start_date, end_date):
    return build_release_calendar_url(
        start_date=start_date,
        end_date=end_date,
    )


def parse_issue_link(link):
    text = clean_text(link.get("text"))
    href = clean_text(link.get("href"))

    if not href:
        return None

    parsed_url = parse_marvel_issue_url(href)

    if parsed_url:
        result = {
            "run_title": parsed_url.run_title,
            "start_year": parsed_url.start_year,
            "issue_number": canonical_issue_number(parsed_url.issue_number),
            "published_date": None,
            "detail_url": href,
            "marvel_issue_id": parsed_url.marvel_id,
            "issue_slug": parsed_url.slug,
        }

        if text:
            text_issue = issue_from_detail_url(href)
            result["detail_url"] = href
            result["run_title"] = text_issue.get("run_title") or result["run_title"]

        return result

    return None


def apply_calendar_issue(*, calendar_issue, detail, dry_run):
    from catalog.marvel.series import MarvelSeries, MarvelSeriesIssue

    parsed_url = parse_marvel_issue_url(clean_text(calendar_issue.get("detail_url")))

    series_issue = MarvelSeriesIssue(
        run_title=calendar_issue["run_title"],
        start_year=calendar_issue["start_year"],
        issue_number=calendar_issue["issue_number"],
        detail_url=calendar_issue.get("detail_url") or "",
        marvel_issue_id=(
            calendar_issue.get("marvel_issue_id")
            or (parsed_url.marvel_id if parsed_url else "")
        ),
        issue_slug=(
            calendar_issue.get("issue_slug")
            or (parsed_url.slug if parsed_url else "")
        ),
    )

    series = MarvelSeries(
        title=calendar_issue["run_title"],
        start_year=calendar_issue["start_year"],
        status="ongoing",
        issues=[series_issue],
    )

    run, run_result = upsert_run_from_series(
        series=series,
        dry_run=dry_run,
    )
    _, issue_result = upsert_issue_from_series_issue(
        run=run,
        series_issue=series_issue,
        detail=detail,
        dry_run=dry_run,
    )

    result = WriteResult(
        run_created=run_result.run_created + issue_result.run_created,
        run_updated=run_result.run_updated + issue_result.run_updated,
        issue_created=issue_result.issue_created,
        issue_updated=issue_result.issue_updated,
        credits_added=issue_result.credits_added,
    )

    return {
        "run_created": result.run_created,
        "run_updated": result.run_updated,
        "issue_created": result.issue_created,
        "issue_updated": result.issue_updated,
        "credits_added": result.credits_added,
    }


def build_missing_issue_plan(calendar_issues):
    plan = {}

    for calendar_issue in calendar_issues:
        current_issue_number = pure_integer_issue_number(
            get_object_value(calendar_issue, "issue_number")
        )

        if current_issue_number is None or current_issue_number <= 1:
            continue

        existing_run = find_existing_run(
            title=get_object_value(calendar_issue, "run_title"),
            start_year=get_object_value(calendar_issue, "start_year"),
        )
        existing_issue_numbers = get_existing_integer_issue_numbers(existing_run)

        missing_issue_numbers = {
            issue_number
            for issue_number in range(1, current_issue_number)
            if issue_number not in existing_issue_numbers
        }

        if not missing_issue_numbers:
            continue

        key = issue_series_key(calendar_issue)
        plan.setdefault(key, set()).update(missing_issue_numbers)

    return plan


def get_existing_integer_issue_numbers(run):
    if run is None:
        return set()

    existing_issue_numbers = set()

    for issue in run.issues.all():
        issue_number = pure_integer_issue_number(issue.issue_number)

        if issue_number is not None:
            existing_issue_numbers.add(issue_number)

    return existing_issue_numbers


def calendar_issue_key(issue):
    return (
        normalize_title(get_object_value(issue, "run_title")),
        clean_text(get_object_value(issue, "start_year")),
        normalize_issue_number(get_object_value(issue, "issue_number")),
        get_object_value(issue, "published_date"),
    )


def issue_series_key(issue):
    return (
        normalize_title(get_object_value(issue, "run_title")),
        clean_text(get_object_value(issue, "start_year")),
    )


def read_current_and_missing_details_with_playwright(
    *,
    calendar_issues,
    missing_issue_plan,
    skip_missing_issues,
    missing_issue_limit,
    headed,
    timeout_ms,
):
    result = {
        "current_details": {},
        "missing_records": [],
        "missing_issue_limit_reached": False,
    }

    with marvel_browser_context(headed=headed) as context:
        for calendar_issue in calendar_issues:
            detail = read_issue_detail_page(
                context=context,
                calendar_issue=calendar_issue,
                timeout_ms=timeout_ms,
            )
            result["current_details"][calendar_issue_key(calendar_issue)] = detail

    return result