import re
import sys
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
from catalog.marvel.series import MarvelSeries, MarvelSeriesIssue
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
SKIP_KEYWORDS = ()


class Command(BaseCommand):
    help = (
        "Fast backfill old Marvel release calendar seed issues by walking weekly Wednesday windows. "
        "This command reads release calendar seed issue pages only and does not open Back to Series pages."
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
            help="Maximum kept calendar issue seed pages to read per weekly window. Default: unlimited.",
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
                "Maximum Playwright wait time in milliseconds per issue detail page. "
                f"Default: {DEFAULT_DETAIL_TIMEOUT_MS}."
            ),
        )
        parser.add_argument(
            "--detail-limit",
            type=int,
            default=None,
            help="Maximum seed issue detail pages to read per weekly window. Default: unlimited.",
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read Marvel pages and report what would change without writing catalog records.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print rendered page previews and parsed detail data.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each seed issue action.",
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
        detail_limit = options["detail_limit"]
        calendar_timeout = options["calendar_timeout"]
        detail_timeout = options["detail_timeout"]

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1 when provided.")

        if detail_limit is not None and detail_limit < 1:
            raise CommandError("--detail-limit must be at least 1 when provided.")

        if calendar_timeout < 1000:
            raise CommandError("--calendar-timeout must be at least 1000 milliseconds.")

        if detail_timeout < 1000:
            raise CommandError("--detail-timeout must be at least 1000 milliseconds.")

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
        headed = options["headed"]

        totals = new_totals()
        globally_seen_issue_keys = set()

        self.write_header(
            dry_run=dry_run,
            requested_year=requested_year,
            start_date=start_date,
            end_date=end_date,
            week_start_dates=week_start_dates,
            limit=limit,
            detail_limit=detail_limit,
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
                headed=headed,
                globally_seen_issue_keys=globally_seen_issue_keys,
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
        headed,
        globally_seen_issue_keys,
    ):
        totals = new_totals()
        calendar_url = build_release_calendar_url(
            start_date=calendar_start_date,
            end_date=calendar_end_date,
        )

        read_result = read_calendar_for_window(
            calendar_url=calendar_url,
            limit=limit,
            headed=headed,
            calendar_timeout=calendar_timeout,
        )

        rendered_calendar = read_result["rendered_calendar"]
        calendar_issues = read_result["calendar_issues"]
        kept_calendar_issues = read_result["kept_calendar_issues"]
        keyword_skipped_issues = read_result["keyword_skipped_issues"]

        totals["calendar_browser_reads"] = 1
        totals["calendar_found"] = len(calendar_issues)
        totals["calendar_incomplete_skipped"] = read_result["incomplete_count"]
        totals["keyword_skipped"] = len(keyword_skipped_issues)
        totals["limit_skipped"] = read_result["limit_skipped"]
        totals["calendar_processed"] = len(kept_calendar_issues)

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

        if detail_limit is not None and len(kept_calendar_issues) > detail_limit:
            totals["detail_limit_skipped"] = len(kept_calendar_issues) - detail_limit
            kept_calendar_issues = kept_calendar_issues[:detail_limit]

        totals["planned_issue_detail_reads"] = len(kept_calendar_issues)
        seed_count = len(kept_calendar_issues)

        for seed_index, calendar_issue in enumerate(kept_calendar_issues, start=1):
            issue_key = issue_identity(calendar_issue)

            if issue_key in globally_seen_issue_keys:
                totals["duplicate_issue_seeds"] += 1
                self.print_seed_skipped(
                    seed_index=seed_index,
                    seed_count=seed_count,
                    calendar_issue=calendar_issue,
                    reason="duplicate issue seed already processed in this run",
                )
                continue

            globally_seen_issue_keys.add(issue_key)

            if not clean_text(calendar_issue.detail_url):
                totals["missing_detail_url_skipped"] += 1
                self.print_seed_skipped(
                    seed_index=seed_index,
                    seed_count=seed_count,
                    calendar_issue=calendar_issue,
                    reason="calendar issue is missing detail URL",
                )
                continue

            series_issue = build_series_issue_from_calendar_issue(calendar_issue)
            detail = read_seed_issue_detail(
                series_issue=series_issue,
                headed=headed,
                timeout_ms=detail_timeout,
            )
            totals["detail_browser_reads"] += 1
            apply_calendar_date_fallback(detail=detail, calendar_issue=calendar_issue)
            self.add_detail_totals(totals=totals, detail=detail, raw=raw)

            if get_detail_value(detail, "error"):
                totals["issue_writes_skipped_no_detail"] += 1
                self.print_seed_skipped(
                    seed_index=seed_index,
                    seed_count=seed_count,
                    calendar_issue=calendar_issue,
                    reason=get_detail_value(detail, "error"),
                )
                continue

            if not get_detail_value(detail, "published_date"):
                totals["issue_writes_skipped_no_detail"] += 1
                self.print_seed_skipped(
                    seed_index=seed_index,
                    seed_count=seed_count,
                    calendar_issue=calendar_issue,
                    reason="issue detail did not expose a published date",
                )
                continue

            close_old_connections()
            series = build_minimal_series_from_calendar_issue(calendar_issue)
            run, run_result = db_call(
                upsert_run_from_series,
                retry=False,
                series=series,
                dry_run=dry_run,
            )
            merge_write_result(totals, run_result)

            _, issue_result = db_call(
                upsert_issue_from_series_issue,
                retry=False,
                run=run,
                series_issue=series_issue,
                detail=detail,
                dry_run=dry_run,
            )
            merge_write_result(totals, issue_result)
            close_old_connections()

            self.print_seed_result(
                seed_index=seed_index,
                seed_count=seed_count,
                calendar_issue=calendar_issue,
                detail=detail,
                run_result=run_result,
                issue_result=issue_result,
                dry_run=dry_run,
                verbose=verbose,
            )

        close_old_connections()
        self.print_window_summary(totals)
        return totals

    def add_detail_totals(self, *, totals, detail, raw):
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
        headed,
        calendar_timeout,
        detail_timeout,
    ):
        first_window_end = week_start_dates[0] + timedelta(days=WINDOW_DAYS - 1)
        last_window_end = week_start_dates[-1] + timedelta(days=WINDOW_DAYS - 1)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar fast backfill"))
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
        self.stdout.write(f"Issue detail timeout: {detail_timeout} ms")
        self.stdout.write("Navigation: release calendar issue detail pages only")
        self.stdout.write("Series expansion: off")
        self.stdout.write("Write cadence: per seed issue")
        self.stdout.write(
            "Calendar seed limit per weekly window: "
            + (str(limit) if limit is not None else "unlimited")
        )
        self.stdout.write(
            "Issue detail read limit per weekly window: "
            + (str(detail_limit) if detail_limit is not None else "unlimited")
        )

    def print_raw_calendar(self, rendered_calendar):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Rendered Marvel calendar page"))
        self.stdout.write(f"Page title: {rendered_calendar['title']}")
        self.stdout.write(f"HTTP status: {rendered_calendar['status']}")
        self.stdout.write(f"Text length: {len(rendered_calendar['text'])}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Rendered text preview"))
        self.stdout.write(rendered_calendar["text"][:5000])

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

    def print_seed_skipped(self, *, seed_index, seed_count, calendar_issue, reason):
        self.stdout.write(
            self.style.WARNING(
                f"[{seed_index}/{seed_count}] Skipped: {format_calendar_issue(calendar_issue)}"
            )
        )
        self.stdout.write(f"  Reason: {reason}")
        self.stdout.write(f"  Source URL: {calendar_issue.detail_url or 'none'}")

    def print_seed_result(
        self,
        *,
        seed_index,
        seed_count,
        calendar_issue,
        detail,
        run_result,
        issue_result,
        dry_run,
        verbose,
    ):
        created_label = "would create" if dry_run else "created"
        updated_label = "would update" if dry_run else "updated"
        missing_fields = get_detail_missing_fields(detail)

        self.stdout.write(
            self.style.SUCCESS(
                f"[{seed_index}/{seed_count}] {format_calendar_issue(calendar_issue)} complete"
            )
        )
        self.stdout.write(
            "  "
            f"runs {created_label} {run_result.run_created}, {updated_label} {run_result.run_updated}; "
            f"issues {created_label} {issue_result.issue_created}, {updated_label} {issue_result.issue_updated}; "
            f"credits added: {issue_result.credits_added}; "
            f"detail complete: {'yes' if not missing_fields else 'no'}"
        )

        if verbose and missing_fields:
            self.stdout.write("  Missing detail fields: " + ", ".join(missing_fields))

    def print_window_summary(self, totals):
        self.stdout.write("")
        self.stdout.write("Weekly window summary:")
        self.stdout.write(f"  Calendar issues found: {totals['calendar_found']}")
        self.stdout.write(f"  Calendar issues used as seeds: {totals['calendar_processed']}")
        self.stdout.write(f"  Duplicate issue seeds skipped: {totals['duplicate_issue_seeds']}")
        self.stdout.write(f"  Missing detail URLs skipped: {totals['missing_detail_url_skipped']}")
        self.stdout.write(f"  Issue detail browser reads: {totals['detail_browser_reads']}")
        self.stdout.write(f"  Issue writes skipped because detail failed: {totals['issue_writes_skipped_no_detail']}")
        self.stdout.write(f"  Created issues: {totals['issues_created']}")
        self.stdout.write(f"  Updated issues: {totals['issues_updated']}")

    def print_summary(self, *, totals, dry_run):
        created_label = "Would create" if dry_run else "Created"
        updated_label = "Would update" if dry_run else "Updated"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar fast backfill complete."))
        self.stdout.write(f"Calendar browser reads: {totals['calendar_browser_reads']}")
        self.stdout.write(f"Issue detail browser reads: {totals['detail_browser_reads']}")
        self.stdout.write(f"Issue detail read failures: {totals['detail_read_failures']}")
        self.stdout.write(f"Calendar issues found: {totals['calendar_found']}")
        self.stdout.write(
            f"Skipped incomplete calendar rows: {totals['calendar_incomplete_skipped']}"
        )
        self.stdout.write(f"Skipped by keyword: {totals['keyword_skipped']}")
        self.stdout.write(f"Skipped by calendar seed limit: {totals['limit_skipped']}")
        self.stdout.write(f"Skipped by detail limit: {totals['detail_limit_skipped']}")
        self.stdout.write(f"Calendar issues used as seeds: {totals['calendar_processed']}")
        self.stdout.write(f"Duplicate issue seeds skipped: {totals['duplicate_issue_seeds']}")
        self.stdout.write(f"Missing detail URLs skipped: {totals['missing_detail_url_skipped']}")
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


