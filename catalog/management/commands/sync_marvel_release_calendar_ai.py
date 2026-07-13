import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = None
    sync_playwright = None

from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicPublisher,
    ComicRun,
    CreditPerson,
    CreditRole,
)


MARVEL_CALENDAR_BASE_URL = "https://www.marvel.com/comics/calendar"
MARVEL_CALENDAR_TIME_ZONE = "America/New_York"
MARVEL_PUBLISHER_NAME = "Marvel"

DEFAULT_LIMIT = 50
DEFAULT_CALENDAR_TIMEOUT_MS = 45000
DEFAULT_DETAIL_TIMEOUT_MS = 45000

SKIP_KEYWORDS = (
    "FACSIMILE",
    "STAR WARS",
    "PREDATOR",
    "ALIEN",
    "GODZILLA",
)

ROLE_DISPLAY_ORDER = {
    "Writer": 10,
    "Artist": 20,
    "Penciller": 30,
    "Inker": 40,
    "Colorist": 50,
    "Letterer": 60,
    "Cover Artist": 70,
    "Editor": 80,
}

DETAIL_CREDIT_LABELS = {
    "WRITER": "Writer",
    "WRITERS": "Writer",
    "ARTIST": "Artist",
    "ARTISTS": "Artist",
    "PENCILLER": "Penciller",
    "PENCILLERS": "Penciller",
    "PENCILER": "Penciller",
    "PENCILERS": "Penciller",
    "INKER": "Inker",
    "INKERS": "Inker",
    "COLORIST": "Colorist",
    "COLORISTS": "Colorist",
    "COLOURIST": "Colorist",
    "COLOURISTS": "Colorist",
    "LETTERER": "Letterer",
    "LETTERERS": "Letterer",
    "COVER ARTIST": "Cover Artist",
    "COVER ARTISTS": "Cover Artist",
    "EDITOR": "Editor",
    "EDITORS": "Editor",
}

DETAIL_STOP_LINES = {
    "SEE VARIANT COVERS",
    "DIGITAL ISSUE",
    "MORE DETAILS",
    "COLLECTING",
    "RELATED",
}

DETAIL_SKIP_LINES = {
    "SKIP MENU",
    "LOG IN",
    "SIGN UP",
    "MARVEL UNLIMITED",
    "SUBSCRIBE",
    "NEWS",
    "COMICS",
    "CHARACTERS",
    "GAMES",
    "MOVIES",
    "TV SHOWS",
    "VIDEOS",
    "MORE",
    "BACK TO SERIES",
    "PREV",
    "NEXT",
}

ISSUE_TEXT_RE = re.compile(
    r"(?P<title>[A-Z0-9][^\n\r#]{1,180}?)\s*"
    r"\((?P<year>\d{4})\)\s*"
    r"#(?P<issue>[A-Z0-9][A-Z0-9.\-/]*)",
    re.IGNORECASE,
)

