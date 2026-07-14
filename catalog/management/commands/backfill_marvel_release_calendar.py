import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections

from catalog.marvel.browser import (
    DEFAULT_CALENDAR_TIMEOUT_MS,
    DEFAULT_DETAIL_TIMEOUT_MS,
    MARVEL_CALENDAR_TIME_ZONE,
    ensure_playwright,
    marvel_browser_context,
)
from catalog.marvel.calendar import (
    build_release_calendar_url,
    extract_release_calendar_issues,
    read_release_calendar_page,
)
from catalog.marvel.credits import normalize_credit_list
from catalog.marvel.issues import (
    get_detail_value,
    get_issue_missing_fields,
    read_issue_detail_page,
)
from catalog.marvel.series import (
    read_issue_page_series_url,
    read_series_page,
)
from catalog.marvel.sync_planner import build_series_sync_plan
from catalog.marvel.text import (
    clean_text,
    issue_number_sort_key,
    normalize_issue_number,
    normalize_title,
)
from catalog.marvel.writer import (
    upsert_issue_from_series_issue,
    upsert_run_from_series,
)


WEDNESDAY_WEEKDAY = 2
WINDOW_DAYS = 7
YEAR_FLAG_RE = re.compile(r"^--(?P<year>\d{4})$")

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
        "Backfill old Marvel release calendar issues by walking weekly Wednesday windows. "
        "Each backfill window uses dateStart=Wednesday and dateEnd=Wednesday+6 days. "
        "Series-first flow: calendar issue -> Back to Series -> full series issue map -> needed issue details. "
        "No AI calls. No Comic Vine calls."
    )

    def add_arguments(self, parser):
        add_detected_year_flags(parser)

        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help=(
                "Backfill one calendar year. Example: --year 2025. "
                "Shorthand year flags like --2025 are also supported."
            ),
        )
        parser.add_argument(
            "--start-date",
            help="Oldest date in the backfill range, YYYY-MM-DD. Prompted if omitted and no year is provided.",
        )
        parser.add_argument(
            "--end-date",
            help="Newest date in the backfill range, YYYY-MM-DD. Prompted if omitted and no year is provided.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help="Maximum kept calendar issues to use as series seeds per weekly window. Default: unlimited.",
        )
        parser.add_argument(
            "--calendar-timeout",
            type=int,
            default=DEFAULT_CALENDAR_TIMEOUT_MS,
            help=(
                "Maximum Playwright wait time in milliseconds for each calendar page. "
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
            help="Maximum planned issue detail pages to read per weekly window. Default: unlimited.",
        )
        parser.add_argument(
            "--missing-issue-limit",
            type=int,
            default=DEFAULT_MISSING_ISSUE_LIMIT,
            help=(
                "Compatibility flag. Series-first backfill does not walk previous links; "
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
            help="Print rendered page previews and parsed detail data.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each series and issue-level action.",
        )

    def handle(self, *args, **options):
        ensure_playwright()
        close_old_connections()

        requested_year = resolve_requested_year(options)

        if requested_year is not None:
            start_date, end_date = year_date_range(
                year=requested_year,
                start_date_value=options.get("start_date"),
                end_date_value=options.get("end_date"),
            )
        else:
            start_date = get_range_date(
                value=options.get("start_date"),
                prompt_label="Oldest date in range",
            )
            end_date = get_range_date(
                value=options.get("end_date"),
                prompt_label="Newest date in range",
            )

        if start_date > end_date:
            raise CommandError("--start-date must be earlier than or equal to --end-date.")

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

        week_start_dates = get_wednesdays_newest_first(
            start_date=start_date,
            end_date=end_date,
        )

        if not week_start_dates:
            self.stdout.write(
                self.style.WARNING(
                    "No Wednesdays were found inside the selected date range."
                )
            )
            return

        dry_run = options["dry_run"]
        raw = options["raw"]
        verbose = options["verbose"]
        skip_details = options["skip_details"]
        skip_missing_issues = options["skip_missing_issues"] or skip_details
        headed = options["headed"]

        totals = new_totals()
        globally_seen_series_keys = set()

        self.write_header(
            dry_run=dry_run,
            requested_year=requested_year,
            start_date=start_date,
            end_date=end_date,
            week_start_dates=week_start_dates,
            limit=limit,
            detail_limit=detail_limit,
            skip_details=skip_details,
            skip_missing_issues=skip_missing_issues,
            missing_issue_limit=missing_issue_limit,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
        )

        for week_start_date in week_start_dates:
            close_old_connections()

            week_end_date = week_start_date + timedelta(days=WINDOW_DAYS - 1)

            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "Processing Marvel release calendar window: "
                    f"{week_start_date.isoformat()} to {week_end_date.isoformat()}"
                )
            )

            date_totals = self.process_release_window(
                calendar_start_date=week_start_date,
                calendar_end_date=week_end_date,
                limit=limit,
                detail_limit=detail_limit,
                calendar_timeout=calendar_timeout,
                detail_timeout=detail_timeout,
                dry_run=dry_run,
                raw=raw,
                verbose=verbose,
                skip_details=skip_details,
                skip_missing_issues=skip_missing_issues,
                headed=headed,
                globally_seen_series_keys=globally_seen_series_keys,
            )
            merge_totals(totals, date_totals)

        close_old_connections()
        self.print_summary(totals=totals, dry_run=dry_run)

    def process_release_window(
        self,
        *,
        calendar_start_date,
        calendar_end_date,
        limit,
        detail_limit,
        calendar_timeout,
        detail_timeout,
        dry_run,
        raw,
        verbose,
        skip_details,
        skip_missing_issues,
        headed,
        globally_seen_series_keys,
    ):
        totals = new_totals()
        calendar_url = build_release_calendar_url(
            start_date=calendar_start_date,
            end_date=calendar_end_date,
        )

        read_result = read_calendar_and_series_pages_for_window(
            calendar_url=calendar_url,
            limit=limit,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
            globally_seen_series_keys=globally_seen_series_keys,
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
        totals["duplicate_series_seeds"] = read_result["duplicate_series_seeds"]
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
        totals["load_more_clicks"] = sum(
            record.series.load_more_clicks
            for record in series_records
            if record.series is not None
        )
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

        if not kept_calendar_issues:
            self.stdout.write("No kept calendar issues for this weekly window.")
            self.print_window_summary(totals)
            return totals

        seed_issue_identities = {
            issue_number_identity(issue)
            for issue in kept_calendar_issues
        }

        series_plans = []

        close_old_connections()

        for record in series_records:
            if record.error:
                if verbose:
                    self.print_series_read_error(record)
                continue

            if record.series is None:
                continue

            if record.series.errors:
                if verbose:
                    self.print_series_read_error(record)
                continue

            series_plan = db_call(
                build_series_sync_plan,
                record.series,
            )

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

        close_old_connections()

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

            if raw:
                self.print_raw_detail(detail)

        for series_plan in series_plans:
            close_old_connections()

            series = series_plan.series
            run, run_result = db_call(
                upsert_run_from_series,
                retry=False,
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
                if skip_details:
                    continue

                detail = detail_map.get(series_issue_key(issue_plan.series_issue))

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

                _, issue_result = db_call(
                    upsert_issue_from_series_issue,
                    retry=False,
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

        close_old_connections()
        self.print_window_summary(totals)
        return totals

    def write_header(
        self,
        *,
        dry_run,
        requested_year,
        start_date,
        end_date,
        week_start_dates,
        limit,
        detail_limit,
        skip_details,
        skip_missing_issues,
        missing_issue_limit,
        headed,
        calendar_timeout,
        detail_timeout,
    ):
        first_window_end = week_start_dates[0] + timedelta(days=WINDOW_DAYS - 1)
        last_window_end = week_start_dates[-1] + timedelta(days=WINDOW_DAYS - 1)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar backfill"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")

        if requested_year is not None:
            self.stdout.write(f"Requested year: {requested_year}")

        self.stdout.write(f"Requested range oldest date: {start_date.isoformat()}")
        self.stdout.write(f"Requested range newest date: {end_date.isoformat()}")
        self.stdout.write(f"Weekly windows to process: {len(week_start_dates)}")
        self.stdout.write(
            f"First processed window: {week_start_dates[0].isoformat()} to {first_window_end.isoformat()}"
        )
        self.stdout.write(
            f"Last processed window: {week_start_dates[-1].isoformat()} to {last_window_end.isoformat()}"
        )
        self.stdout.write(f"Window size: {WINDOW_DAYS} days")
        self.stdout.write(f"Calendar timezone: {MARVEL_CALENDAR_TIME_ZONE}")
        self.stdout.write("Reader: Playwright Chromium")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Calendar timeout: {calendar_timeout} ms")
        self.stdout.write(f"Detail/series timeout: {detail_timeout} ms")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write("Navigation: release calendar issue -> Back to Series -> full series issue map")
        self.stdout.write("Run status behavior: series page Present => ongoing")
        self.stdout.write(
            "Calendar seed limit per weekly window: "
            + (str(limit) if limit is not None else "unlimited")
        )
        self.stdout.write(
            "Issue detail read limit per weekly window: "
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

    def print_raw_detail(self, detail):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Parsed issue detail"))
        self.stdout.write(f"Read attempted: {get_detail_value(detail, 'read_attempted')}")
        self.stdout.write(f"Read error: {get_detail_value(detail, 'error') or 'none'}")
        self.stdout.write(
            "Published date from detail: "
            + (
                get_detail_value(detail, "published_date").isoformat()
                if get_detail_value(detail, "published_date")
                else "none"
            )
        )
        self.stdout.write(f"Description: {get_detail_value(detail, 'description') or '[blank]'}")
        self.stdout.write(f"Credits: {format_credits(get_detail_value(detail, 'credits')) or 'none'}")
        self.stdout.write(
            "Missing fields: "
            + (",".join(get_detail_missing_fields(detail)) or "none")
        )
        self.stdout.write("Text preview:")
        self.stdout.write(get_detail_value(detail, "text_preview") or "")

    def print_series_read_error(self, record):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Series read failed"))
        self.stdout.write(f"  Seed: {format_calendar_issue(record.seed_issue)}")
        self.stdout.write(f"  Series URL: {record.series_url or 'none'}")

        if record.error:
            self.stdout.write(f"  Error: {record.error}")

        if record.series is not None and record.series.errors:
            for error in record.series.errors:
                self.stdout.write(f"  Error: {error}")

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

    def print_window_summary(self, totals):
        self.stdout.write("")
        self.stdout.write("Weekly window summary:")
        self.stdout.write(f"  Calendar issues found: {totals['calendar_found']}")
        self.stdout.write(f"  Calendar issues used as seeds: {totals['calendar_processed']}")
        self.stdout.write(f"  Duplicate series seeds skipped: {totals['duplicate_series_seeds']}")
        self.stdout.write(f"  Series found: {totals['series_found']}")
        self.stdout.write(f"  Unique series issue links: {totals['unique_series_issue_links']}")
        self.stdout.write(f"  Planned issue detail reads: {totals['planned_issue_detail_reads']}")
        self.stdout.write(f"  Issue detail browser reads: {totals['detail_browser_reads']}")
        self.stdout.write(f"  Created issues: {totals['issues_created']}")
        self.stdout.write(f"  Updated issues: {totals['issues_updated']}")

    def print_summary(self, *, totals, dry_run):
        created_label = "Would create" if dry_run else "Created"
        updated_label = "Would update" if dry_run else "Updated"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar backfill complete."))
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


def read_calendar_and_series_pages_for_window(
    *,
    calendar_url,
    limit,
    headed,
    calendar_timeout,
    detail_timeout,
    globally_seen_series_keys,
):
    with marvel_browser_context(headed=headed) as context:
        rendered_calendar = read_release_calendar_page(
            context=context,
            calendar_url=calendar_url,
            timeout_ms=calendar_timeout,
        )

        calendar_issues, incomplete_count = extract_release_calendar_issues(
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

            if series_key in globally_seen_series_keys:
                duplicate_series_seeds += 1
                continue

            globally_seen_series_keys.add(series_key)

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
                issue=issue_plan.series_issue,
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


def db_call(function, *args, retry=True, **kwargs):
    close_old_connections()

    try:
        return function(*args, **kwargs)
    except OperationalError:
        if not retry:
            raise

        close_old_connections()
        return function(*args, **kwargs)
    finally:
        close_old_connections()


def add_detected_year_flags(parser):
    detected_years = []

    for value in sys.argv[2:]:
        match = YEAR_FLAG_RE.match(value)

        if not match:
            continue

        year = int(match.group("year"))

        if year in detected_years:
            continue

        detected_years.append(year)

    for year in detected_years:
        parser.add_argument(
            f"--{year}",
            action="append_const",
            const=year,
            dest="year_flags",
            help=f"Backfill all Marvel release calendar windows for {year}.",
        )


def resolve_requested_year(options):
    years = []

    if options.get("year") is not None:
        years.append(options["year"])

    years.extend(options.get("year_flags") or [])

    unique_years = sorted(set(years))

    if len(unique_years) > 1:
        raise CommandError("Use only one year value per backfill run.")

    if not unique_years:
        return None

    year = unique_years[0]
    validate_year(year)
    return year


def validate_year(year):
    if year < 1 or year > 9999:
        raise CommandError("Year must be between 1 and 9999.")


def year_date_range(*, year, start_date_value, end_date_value):
    if start_date_value or end_date_value:
        raise CommandError("Use either a year flag/--year or --start-date/--end-date, not both.")

    return date(year, 1, 1), date(year, 12, 31)


def get_range_date(*, value, prompt_label):
    if not value:
        value = input(f"{prompt_label} YYYY-MM-DD: ").strip()

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def get_wednesdays_newest_first(*, start_date, end_date):
    days_since_wednesday = (end_date.weekday() - WEDNESDAY_WEEKDAY) % 7
    current = end_date - timedelta(days=days_since_wednesday)

    wednesdays = []

    while current >= start_date:
        wednesdays.append(current)
        current -= timedelta(days=7)

    return wednesdays


def merge_totals(total, date_total):
    for key, value in date_total.items():
        total[key] += value


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