def read_calendar_for_window(*, calendar_url, limit, headed, calendar_timeout):
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

    return {
        "rendered_calendar": rendered_calendar,
        "calendar_issues": calendar_issues,
        "kept_calendar_issues": kept_calendar_issues,
        "keyword_skipped_issues": keyword_skipped_issues,
        "incomplete_count": incomplete_count,
        "limit_skipped": limit_skipped,
    }


def read_seed_issue_detail(*, series_issue, headed, timeout_ms):
    with marvel_browser_context(headed=headed) as context:
        return read_issue_detail_page(
            context=context,
            issue=series_issue,
            timeout_ms=timeout_ms,
        )


def apply_calendar_date_fallback(*, detail, calendar_issue):
    if get_detail_value(detail, "published_date"):
        return

    if calendar_issue.published_date:
        detail.published_date = calendar_issue.published_date


def build_minimal_series_from_calendar_issue(calendar_issue):
    return MarvelSeries(
        title=calendar_issue.run_title,
        start_year=calendar_issue.start_year,
        status="",
        url="",
        marvel_series_id="",
        series_slug="",
        raw_issue_link_count=0,
        load_more_clicks=0,
        issues=[],
        errors=[],
    )


def build_series_issue_from_calendar_issue(calendar_issue):
    return MarvelSeriesIssue(
        run_title=calendar_issue.run_title,
        start_year=calendar_issue.start_year,
        issue_number=calendar_issue.issue_number,
        detail_url=calendar_issue.detail_url,
        marvel_issue_id=calendar_issue.marvel_issue_id,
        issue_slug=calendar_issue.issue_slug,
    )


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
            help=f"Fast backfill all Marvel release calendar windows for {year}.",
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
        "detail_browser_reads": 0,
        "detail_read_failures": 0,
        "calendar_found": 0,
        "calendar_incomplete_skipped": 0,
        "keyword_skipped": 0,
        "limit_skipped": 0,
        "detail_limit_skipped": 0,
        "calendar_processed": 0,
        "duplicate_issue_seeds": 0,
        "missing_detail_url_skipped": 0,
        "planned_issue_detail_reads": 0,
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


def calendar_issue_sort_key(issue):
    return (
        issue.published_date,
        normalize_title(issue.run_title),
        issue_number_sort_key(issue.issue_number),
    )


def issue_identity(issue):
    return (
        normalize_title(issue.run_title),
        clean_text(issue.start_year),
        normalize_issue_number(issue.issue_number),
    )


def format_calendar_issue(issue):
    published_date = issue.published_date
    date_text = published_date.isoformat() if published_date else "no date"

    return (
        f"{issue.run_title} "
        f"({issue.start_year}) "
        f"#{issue.issue_number} "
        f"[{date_text}]"
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
        calendar_issue.run_title,
        calendar_issue.start_year,
        calendar_issue.issue_number,
    )


def contains_skip_keyword(*values):
    text = " ".join(clean_text(value) for value in values).casefold()

    return any(keyword.casefold() in text for keyword in SKIP_KEYWORDS)


def get_detail_missing_fields(detail):
    return get_issue_missing_fields(detail)