ON_SALE_NUMERIC_DATE_RE = re.compile(
    r"ON\s+SALE:?\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)

ON_SALE_WORD_DATE_RE = re.compile(
    r"ON\s+SALE:?\s*(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


class Command(BaseCommand):
    help = (
        "Sync current Marvel release calendar issues from Marvel.com. "
        "Uses Playwright for the rendered calendar and issue detail pages. No AI calls."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Maximum kept calendar issues to process. Default: {DEFAULT_LIMIT}",
        )
        parser.add_argument(
            "--calendar-timeout",
            type=int,
            default=DEFAULT_CALENDAR_TIMEOUT_MS,
            help=(
                "Maximum Playwright wait time in milliseconds for the calendar page. "
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
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--skip-details",
            action="store_true",
            help="Only read the calendar list. Do not open issue detail pages.",
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
        if sync_playwright is None:
            raise CommandError(
                "Playwright is not installed. Run: "
                "pip install playwright && python -m playwright install chromium"
            )

        limit = options["limit"]
        calendar_timeout = options["calendar_timeout"]
        detail_timeout = options["detail_timeout"]

        if limit < 1:
            raise CommandError("--limit must be at least 1.")

        if calendar_timeout < 1000:
            raise CommandError("--calendar-timeout must be at least 1000 milliseconds.")

        if detail_timeout < 1000:
            raise CommandError("--detail-timeout must be at least 1000 milliseconds.")

        calendar_start_date = current_marvel_date()
        calendar_end_date = calendar_start_date + timedelta(days=6)
        calendar_url = build_calendar_url(
            start_date=calendar_start_date,
            end_date=calendar_end_date,
        )

        dry_run = options["dry_run"]
        raw = options["raw"]
        verbose = options["verbose"]
        skip_details = options["skip_details"]
        headed = options["headed"]

        self.write_header(
            dry_run=dry_run,
            limit=limit,
            skip_details=skip_details,
            calendar_start_date=calendar_start_date,
            calendar_end_date=calendar_end_date,
            calendar_url=calendar_url,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
        )

        totals = {
            "calendar_browser_reads": 0,
            "detail_browser_reads": 0,
            "detail_read_failures": 0,
            "calendar_found": 0,
            "calendar_incomplete_skipped": 0,
            "keyword_skipped": 0,
            "limit_skipped": 0,
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

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=not headed,
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={
                    "width": 1440,
                    "height": 1800,
                },
                locale="en-US",
                timezone_id=MARVEL_CALENDAR_TIME_ZONE,
            )

            try:
                rendered_calendar = read_rendered_calendar_page(
                    context=context,
                    calendar_url=calendar_url,
                    timeout_ms=calendar_timeout,
                )
                totals["calendar_browser_reads"] += 1

                if raw:
                    self.print_raw_calendar(rendered_calendar)

                calendar_issues, incomplete_count = extract_calendar_issues(
                    rendered_calendar=rendered_calendar,
                )
                totals["calendar_found"] = len(calendar_issues)
                totals["calendar_incomplete_skipped"] = incomplete_count

                kept_issues, keyword_skipped_issues = filter_skipped_calendar_issues(
                    calendar_issues
                )
                totals["keyword_skipped"] = len(keyword_skipped_issues)

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

                if len(kept_issues) > limit:
                    totals["limit_skipped"] = len(kept_issues) - limit
                    kept_issues = kept_issues[:limit]

                for calendar_issue in kept_issues:
                    totals["processed"] += 1

                    existing_run = find_existing_run(
                        title=calendar_issue["run_title"],
                        start_year=calendar_issue["start_year"],
                    )
                    existing_issue = find_existing_issue(
                        run=existing_run,
                        issue_number=calendar_issue["issue_number"],
                    )

                    detail = empty_detail()

                    if skip_details:
                        pass
                    elif existing_issue and issue_has_complete_details(existing_issue):
                        totals["existing_detail_skipped"] += 1
                    else:
                        detail = read_issue_detail_page(
                            context=context,
                            calendar_issue=calendar_issue,
                            timeout_ms=detail_timeout,
                        )

                        if detail["read_attempted"]:
                            totals["detail_browser_reads"] += 1

                        if detail["error"]:
                            totals["detail_read_failures"] += 1

                        missing_fields = get_preview_missing_fields(
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
                            self.print_raw_detail(calendar_issue=calendar_issue, detail=detail)

                    result = apply_calendar_issue(
                        calendar_issue=calendar_issue,
                        detail=detail,
                        dry_run=dry_run,
                    )

                    totals["runs_created"] += result["run_created"]
                    totals["runs_updated"] += result["run_updated"]
                    totals["issues_created"] += result["issue_created"]
                    totals["issues_updated"] += result["issue_updated"]
                    totals["credits_added"] += result["credits_added"]

                    if verbose:
                        self.print_issue_result(
                            calendar_issue=calendar_issue,
                            detail=detail,
                            result=result,
                            dry_run=dry_run,
                            skip_details=skip_details,
                            existing_detail_skipped=bool(
                                existing_issue and issue_has_complete_details(existing_issue)
                            ),
                        )

            finally:
                context.close()
                browser.close()

        self.print_summary(totals=totals, dry_run=dry_run)

    def write_header(
        self,
        *,
        dry_run,
        limit,
        skip_details,
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
        self.stdout.write(f"Detail timeout: {detail_timeout} ms")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write(f"Calendar issue process limit: {limit}")
        self.stdout.write(f"Detail lookup: {'off' if skip_details else 'on'}")
        self.stdout.write("Skip keywords: " + ", ".join(SKIP_KEYWORDS))
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

    def print_raw_detail(self, *, calendar_issue, detail):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"Parsed detail: {format_calendar_issue(calendar_issue)}"))
        self.stdout.write(f"Detail URL: {calendar_issue.get('detail_url') or 'none'}")
        self.stdout.write(f"Read attempted: {detail['read_attempted']}")
        self.stdout.write(f"Read error: {detail['error'] or 'none'}")
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
        calendar_issue,
        detail,
        result,
        dry_run,
        skip_details,
        existing_detail_skipped,
    ):
        self.stdout.write("")
        self.stdout.write(format_calendar_issue(calendar_issue))

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

    def print_summary(self, *, totals, dry_run):
        created_label = "Would create" if dry_run else "Created"
        updated_label = "Would update" if dry_run else "Updated"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel release calendar sync complete."))
        self.stdout.write(f"Calendar browser reads: {totals['calendar_browser_reads']}")
        self.stdout.write(f"Issue detail browser reads: {totals['detail_browser_reads']}")
        self.stdout.write(f"Issue detail read failures: {totals['detail_read_failures']}")
        self.stdout.write("AI calls: 0")
        self.stdout.write(f"Calendar issues found: {totals['calendar_found']}")
        self.stdout.write(
            f"Skipped incomplete calendar rows: {totals['calendar_incomplete_skipped']}"
        )
        self.stdout.write(f"Skipped by keyword: {totals['keyword_skipped']}")
        self.stdout.write(f"Skipped by limit: {totals['limit_skipped']}")
        self.stdout.write(f"Issues processed: {totals['processed']}")
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


def read_rendered_calendar_page(*, context, calendar_url, timeout_ms):
    page = context.new_page()

    try:
        response = page.goto(
            calendar_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )

        status = response.status if response else None

        if status and status >= 400:
            text = page.locator("body").inner_text(timeout=5000)
            raise CommandError(
                f"Marvel calendar page returned HTTP {status}. "
                f"Try again with --headed. Page text: {text[:500]}"
            )

        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

        try:
            page.wait_for_function(
                """
                () => {
                    const text = document.body ? document.body.innerText : "";
                    return text.includes("ON SALE") || /\\(\\d{4}\\)\\s*#/.test(text);
                }
                """,
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError:
            pass

        page.wait_for_timeout(1000)

        title = page.title()
        text = page.locator("body").inner_text(timeout=timeout_ms)
        links = page.eval_on_selector_all(
            "a",
            """
            elements => elements
                .map((element) => ({
                    text: (element.innerText || "").trim(),
                    href: element.href || ""
                }))
                .filter((item) => item.text && /\\(\\d{4}\\)\\s*#/.test(item.text))
            """,
        )

        return {
            "title": title,
            "status": status,
            "text": text,
            "links": links,
        }
    finally:
        page.close()


def read_issue_detail_page(*, context, calendar_issue, timeout_ms):
    detail_url = clean_text(calendar_issue.get("detail_url"))

    if not detail_url:
        detail = empty_detail()
        detail["checked"] = True
        detail["read_attempted"] = False
        detail["error"] = "missing detail URL"
        return detail

    page = context.new_page()

    try:
        response = page.goto(
            detail_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        status = response.status if response else None

        if status and status >= 400:
            detail = empty_detail()
            detail["checked"] = True
            detail["read_attempted"] = True
            detail["error"] = f"HTTP {status}"
            return detail

        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

        try:
            page.wait_for_function(
                """
                () => {
                    const text = document.body ? document.body.innerText : "";
                    return text.includes("PUBLISHED") || text.includes("See Variant Covers");
                }
                """,
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError:
            pass

        page.wait_for_timeout(1000)

        text = page.locator("body").inner_text(timeout=timeout_ms)
        detail = parse_issue_detail_text(
            text=text,
            calendar_issue=calendar_issue,
        )
        detail["checked"] = True
        detail["read_attempted"] = True
        detail["error"] = ""
        detail["text_preview"] = text[:2000]
        return detail

    except Exception as exc:
        detail = empty_detail()
        detail["checked"] = True
        detail["read_attempted"] = True
        detail["error"] = str(exc)
        return detail
    finally:
        page.close()


def parse_issue_detail_text(*, text, calendar_issue):
    lines = normalize_page_lines(text)
    title_index = find_detail_title_index(lines=lines, calendar_issue=calendar_issue)
    end_index = find_detail_end_index(lines=lines, start_index=title_index)

    credits = []
    last_metadata_index = title_index
    index = title_index + 1

    while index < end_index:
        line = lines[index]
        label, inline_value = parse_detail_label_line(line)

        if label == "PUBLISHED":
            value_index = find_next_value_line_index(
                lines=lines,
                start_index=index + 1,
                end_index=end_index,
            )

            if value_index is not None:
                last_metadata_index = max(last_metadata_index, value_index)
                index = value_index + 1
                continue

            last_metadata_index = max(last_metadata_index, index)
            index += 1
            continue

        role = DETAIL_CREDIT_LABELS.get(label)

        if role:
            names_text = inline_value

            if not names_text:
                value_index = find_next_value_line_index(
                    lines=lines,
                    start_index=index + 1,
                    end_index=end_index,
                )

                if value_index is not None and looks_like_people_line(lines[value_index]):
                    names_text = lines[value_index]
                    last_metadata_index = max(last_metadata_index, value_index)
                    index = value_index + 1
                else:
                    last_metadata_index = max(last_metadata_index, index)
                    index += 1
            else:
                last_metadata_index = max(last_metadata_index, index)
                index += 1

            for person_name in split_credit_names(names_text):
                credits.append(
                    {
                        "role": role,
                        "name": person_name,
                    }
                )

            continue

        index += 1

    description_lines = []

    for line in lines[last_metadata_index + 1:end_index]:
        if should_skip_description_line(line):
            continue

        label, _ = parse_detail_label_line(line)

        if label == "PUBLISHED" or label in DETAIL_CREDIT_LABELS:
            continue

        description_lines.append(line)

    description = clean_description(" ".join(description_lines))

    return {
        "checked": False,
        "read_attempted": False,
        "error": "",
        "description": description,
        "credits": normalize_credit_list(credits),
        "text_preview": text[:2000],
    }


def extract_calendar_issues(*, rendered_calendar):
    text_issues = extract_calendar_issues_from_text(rendered_calendar["text"])
    link_map = build_issue_link_map(rendered_calendar["links"])

    issues = []
    seen = set()
    incomplete_count = 0

    for issue in text_issues:
        normalized_key = calendar_issue_identity(issue)

        if not normalized_key:
            incomplete_count += 1
            continue

        if normalized_key in seen:
            continue

        seen.add(normalized_key)
        detail_url = link_map.get(
            (
                normalize_title(issue["run_title"]),
                clean_text(issue["start_year"]),
                normalize_issue_number(issue["issue_number"]),
            )
        )

        if detail_url:
            issue["detail_url"] = detail_url

        issues.append(issue)

    return sorted(issues, key=calendar_issue_sort_key), incomplete_count


def extract_calendar_issues_from_text(text):
    date_markers = find_on_sale_date_markers(text)
    issues = []

    if not date_markers:
        return issues

    for match in ISSUE_TEXT_RE.finditer(text):
        published_date = find_latest_date_before_position(
            date_markers=date_markers,
            position=match.start(),
        )

        if published_date is None:
            continue

        run_title = clean_calendar_title(match.group("title"))
        start_year = clean_text(match.group("year"))
        issue_number = canonical_issue_number(match.group("issue"))

        if not run_title or not start_year or not issue_number:
            continue

        issues.append(
            {
                "run_title": run_title,
                "start_year": start_year,
                "issue_number": issue_number,
                "published_date": published_date,
                "detail_url": "",
            }
        )

    return issues


def find_on_sale_date_markers(text):
    markers = []

    for match in ON_SALE_NUMERIC_DATE_RE.finditer(text):
        parsed_date = parse_calendar_display_date(match.group("date"))

        if parsed_date:
            markers.append(
                {
                    "position": match.start(),
                    "date": parsed_date,
                }
            )

    for match in ON_SALE_WORD_DATE_RE.finditer(text):
        parsed_date = parse_calendar_display_date(match.group("date"))

        if parsed_date:
            markers.append(
                {
                    "position": match.start(),
                    "date": parsed_date,
                }
            )

    return sorted(markers, key=lambda item: item["position"])


def find_latest_date_before_position(*, date_markers, position):
    latest = None

    for marker in date_markers:
        if marker["position"] > position:
            break

        latest = marker["date"]

    return latest


def build_issue_link_map(links):
    link_map = {}

    for link in links or []:
        text = clean_text(link.get("text"))
        href = clean_text(link.get("href"))
        match = ISSUE_TEXT_RE.search(text)

        if not match or not href:
            continue

        run_title = clean_calendar_title(match.group("title"))
        start_year = clean_text(match.group("year"))
        issue_number = canonical_issue_number(match.group("issue"))

        key = (
            normalize_title(run_title),
            start_year,
            normalize_issue_number(issue_number),
        )
        link_map[key] = href

    return link_map


def calendar_issue_identity(issue):
    run_title = clean_text(issue.get("run_title"))
    start_year = clean_text(issue.get("start_year"))
    issue_number = canonical_issue_number(issue.get("issue_number"))
    published_date = issue.get("published_date")

    if not run_title or not start_year or not issue_number or not published_date:
        return None

    return (
        normalize_title(run_title),
        start_year,
        normalize_issue_number(issue_number),
        published_date,
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
        calendar_issue.get("run_title"),
        calendar_issue.get("start_year"),
        calendar_issue.get("issue_number"),
    )


def contains_skip_keyword(*values):
    text = " ".join(clean_text(value) for value in values).casefold()

    return any(keyword.casefold() in text for keyword in SKIP_KEYWORDS)


def apply_calendar_issue(*, calendar_issue, detail, dry_run):
    result = {
        "run_created": 0,
        "run_updated": 0,
        "issue_created": 0,
        "issue_updated": 0,
        "credits_added": 0,
    }

    existing_run = find_existing_run(
        title=calendar_issue["run_title"],
        start_year=calendar_issue["start_year"],
    )
    existing_issue = find_existing_issue(
        run=existing_run,
        issue_number=calendar_issue["issue_number"],
    )

    if dry_run:
        result["run_created"] = 1 if existing_run is None else 0
        result["run_updated"] = (
            0
            if existing_run is None
            else int(run_needs_release_update(existing_run, calendar_issue))
        )
        result["issue_created"] = 1 if existing_issue is None else 0
        result["issue_updated"] = (
            0
            if existing_issue is None
            else int(issue_needs_release_update(existing_issue, calendar_issue, detail))
        )
        result["credits_added"] = count_new_issue_credits(
            issue=existing_issue,
            credits=detail.get("credits") or [],
        )
        return result

    with transaction.atomic():
        publisher = get_or_create_marvel_publisher()
        run = existing_run

        if run is None:
            run = create_run_from_calendar_issue(
                publisher=publisher,
                calendar_issue=calendar_issue,
            )
            result["run_created"] = 1
        else:
            if update_run_from_calendar_issue(run=run, calendar_issue=calendar_issue):
                result["run_updated"] = 1

        issue = find_existing_issue(
            run=run,
            issue_number=calendar_issue["issue_number"],
        )
        issue_was_created = False

        if issue is None:
            issue = create_issue_from_calendar_issue(
                run=run,
                calendar_issue=calendar_issue,
                detail=detail,
            )
            issue_was_created = True
            result["issue_created"] = 1
        else:
            if update_issue_from_calendar_issue(
                issue=issue,
                calendar_issue=calendar_issue,
                detail=detail,
            ):
                result["issue_updated"] = 1

        result["credits_added"] = add_issue_credits(
            issue=issue,
            credits=detail.get("credits") or [],
        )

        if detail.get("checked"):
            tracking_changed = update_issue_official_detail_tracking(issue)

            if tracking_changed and not issue_was_created:
                result["issue_updated"] = 1

    return result


def get_or_create_marvel_publisher():
    existing = ComicPublisher.objects.filter(name__iexact=MARVEL_PUBLISHER_NAME).first()

    if existing:
        return existing

    base_slug = slugify(MARVEL_PUBLISHER_NAME) or "marvel"
    slug = base_slug
    suffix = 2

    while ComicPublisher.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    return ComicPublisher.objects.create(
        name=MARVEL_PUBLISHER_NAME,
        slug=slug,
    )


def find_existing_run(*, title, start_year):
    title = clean_text(title)
    start_year = clean_text(start_year)

    if not title:
        return None

    queryset = ComicRun.objects.all()

    if start_year:
        queryset = queryset.filter(start_year=start_year)

    exact_match = queryset.filter(title__iexact=title).order_by("id").first()

    if exact_match:
        return exact_match

    normalized_title = normalize_title(title)

    if not normalized_title:
        return None

    for run in queryset.order_by("id"):
        if normalize_title(run.title) == normalized_title:
            return run

    return None


def find_existing_issue(*, run, issue_number):
    if run is None:
        return None

    normalized_target = normalize_issue_number(issue_number)

    if not normalized_target:
        return None

    for issue in run.issues.all().order_by("id"):
        if normalize_issue_number(issue.issue_number) == normalized_target:
            return issue

    return None


def create_run_from_calendar_issue(*, publisher, calendar_issue):
    published_date = calendar_issue["published_date"]
    issue_number = calendar_issue["issue_number"]

    return ComicRun.objects.create(
        publisher=publisher,
        title=calendar_issue["run_title"],
        start_year=calendar_issue["start_year"],
        first_issue_date=published_date if is_first_issue_number(issue_number) else None,
        last_issue_date=published_date,
        status=derive_run_status(
            issue_number=issue_number,
            published_date=published_date,
        ),
        issue_count=pure_integer_issue_number(issue_number),
        description="",
    )


def update_run_from_calendar_issue(*, run, calendar_issue):
    changed = False
    published_date = calendar_issue["published_date"]
    issue_number = calendar_issue["issue_number"]
    issue_count = pure_integer_issue_number(issue_number)

    if issue_count is not None and (
        run.issue_count is None or issue_count > run.issue_count
    ):
        run.issue_count = issue_count
        changed = True

    if published_date and (
        run.last_issue_date is None or published_date > run.last_issue_date
    ):
        run.last_issue_date = published_date
        changed = True

    if (
        is_first_issue_number(issue_number)
        and published_date
        and run.first_issue_date is None
    ):
        run.first_issue_date = published_date
        changed = True

    derived_status = derive_run_status(
        issue_number=issue_number,
        published_date=published_date,
    )

    if derived_status and run.status != derived_status:
        run.status = derived_status
        changed = True

    if changed:
        run.save()

    return changed


def run_needs_release_update(run, calendar_issue):
    published_date = calendar_issue["published_date"]
    issue_number = calendar_issue["issue_number"]
    issue_count = pure_integer_issue_number(issue_number)

    if issue_count is not None and (
        run.issue_count is None or issue_count > run.issue_count
    ):
        return True

    if published_date and (
        run.last_issue_date is None or published_date > run.last_issue_date
    ):
        return True

    if (
        is_first_issue_number(issue_number)
        and published_date
        and run.first_issue_date is None
    ):
        return True

    derived_status = derive_run_status(
        issue_number=issue_number,
        published_date=published_date,
    )

    if derived_status and run.status != derived_status:
        return True

    return False


def derive_run_status(*, issue_number, published_date):
    if is_first_issue_number(issue_number) and published_date > current_marvel_date():
        return ComicRun.STATUS_UPCOMING

    return ComicRun.STATUS_ONGOING


def create_issue_from_calendar_issue(*, run, calendar_issue, detail):
    published_date = calendar_issue["published_date"]

    return ComicIssue.objects.create(
        run=run,
        issue_number=calendar_issue["issue_number"],
        title="",
        cover_date=None,
        published_date=published_date,
        is_released=published_date <= current_marvel_date(),
        description=clean_text(detail.get("description")),
    )


def update_issue_from_calendar_issue(*, issue, calendar_issue, detail):
    changed = False
    published_date = calendar_issue["published_date"]

    if issue.issue_number != calendar_issue["issue_number"]:
        duplicate_exists = (
            ComicIssue.objects.filter(
                run=issue.run,
                issue_number=calendar_issue["issue_number"],
            )
            .exclude(id=issue.id)
            .exists()
        )

        if not duplicate_exists:
            issue.issue_number = calendar_issue["issue_number"]
            changed = True

    if issue.published_date != published_date:
        issue.published_date = published_date
        changed = True

    is_released = published_date <= current_marvel_date()

    if issue.is_released != is_released:
        issue.is_released = is_released
        changed = True

    description = clean_text(detail.get("description"))

    if description and not issue.description:
        issue.description = description
        changed = True

    if issue.title:
        issue.title = ""
        changed = True

    if changed:
        issue.save()

    return changed


def issue_needs_release_update(issue, calendar_issue, detail):
    published_date = calendar_issue["published_date"]

    if issue.issue_number != calendar_issue["issue_number"]:
        return True

    if issue.published_date != published_date:
        return True

    if issue.is_released != (published_date <= current_marvel_date()):
        return True

    description = clean_text(detail.get("description"))

    if description and not issue.description:
        return True

    if issue.title:
        return True

    if detail.get("checked"):
        status, missing_fields = preview_official_detail_tracking(
            issue=issue,
            detail=detail,
        )

        if issue.official_detail_status != status:
            return True

        if issue.official_detail_missing_fields != missing_fields:
            return True

    return False


def update_issue_official_detail_tracking(issue):
    missing_fields = get_issue_missing_official_fields(issue)
    status = (
        ComicIssue.OFFICIAL_DETAIL_STATUS_INCOMPLETE
        if missing_fields
        else ComicIssue.OFFICIAL_DETAIL_STATUS_COMPLETE
    )
    missing_fields_text = ",".join(missing_fields)

    changed = False

    if issue.official_detail_status != status:
        issue.official_detail_status = status
        changed = True

    if issue.official_detail_missing_fields != missing_fields_text:
        issue.official_detail_missing_fields = missing_fields_text
        changed = True

    issue.official_detail_checked_at = timezone.now()
    changed = True

    if changed:
        issue.save()

    return changed


def preview_official_detail_tracking(*, issue, detail):
    missing_fields = get_preview_missing_fields(issue=issue, detail=detail)
    status = (
        ComicIssue.OFFICIAL_DETAIL_STATUS_INCOMPLETE
        if missing_fields
        else ComicIssue.OFFICIAL_DETAIL_STATUS_COMPLETE
    )

    return status, ",".join(missing_fields)


def get_issue_missing_official_fields(issue):
    missing_fields = []

    if not clean_text(issue.description):
        missing_fields.append("description")

    if not issue_has_role(issue, "Writer"):
        missing_fields.append("writer")

    return missing_fields


def get_preview_missing_fields(*, issue, detail):
    missing_fields = []

    has_description = bool(clean_text(detail.get("description")))

    if issue is not None and clean_text(issue.description):
        has_description = True

    has_writer = detail_has_writer(detail)

    if issue is not None and issue_has_role(issue, "Writer"):
        has_writer = True

    if not has_description:
        missing_fields.append("description")

    if not has_writer:
        missing_fields.append("writer")

    return missing_fields


def get_detail_missing_fields(detail):
    missing_fields = []

    if not clean_text(detail.get("description")):
        missing_fields.append("description")

    if not detail_has_writer(detail):
        missing_fields.append("writer")

    return missing_fields


def issue_has_complete_details(issue):
    if not clean_text(issue.description):
        return False

    return issue_has_role(issue, "Writer")


def issue_has_role(issue, role_name):
    target_role = role_name.casefold()

    for credit in issue.credits.select_related("role").all():
        if credit.role.name.casefold() == target_role:
            return True

    return False


def add_issue_credits(*, issue, credits):
    created_count = 0

    for index, credit in enumerate(normalize_credit_list(credits), start=1):
        role_name = normalize_credit_role(credit.get("role"))
        person_name = clean_credit_name(credit.get("name"))

        if not role_name or not person_name:
            continue

        role = get_or_create_credit_role(name=role_name)
        person = get_or_create_credit_person(person_name)

        _, created = ComicIssueCredit.objects.get_or_create(
            issue=issue,
            person=person,
            role=role,
            defaults={
                "credit_order": index,
            },
        )

        if created:
            created_count += 1

    return created_count


def count_new_issue_credits(*, issue, credits):
    normalized_credits = normalize_credit_list(credits)

    if issue is None:
        return len(normalized_credits)

    count = 0

    for credit in normalized_credits:
        role_name = normalize_credit_role(credit.get("role"))
        person_name = clean_credit_name(credit.get("name"))

        if not role_name or not person_name:
            continue

        exists = ComicIssueCredit.objects.filter(
            issue=issue,
            person__name__iexact=person_name,
            role__name__iexact=role_name,
        ).exists()

        if not exists:
            count += 1

    return count


def get_or_create_credit_role(*, name):
    display_order = ROLE_DISPLAY_ORDER.get(name, 100)

    role = CreditRole.objects.filter(name__iexact=name).first()

    if role is None:
        return CreditRole.objects.create(
            name=name,
            display_order=display_order,
            show_by_default=True,
        )

    changed = False

    if role.display_order != display_order:
        role.display_order = display_order
        changed = True

    if not role.show_by_default:
        role.show_by_default = True
        changed = True

    if changed:
        role.save()

    return role


def get_or_create_credit_person(name):
    existing = CreditPerson.objects.filter(name__iexact=name).first()

    if existing:
        return existing

    return CreditPerson.objects.create(name=name)


def normalize_credit_list(value):
    if not value:
        return []

    credits = []
    seen = set()

    for item in value:
        if not isinstance(item, dict):
            continue

        role = normalize_credit_role(item.get("role"))
        name = clean_credit_name(item.get("name"))

        if not role or not name:
            continue

        key = (role.casefold(), name.casefold())

        if key in seen:
            continue

        seen.add(key)
        credits.append(
            {
                "role": role,
                "name": name,
            }
        )

    return credits


def normalize_credit_role(value):
    value = clean_text(value)
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = re.sub(r"\s+", " ", value).strip(" :;,.")
    key = value.casefold()

    role_aliases = {
        "writer": "Writer",
        "writers": "Writer",
        "artist": "Artist",
        "artists": "Artist",
        "penciler": "Penciller",
        "pencilers": "Penciller",
        "penciller": "Penciller",
        "pencillers": "Penciller",
        "inker": "Inker",
        "inkers": "Inker",
        "colorist": "Colorist",
        "colorists": "Colorist",
        "colourist": "Colorist",
        "colourists": "Colorist",
        "letterer": "Letterer",
        "letterers": "Letterer",
        "cover": "Cover Artist",
        "cover artist": "Cover Artist",
        "cover artists": "Cover Artist",
        "editor": "Editor",
        "editors": "Editor",
    }

    if key in role_aliases:
        return role_aliases[key]

    return value.title()


def detail_has_writer(detail):
    for credit in detail.get("credits") or []:
        if normalize_credit_role(credit.get("role")) == "Writer":
            return True

    return False


def empty_detail():
    return {
        "checked": False,
        "read_attempted": False,
        "error": "",
        "description": "",
        "credits": [],
        "text_preview": "",
    }


def normalize_page_lines(text):
    lines = []

    for line in str(text or "").splitlines():
        line = clean_text(line)

        if not line:
            continue

        lines.append(line)

    return lines


def find_detail_title_index(*, lines, calendar_issue):
    normalized_target_title = normalize_title(calendar_issue["run_title"])
    target_issue_number = normalize_issue_number(calendar_issue["issue_number"])

    for index, line in enumerate(lines):
        match = ISSUE_TEXT_RE.search(line)

        if not match:
            continue

        line_title = normalize_title(match.group("title"))
        line_issue_number = normalize_issue_number(match.group("issue"))

        if line_title == normalized_target_title and line_issue_number == target_issue_number:
            return index

    for index, line in enumerate(lines):
        if normalized_target_title and normalized_target_title in normalize_title(line):
            return index

    return 0


def find_detail_end_index(*, lines, start_index):
    for index in range(start_index + 1, len(lines)):
        normalized = normalize_detail_label(lines[index])

        if normalized in DETAIL_STOP_LINES:
            return index

        if any(normalized.startswith(f"{stop} ") for stop in DETAIL_STOP_LINES):
            return index

    return len(lines)


def parse_detail_label_line(line):
    line = clean_text(line)

    if ":" in line:
        label, value = line.split(":", 1)
    else:
        label = line
        value = ""

    return normalize_detail_label(label), clean_text(value)


def normalize_detail_label(value):
    value = clean_text(value)
    value = value.strip(":")
    value = re.sub(r"\s+", " ", value)
    return value.upper()


def find_next_value_line_index(*, lines, start_index, end_index):
    for index in range(start_index, end_index):
        line = lines[index]
        label, _ = parse_detail_label_line(line)

        if label == "PUBLISHED" or label in DETAIL_CREDIT_LABELS:
            return None

        if normalize_detail_label(line) in DETAIL_STOP_LINES:
            return None

        if should_skip_description_line(line):
            continue

        return index

    return None


def looks_like_people_line(line):
    line = clean_text(line)

    if not line:
        return False

    if len(line) > 120:
        return False

    if re.search(r"[!?]", line):
        return False

    words = re.findall(r"[A-Za-z][A-Za-z.'-]*", line)

    if len(words) > 10:
        return False

    return True


def split_credit_names(value):
    value = clean_text(value)

    if not value:
        return []

    value = value.replace("\n", ", ")
    value = re.sub(r"\s+and\s+", ", ", value, flags=re.IGNORECASE)
    pieces = re.split(r"\s*,\s*|\s*;\s*", value)
    names = []

    for piece in pieces:
        name = clean_credit_name(piece)

        if not name:
            continue

        names.append(name)

    return names


def should_skip_description_line(line):
    normalized = normalize_detail_label(line)

    if normalized in DETAIL_SKIP_LINES:
        return True

    if normalized in DETAIL_STOP_LINES:
        return True

    if normalized.startswith("READ ONLINE"):
        return True

    if normalized.startswith("DIGITAL ISSUE"):
        return True

    if normalized.startswith("SEE VARIANT"):
        return True

    if normalized.startswith("MARVEL UNLIMITED"):
        return True

    if normalized.startswith("ABOUT MARVEL"):
        return True

    if normalized.startswith("TERMS OF USE"):
        return True

    if normalized.startswith("PRIVACY POLICY"):
        return True

    if normalized.startswith("©"):
        return True

    return False


def clean_description(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_credit_name(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,;")


def parse_calendar_display_date(value):
    value = clean_text(value)

    for date_format in ("%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None


def canonical_issue_number(value):
    value = clean_text(value)
    value = re.sub(r"^\s*issue\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*no\.?\s*", "", value, flags=re.IGNORECASE)

    while value.startswith("#"):
        value = value[1:].strip()

    return value.strip()


def normalize_issue_number(value):
    value = canonical_issue_number(value).casefold()
    return re.sub(r"[^a-z0-9.]+", "", value)


def is_first_issue_number(value):
    return canonical_issue_number(value) == "1"


def pure_integer_issue_number(value):
    value = canonical_issue_number(value)

    if not re.fullmatch(r"\d+", value):
        return None

    return int(value)


def clean_calendar_title(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(
        r"^(?:load\s+more|new\s+this\s+week|comics|latest\s+comics)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip(" -:|")


def normalize_title(value):
    value = clean_text(value).casefold()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def current_marvel_date():
    return datetime.now(ZoneInfo(MARVEL_CALENDAR_TIME_ZONE)).date()


def build_calendar_url(*, start_date, end_date):
    return (
        f"{MARVEL_CALENDAR_BASE_URL}"
        f"?dateEnd={end_date.isoformat()}"
        f"&dateStart={start_date.isoformat()}"
        f"&tab=comic"
        f"&variants=false"
    )


def calendar_issue_sort_key(calendar_issue):
    return (
        calendar_issue["published_date"],
        normalize_title(calendar_issue["run_title"]),
        issue_number_sort_key(calendar_issue["issue_number"]),
    )


def issue_number_sort_key(value):
    value = canonical_issue_number(value)
    match = re.match(r"^(\d+)(.*)$", value)

    if not match:
        return 999999, value

    return int(match.group(1)), match.group(2)


def format_calendar_issue(calendar_issue):
    return (
        f"{calendar_issue['run_title']} "
        f"({calendar_issue['start_year']}) "
        f"#{calendar_issue['issue_number']} "
        f"[{calendar_issue['published_date'].isoformat()}]"
    )


def format_credits(credits):
    normalized_credits = normalize_credit_list(credits)

    if not normalized_credits:
        return ""

    return "; ".join(
        f"{credit['role']}: {credit['name']}"
        for credit in normalized_credits
    )