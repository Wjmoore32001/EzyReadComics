from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections

from catalog.models import ComicRun
from catalog.management.commands.sync_marvel_release_calendar_ai import (
    DEFAULT_CALENDAR_TIMEOUT_MS,
    DEFAULT_DETAIL_TIMEOUT_MS,
    DEFAULT_LIMIT,
    DEFAULT_MISSING_ISSUE_LIMIT,
    MARVEL_CALENDAR_TIME_ZONE,
    SKIP_KEYWORDS,
    apply_calendar_issue,
    build_calendar_url,
    build_missing_issue_plan,
    calendar_issue_key,
    empty_detail,
    extract_calendar_issues,
    filter_skipped_calendar_issues,
    find_existing_issue,
    find_existing_run,
    format_calendar_issue,
    format_credits,
    get_detail_missing_fields,
    get_preview_missing_fields,
    issue_has_complete_details,
    issue_number_identity,
    issue_number_sort_key,
    issue_series_key,
    normalize_issue_number,
    normalize_title,
    read_calendar_with_playwright,
    read_current_and_missing_details_with_playwright,
)


WEDNESDAY_WEEKDAY = 2


class Command(BaseCommand):
    help = (
        "Backfill old Marvel release calendar issues by walking Wednesday release dates. "
        "Uses the no-AI Marvel calendar/detail parser from sync_marvel_release_calendar_ai."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            help="Oldest date in the backfill range, YYYY-MM-DD. Prompted if omitted.",
        )
        parser.add_argument(
            "--end-date",
            help="Newest date in the backfill range, YYYY-MM-DD. Prompted if omitted.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help="Maximum kept calendar issues to process per Wednesday. Default: unlimited.",
        )
        parser.add_argument(
            "--calendar-timeout",
            type=int,
            default=DEFAULT_CALENDAR_TIMEOUT_MS,
            help=(
                "Maximum Playwright wait time in milliseconds for each calendar page. "
                f"Default: {DEFAULT_CALENDAR_TIMEOUT_MS}"
            ),
        )
        parser.add_argument(
            "--detail-timeout",
            type=int,
            default=DEFAULT_DETAIL_TIMEOUT_MS,
            help=(
                "Maximum Playwright wait time in milliseconds per issue detail page. "
                f"Default: {DEFAULT_DETAIL_TIMEOUT_MS}"
            ),
        )
        parser.add_argument(
            "--missing-issue-limit",
            type=int,
            default=DEFAULT_MISSING_ISSUE_LIMIT,
            help=(
                "Maximum previous issue pages to read per Wednesday while filling local missing issues. "
                "Default: unlimited."
            ),
        )
        parser.add_argument(
            "--skip-missing-issues",
            action="store_true",
            help="Do not walk previous issue links to fill locally missing issues.",
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--skip-details",
            action="store_true",
            help="Only read calendar pages. Do not open issue detail pages or backfill missing issues.",
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
            help="Print each kept/skipped calendar issue and row-level actions.",
        )

    def handle(self, *args, **options):
        close_old_connections()

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
        missing_issue_limit = options["missing_issue_limit"]

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1 when provided.")

        if calendar_timeout < 1000:
            raise CommandError("--calendar-timeout must be at least 1000 milliseconds.")

        if detail_timeout < 1000:
            raise CommandError("--detail-timeout must be at least 1000 milliseconds.")

        if missing_issue_limit is not None and missing_issue_limit < 0:
            raise CommandError("--missing-issue-limit cannot be negative.")

        wednesdays = get_wednesdays_newest_first(
            start_date=start_date,
            end_date=end_date,
        )

        if not wednesdays:
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
        globally_seen_issue_numbers = set()

        self.write_header(
            dry_run=dry_run,
            start_date=start_date,
            end_date=end_date,
            wednesdays=wednesdays,
            limit=limit,
            skip_details=skip_details,
            skip_missing_issues=skip_missing_issues,
            missing_issue_limit=missing_issue_limit,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
        )

        for release_date in wednesdays:
            close_old_connections()

            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Processing Marvel calendar date: {release_date.isoformat()}"
                )
            )

            date_totals = self.process_release_date(
                release_date=release_date,
                limit=limit,
                calendar_timeout=calendar_timeout,
                detail_timeout=detail_timeout,
                missing_issue_limit=missing_issue_limit,
                dry_run=dry_run,
                raw=raw,
                verbose=verbose,
                skip_details=skip_details,
                skip_missing_issues=skip_missing_issues,
                headed=headed,
                globally_seen_issue_numbers=globally_seen_issue_numbers,
            )
            merge_totals(totals, date_totals)

        close_old_connections()
        self.print_summary(totals=totals, dry_run=dry_run)

    def process_release_date(
        self,
        *,
        release_date,
        limit,
        calendar_timeout,
        detail_timeout,
        missing_issue_limit,
        dry_run,
        raw,
        verbose,
        skip_details,
        skip_missing_issues,
        headed,
        globally_seen_issue_numbers,
    ):
        totals = new_totals()
        calendar_url = build_calendar_url(
            start_date=release_date,
            end_date=release_date,
        )

        close_old_connections()

        rendered_calendar = read_calendar_with_playwright(
            calendar_url=calendar_url,
            headed=headed,
            timeout_ms=calendar_timeout,
        )
        totals["calendar_browser_reads"] += 1

        close_old_connections()

        if raw:
            self.print_raw_calendar(rendered_calendar)

        calendar_issues, incomplete_count = extract_calendar_issues(
            rendered_calendar=rendered_calendar,
        )
        totals["calendar_found"] += len(calendar_issues)
        totals["calendar_incomplete_skipped"] += incomplete_count

        kept_issues, keyword_skipped_issues = filter_skipped_calendar_issues(
            calendar_issues
        )
        totals["keyword_skipped"] += len(keyword_skipped_issues)

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

        kept_issues = remove_globally_seen_calendar_issues(
            calendar_issues=kept_issues,
            globally_seen_issue_numbers=globally_seen_issue_numbers,
        )

        if limit is not None and len(kept_issues) > limit:
            totals["limit_skipped"] += len(kept_issues) - limit
            kept_issues = kept_issues[:limit]

        if not kept_issues:
            self.stdout.write("No new kept issues for this Wednesday.")
            return totals

        missing_issue_plan = {}

        if not skip_missing_issues:
            missing_issue_plan = db_call(build_missing_issue_plan, kept_issues)
            missing_issue_plan = remove_globally_seen_from_missing_plan(
                missing_issue_plan=missing_issue_plan,
                globally_seen_issue_numbers=globally_seen_issue_numbers,
            )
            totals["missing_issue_targets"] += sum(
                len(numbers)
                for numbers in missing_issue_plan.values()
            )

        issue_records = []
        detail_read_issues = []

        for calendar_issue in kept_issues:
            existing_run = db_call(
                find_existing_run,
                title=calendar_issue["run_title"],
                start_year=calendar_issue["start_year"],
            )
            existing_issue = db_call(
                find_existing_issue,
                run=existing_run,
                issue_number=calendar_issue["issue_number"],
            )
            has_missing_issue_targets = bool(
                missing_issue_plan.get(issue_series_key(calendar_issue))
            )
            existing_detail_skipped = bool(
                existing_issue
                and db_call(issue_has_complete_details, existing_issue)
                and not has_missing_issue_targets
                and not skip_details
            )

            issue_records.append(
                {
                    "source": "calendar",
                    "calendar_issue": calendar_issue,
                    "existing_detail_skipped": existing_detail_skipped,
                    "detail": empty_detail(),
                }
            )

            if existing_detail_skipped:
                totals["existing_detail_skipped"] += 1

            if not skip_details and not existing_detail_skipped:
                detail_read_issues.append(calendar_issue)

        close_old_connections()

        if detail_read_issues:
            detail_result = read_current_and_missing_details_with_playwright(
                calendar_issues=detail_read_issues,
                missing_issue_plan=missing_issue_plan,
                skip_missing_issues=skip_missing_issues,
                missing_issue_limit=missing_issue_limit,
                headed=headed,
                timeout_ms=detail_timeout,
            )

            close_old_connections()

            for record in issue_records:
                detail = detail_result["current_details"].get(
                    calendar_issue_key(record["calendar_issue"])
                )

                if detail:
                    record["detail"] = detail

            missing_records = remove_globally_seen_records(
                records=detail_result["missing_records"],
                globally_seen_issue_numbers=globally_seen_issue_numbers,
            )

            issue_records.extend(missing_records)
            totals["missing_issues_discovered"] += len(missing_records)
            totals["missing_issue_limit_reached"] += int(
                detail_result["missing_issue_limit_reached"]
            )

        issue_records = sorted(
            issue_records,
            key=lambda record: (
                normalize_title(record["calendar_issue"]["run_title"]),
                issue_number_sort_key(record["calendar_issue"]["issue_number"]),
                0 if record["source"] == "missing" else 1,
            ),
        )

        for record in issue_records:
            close_old_connections()

            calendar_issue = record["calendar_issue"]
            detail = record["detail"]
            source = record["source"]

            globally_seen_issue_numbers.add(issue_number_identity(calendar_issue))

            existing_run = db_call(
                find_existing_run,
                title=calendar_issue["run_title"],
                start_year=calendar_issue["start_year"],
            )
            existing_issue = db_call(
                find_existing_issue,
                run=existing_run,
                issue_number=calendar_issue["issue_number"],
            )

            totals["processed"] += 1

            if source == "calendar":
                totals["calendar_processed"] += 1

            if detail.get("read_attempted"):
                if source == "missing":
                    totals["missing_issue_browser_reads"] += 1
                else:
                    totals["detail_browser_reads"] += 1

            if detail.get("error"):
                totals["detail_read_failures"] += 1

            if detail.get("checked"):
                missing_fields = db_call(
                    get_preview_missing_fields,
                    issue=existing_issue,
                    detail=detail,
                )

                if missing_fields:
                    totals["incomplete_details"] += 1
                else:
                    totals["complete_details"] += 1

                if "description" in missing_fields:
                    totals["missing_description"] += 1

                if "writer" in missing_fields:
                    totals["missing_writer"] += 1

                if raw:
                    self.print_raw_detail(
                        calendar_issue=calendar_issue,
                        detail=detail,
                    )

            result = db_call(
                apply_calendar_issue,
                retry=False,
                calendar_issue=calendar_issue,
                detail=detail,
                dry_run=dry_run,
            )

            if dry_run:
                if db_call(would_force_run_ongoing, calendar_issue):
                    result["run_updated"] = 1
            else:
                if db_call(force_run_ongoing, calendar_issue, retry=False):
                    result["run_updated"] = 1

            totals["runs_created"] += result["run_created"]
            totals["runs_updated"] += result["run_updated"]
            totals["issues_created"] += result["issue_created"]
            totals["issues_updated"] += result["issue_updated"]
            totals["credits_added"] += result["credits_added"]

            if verbose:
                self.print_issue_result(
                    source=source,
                    calendar_issue=calendar_issue,
                    detail=detail,
                    result=result,
                    dry_run=dry_run,
                    skip_details=skip_details,
                    existing_detail_skipped=record["existing_detail_skipped"],
                )

        close_old_connections()
        self.print_date_summary(totals)
        return totals

    def write_header(
        self,
        *,
        dry_run,
        start_date,
        end_date,
        wednesdays,
        limit,
        skip_details,
        skip_missing_issues,
        missing_issue_limit,
        headed,
        calendar_timeout,
        detail_timeout,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar backfill"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write(f"Range oldest date: {start_date.isoformat()}")
        self.stdout.write(f"Range newest date: {end_date.isoformat()}")
        self.stdout.write(f"Wednesdays to process: {len(wednesdays)}")
        self.stdout.write(f"First processed: {wednesdays[0].isoformat()}")
        self.stdout.write(f"Last processed: {wednesdays[-1].isoformat()}")
        self.stdout.write(f"Calendar timezone: {MARVEL_CALENDAR_TIME_ZONE}")
        self.stdout.write("Reader: Playwright Chromium")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Calendar timeout: {calendar_timeout} ms")
        self.stdout.write(f"Detail timeout: {detail_timeout} ms")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write("Run status behavior: ongoing")
        self.stdout.write(
            "Calendar issue process limit per Wednesday: "
            + (str(limit) if limit is not None else "unlimited")
        )
        self.stdout.write(f"Detail lookup: {'off' if skip_details else 'on'}")
        self.stdout.write(
            f"Missing issue backfill: {'off' if skip_missing_issues else 'on'}"
        )
        self.stdout.write(
            "Missing issue page read limit per Wednesday: "
            + (str(missing_issue_limit) if missing_issue_limit is not None else "unlimited")
        )
        self.stdout.write("Skip keywords: " + ", ".join(SKIP_KEYWORDS))
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

    def print_raw_detail(self, *, calendar_issue, detail):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"Parsed detail: {format_calendar_issue(calendar_issue)}"))
        self.stdout.write(f"Detail URL: {calendar_issue.get('detail_url') or 'none'}")
        self.stdout.write(f"Read attempted: {detail['read_attempted']}")
        self.stdout.write(f"Read error: {detail['error'] or 'none'}")
        self.stdout.write(
            "Published date from detail: "
            + (
                detail["published_date"].isoformat()
                if detail.get("published_date")
                else "none"
            )
        )
        self.stdout.write(f"Description: {detail['description'] or '[blank]'}")
        self.stdout.write(f"Credits: {format_credits(detail['credits']) or 'none'}")
        self.stdout.write(
            "Missing fields: "
            + (",".join(get_detail_missing_fields(detail)) or "none")
        )
        self.stdout.write("Text preview:")
        self.stdout.write(detail["text_preview"])

    def print_issue_result(
        self,
        *,
        source,
        calendar_issue,
        detail,
        result,
        dry_run,
        skip_details,
        existing_detail_skipped,
    ):
        self.stdout.write("")
        self.stdout.write(format_calendar_issue(calendar_issue))

        if source == "missing":
            self.stdout.write("  Source: missing issue backfill")

        if skip_details:
            self.stdout.write("  Detail lookup: skipped by flag")
        elif existing_detail_skipped:
            self.stdout.write(
                "  Detail lookup: skipped, existing issue already has description and Writer"
            )
        elif detail["checked"]:
            missing_fields = get_detail_missing_fields(detail)
            self.stdout.write("  Detail lookup: checked")
            self.stdout.write(
                "  Detail complete: "
                + ("yes" if not missing_fields else "no")
            )

            if missing_fields:
                self.stdout.write("  Missing: " + ", ".join(missing_fields))

            if detail["error"]:
                self.stdout.write("  Detail error: " + detail["error"])
        else:
            self.stdout.write("  Detail lookup: not checked")

        action_prefix = "Would" if dry_run else "Did"

        if result["run_created"]:
            self.stdout.write(f"  {action_prefix} create run")

        if result["run_updated"]:
            self.stdout.write(f"  {action_prefix} update run")

        if result["issue_created"]:
            self.stdout.write(f"  {action_prefix} create issue")

        if result["issue_updated"]:
            self.stdout.write(f"  {action_prefix} update issue")

        if result["credits_added"]:
            self.stdout.write(f"  Credits added: {result['credits_added']}")

    def print_date_summary(self, totals):
        self.stdout.write("")
        self.stdout.write("Wednesday summary:")
        self.stdout.write(f"  Calendar issues found: {totals['calendar_found']}")
        self.stdout.write(f"  Calendar issues processed: {totals['calendar_processed']}")
        self.stdout.write(f"  Missing issues discovered: {totals['missing_issues_discovered']}")
        self.stdout.write(f"  Total issues processed: {totals['processed']}")

    def print_summary(self, *, totals, dry_run):
        created_label = "Would create" if dry_run else "Created"
        updated_label = "Would update" if dry_run else "Updated"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar backfill complete."))
        self.stdout.write(f"Calendar browser reads: {totals['calendar_browser_reads']}")
        self.stdout.write(f"Current issue detail browser reads: {totals['detail_browser_reads']}")
        self.stdout.write(f"Missing issue detail browser reads: {totals['missing_issue_browser_reads']}")
        self.stdout.write(f"Issue detail read failures: {totals['detail_read_failures']}")
        self.stdout.write("AI calls: 0")
        self.stdout.write(f"Calendar issues found: {totals['calendar_found']}")
        self.stdout.write(
            f"Skipped incomplete calendar rows: {totals['calendar_incomplete_skipped']}"
        )
        self.stdout.write(f"Skipped by keyword: {totals['keyword_skipped']}")
        self.stdout.write(f"Skipped by limit: {totals['limit_skipped']}")
        self.stdout.write(f"Calendar issues processed: {totals['calendar_processed']}")
        self.stdout.write(f"Local missing issue targets: {totals['missing_issue_targets']}")
        self.stdout.write(f"Missing issues discovered from Marvel links: {totals['missing_issues_discovered']}")
        self.stdout.write(
            f"Missing issue limit reached count: {totals['missing_issue_limit_reached']}"
        )
        self.stdout.write(f"Total issues processed: {totals['processed']}")
        self.stdout.write(
            f"Detail reads skipped for complete existing issues: "
            f"{totals['existing_detail_skipped']}"
        )
        self.stdout.write(f"Issues with complete details: {totals['complete_details']}")
        self.stdout.write(f"Issues with incomplete details: {totals['incomplete_details']}")
        self.stdout.write(
            f"Issues missing description: {totals['missing_description']}"
        )
        self.stdout.write(f"Issues missing Writer: {totals['missing_writer']}")
        self.stdout.write(f"{created_label} runs: {totals['runs_created']}")
        self.stdout.write(f"{updated_label} runs: {totals['runs_updated']}")
        self.stdout.write(f"{created_label} issues: {totals['issues_created']}")
        self.stdout.write(f"{updated_label} issues: {totals['issues_updated']}")
        self.stdout.write(f"Credits added: {totals['credits_added']}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog data was created or updated.")


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


def remove_globally_seen_calendar_issues(*, calendar_issues, globally_seen_issue_numbers):
    kept_issues = []

    for calendar_issue in calendar_issues:
        identity = issue_number_identity(calendar_issue)

        if identity in globally_seen_issue_numbers:
            continue

        kept_issues.append(calendar_issue)

    return kept_issues


def remove_globally_seen_records(*, records, globally_seen_issue_numbers):
    kept_records = []

    for record in records:
        identity = issue_number_identity(record["calendar_issue"])

        if identity in globally_seen_issue_numbers:
            continue

        kept_records.append(record)

    return kept_records


def remove_globally_seen_from_missing_plan(*, missing_issue_plan, globally_seen_issue_numbers):
    cleaned_plan = {}

    for series_key, issue_numbers in missing_issue_plan.items():
        title_key, start_year = series_key
        remaining_numbers = set()

        for issue_number in issue_numbers:
            identity = (
                title_key,
                start_year,
                normalize_issue_number(str(issue_number)),
            )

            if identity in globally_seen_issue_numbers:
                continue

            remaining_numbers.add(issue_number)

        if remaining_numbers:
            cleaned_plan[series_key] = remaining_numbers

    return cleaned_plan


def would_force_run_ongoing(calendar_issue):
    run = find_existing_run(
        title=calendar_issue["run_title"],
        start_year=calendar_issue["start_year"],
    )

    if run is None:
        return False

    return run.status != ComicRun.STATUS_ONGOING


def force_run_ongoing(calendar_issue):
    run = find_existing_run(
        title=calendar_issue["run_title"],
        start_year=calendar_issue["start_year"],
    )

    if run is None:
        return False

    if run.status == ComicRun.STATUS_ONGOING:
        return False

    run.status = ComicRun.STATUS_ONGOING
    run.save(update_fields=["status", "updated_at"])
    return True


def new_totals():
    return {
        "calendar_browser_reads": 0,
        "detail_browser_reads": 0,
        "missing_issue_browser_reads": 0,
        "detail_read_failures": 0,
        "calendar_found": 0,
        "calendar_incomplete_skipped": 0,
        "keyword_skipped": 0,
        "limit_skipped": 0,
        "calendar_processed": 0,
        "missing_issue_targets": 0,
        "missing_issues_discovered": 0,
        "missing_issue_limit_reached": 0,
        "processed": 0,
        "existing_detail_skipped": 0,
        "complete_details": 0,
        "incomplete_details": 0,
        "missing_description": 0,
        "missing_writer": 0,
        "runs_created": 0,
        "runs_updated": 0,
        "issues_created": 0,
        "issues_updated": 0,
        "credits_added": 0,
    }


def merge_totals(target, source):
    for key, value in source.items():
        target[key] += value