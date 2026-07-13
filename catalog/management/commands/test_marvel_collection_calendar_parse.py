import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = None
    sync_playwright = None


MARVEL_CALENDAR_BASE_URL = "https://www.marvel.com/comics/calendar"
MARVEL_CALENDAR_TIME_ZONE = "America/New_York"

DEFAULT_CALENDAR_TIMEOUT_MS = 45000
DEFAULT_DETAIL_TIMEOUT_MS = 45000

ON_SALE_NUMERIC_DATE_RE = re.compile(
    r"ON\s+SALE:?\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)

ON_SALE_WORD_DATE_RE = re.compile(
    r"ON\s+SALE:?\s*(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)

COLLECTING_START_RE = re.compile(
    r"\bCOLLECTING\b:?\s*|\bCOLLECTS\b:?\s*",
    re.IGNORECASE,
)

NORMAL_RUN_TOKEN_RE = re.compile(
    r"(?P<title>[A-Z][A-Z0-9 .:'’!?&/+,\-]+?)\s*\((?P<year>\d{4})\)",
)

PRE_YEAR_ISSUE_TOKEN_RE = re.compile(
    r"(?P<title_prefix>[A-Z][A-Z0-9 .:'’!?&/+,\-]*?)\s+"
    r"#(?P<issue>[A-Z0-9.]+(?:\s*[-–—]\s*[A-Z0-9.]+)?)\s+"
    r"(?P<title_suffix>[A-Z][A-Z0-9 .:'’!?&/+,\-]*?)\s*"
    r"\((?P<year>\d{4})\)",
)

ISSUE_TOKEN_RE = re.compile(
    r"#\s*(?P<issue>[A-Za-z0-9.]+(?:\s*[-–—]\s*[A-Za-z0-9.]+)?)",
)

CALENDAR_COLLECTION_LINK_RE = re.compile(
    r"/comics/collection/\d+/",
    re.IGNORECASE,
)

STOP_TEXT_MARKERS = (
    "DIGITAL ISSUE",
    "MORE DETAILS",
    "EXTENDED CREDITS",
    "Rating:",
    "Format:",
    "FOC Date:",
    "Price:",
    "ISBN",
    "STORIES",
    "COVER INFORMATION",
    "MORE ",
    "RECOMMENDED SERIES",
    "ABOUT MARVEL",
    "Terms of Use",
    "Privacy Policy",
    "©",
)

DETAIL_ROLE_LABELS = {
    "WRITER",
    "WRITERS",
    "ARTIST",
    "ARTISTS",
    "PENCILLER",
    "PENCILLERS",
    "PENCILER",
    "PENCILERS",
    "COVER ARTIST",
    "COVER ARTISTS",
}


class Command(BaseCommand):
    help = (
        "Test parsing official Marvel.com collection calendar pages and collection descriptions. "
        "No catalog data is created or updated."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            action="append",
            default=[],
            help=(
                "Direct Marvel collection URL to test. Can be passed multiple times. "
                "When provided, the calendar page is skipped."
            ),
        )
        parser.add_argument(
            "--date",
            help="Single calendar date to test, YYYY-MM-DD. Sets dateStart and dateEnd to the same date.",
        )
        parser.add_argument(
            "--start-date",
            help="Calendar start date, YYYY-MM-DD. Default: current Marvel/Eastern date.",
        )
        parser.add_argument(
            "--end-date",
            help="Calendar end date, YYYY-MM-DD. Default: start date plus 6 days.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum collection pages to test. Default: unlimited.",
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
                "Maximum Playwright wait time in milliseconds per collection detail page. "
                f"Default: {DEFAULT_DETAIL_TIMEOUT_MS}"
            ),
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print rendered page text previews.",
        )
        parser.add_argument(
            "--show-description",
            action="store_true",
            help="Print the parsed description candidate. Off by default to keep output readable.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print parsed collection rows and detailed parser notes.",
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

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1 when provided.")

        if calendar_timeout < 1000:
            raise CommandError("--calendar-timeout must be at least 1000 milliseconds.")

        if detail_timeout < 1000:
            raise CommandError("--detail-timeout must be at least 1000 milliseconds.")

        direct_urls = [
            clean_text(url)
            for url in options["url"]
            if clean_text(url)
        ]

        headed = options["headed"]
        raw = options["raw"]
        verbose = options["verbose"]
        show_description = options["show_description"]

        if direct_urls:
            collections = build_direct_url_collections(direct_urls)

            if limit is not None and len(collections) > limit:
                collections = collections[:limit]

            self.write_direct_url_header(
                collections=collections,
                headed=headed,
                detail_timeout=detail_timeout,
            )
        else:
            start_date, end_date = resolve_date_range(options)
            calendar_url = build_collection_calendar_url(
                start_date=start_date,
                end_date=end_date,
            )

            self.write_calendar_header(
                start_date=start_date,
                end_date=end_date,
                calendar_url=calendar_url,
                headed=headed,
                limit=limit,
                calendar_timeout=calendar_timeout,
                detail_timeout=detail_timeout,
            )

            rendered_calendar = read_collection_calendar_with_playwright(
                calendar_url=calendar_url,
                headed=headed,
                timeout_ms=calendar_timeout,
            )

            if raw:
                self.print_raw_calendar(rendered_calendar)

            collections = extract_calendar_collections(rendered_calendar)

            if limit is not None and len(collections) > limit:
                collections = collections[:limit]

        if verbose:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Collections queued for detail parsing"))

            for collection in collections:
                self.stdout.write(format_collection_row(collection))

        details = read_collection_details_with_playwright(
            collections=collections,
            headed=headed,
            timeout_ms=detail_timeout,
        )

        collections_with_collecting_text = 0
        collections_with_run_links = 0
        collections_with_one_shots = 0
        collections_without_refs = 0
        total_volume_run_links = 0
        total_exact_issue_links = 0
        total_one_shot_links = 0

        for collection in collections:
            detail = details.get(collection["detail_url"], empty_collection_detail())

            if detail["collecting_text"]:
                collections_with_collecting_text += 1

            if detail["run_links"]:
                collections_with_run_links += 1

            if detail["one_shots"]:
                collections_with_one_shots += 1

            if not detail["run_links"] and not detail["one_shots"]:
                collections_without_refs += 1

            total_volume_run_links += len(detail["run_links"])
            total_one_shot_links += len(detail["one_shots"])
            total_exact_issue_links += sum(
                len(reference["issue_numbers"])
                for reference in detail["run_links"]
            )

            self.print_collection_result(
                collection=collection,
                detail=detail,
                raw=raw,
                show_description=show_description,
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel collection parse test complete."))
        self.stdout.write(f"Collections tested: {len(collections)}")
        self.stdout.write(f"Collections with explicit Collecting text: {collections_with_collecting_text}")
        self.stdout.write(f"Collections with parsed future ComicVolumeRun links: {collections_with_run_links}")
        self.stdout.write(f"Collections with parsed future ComicOneShot links: {collections_with_one_shots}")
        self.stdout.write(f"Collections without parsed references: {collections_without_refs}")
        self.stdout.write(f"Future ComicVolumeRun links parsed: {total_volume_run_links}")
        self.stdout.write(f"Future ComicVolumeIssue exact issue links parsed: {total_exact_issue_links}")
        self.stdout.write(f"Future ComicVolumeOneShot links parsed: {total_one_shot_links}")
        self.stdout.write("Catalog writes: 0")

    def write_calendar_header(
        self,
        *,
        start_date,
        end_date,
        calendar_url,
        headed,
        limit,
        calendar_timeout,
        detail_timeout,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel collection calendar parse test"))
        self.stdout.write(f"Source: {calendar_url}")
        self.stdout.write(
            "Date range: "
            f"{start_date.isoformat()} to {end_date.isoformat()}"
        )
        self.stdout.write(f"Calendar timezone: {MARVEL_CALENDAR_TIME_ZONE}")
        self.stdout.write("Calendar tab: collection")
        self.stdout.write("Variants parameter: false")
        self.stdout.write("Reader: Playwright Chromium")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Calendar timeout: {calendar_timeout} ms")
        self.stdout.write(f"Detail timeout: {detail_timeout} ms")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Comic Vine calls: 0")
        self.stdout.write("Catalog writes: 0")
        self.stdout.write(
            "Collection page process limit: "
            + (str(limit) if limit is not None else "unlimited")
        )

    def write_direct_url_header(
        self,
        *,
        collections,
        headed,
        detail_timeout,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel direct collection URL parse test"))
        self.stdout.write(f"Collection URLs: {len(collections)}")
        self.stdout.write(f"Calendar timezone: {MARVEL_CALENDAR_TIME_ZONE}")
        self.stdout.write("Reader: Playwright Chromium")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Detail timeout: {detail_timeout} ms")
        self.stdout.write("Calendar reads: 0")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Comic Vine calls: 0")
        self.stdout.write("Catalog writes: 0")

    def print_raw_calendar(self, rendered_calendar):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Rendered Marvel collection calendar page"))
        self.stdout.write(f"Page title: {rendered_calendar['title']}")
        self.stdout.write(f"HTTP status: {rendered_calendar['status']}")
        self.stdout.write(f"Text length: {len(rendered_calendar['text'])}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Rendered text preview"))
        self.stdout.write(rendered_calendar["text"][:5000])

        if rendered_calendar["links"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Rendered collection links"))

            for link in rendered_calendar["links"][:50]:
                self.stdout.write(f"- {link['text']} -> {link['href']}")

    def print_collection_result(self, *, collection, detail, raw, show_description):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(format_collection_row(collection)))
        self.stdout.write(f"Detail URL: {collection['detail_url']}")
        self.stdout.write(f"Read attempted: {detail['read_attempted']}")
        self.stdout.write(f"Read error: {detail['error'] or 'none'}")
        self.stdout.write(f"Parse confidence: {detail['confidence']}")

        if show_description and detail["description"]:
            self.stdout.write("")
            self.stdout.write("Description candidate:")
            self.stdout.write(detail["description"])

        if detail["collecting_text"]:
            self.stdout.write("")
            self.stdout.write("Collecting text:")
            self.stdout.write(detail["collecting_text"])
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Collecting text: none found"))

        if detail["run_links"]:
            self.stdout.write("")
            self.stdout.write("Future ComicVolumeRun / ComicVolumeIssue candidates:")

            for reference in detail["run_links"]:
                issue_summary = summarize_issue_numbers(reference["issue_numbers"])

                self.stdout.write(
                    f"- {reference['run_title']} "
                    f"({reference['start_year']}): "
                    f"{issue_summary}"
                )
                self.stdout.write(
                    "  ComicVolumeRun issue_numbers_text: "
                    + reference["issue_numbers_text"]
                )

                if reference["first_issue_number"] or reference["last_issue_number"]:
                    self.stdout.write(
                        "  ComicVolumeRun first/last: "
                        + f"{reference['first_issue_number'] or 'blank'}"
                        + " / "
                        + f"{reference['last_issue_number'] or 'blank'}"
                    )

                if reference["issue_numbers"]:
                    self.stdout.write(
                        "  ComicVolumeIssue exact candidates: "
                        + ", ".join(f"#{issue_number}" for issue_number in reference["issue_numbers"])
                    )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Future ComicVolumeRun / ComicVolumeIssue candidates: none"))

        if detail["one_shots"]:
            self.stdout.write("")
            self.stdout.write("Future ComicOneShot / ComicVolumeOneShot candidates:")

            for one_shot in detail["one_shots"]:
                reason_text = f" [{one_shot['reason']}]" if one_shot["reason"] else ""

                self.stdout.write(
                    f"- {one_shot['title']} "
                    f"({one_shot['start_year']})"
                    f"{reason_text}"
                )

                if one_shot["source_issue_expression"]:
                    self.stdout.write(
                        "  source issue expression ignored for one-shot storage: "
                        + one_shot["source_issue_expression"]
                    )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Future ComicOneShot / ComicVolumeOneShot candidates: none"))

        if detail["warnings"]:
            self.stdout.write("")
            self.stdout.write("Parser warnings:")

            for warning in detail["warnings"]:
                self.stdout.write(f"- {warning}")

        if raw:
            self.stdout.write("")
            self.stdout.write("Detail text preview:")
            self.stdout.write(detail["text_preview"])


def resolve_date_range(options):
    single_date = clean_text(options.get("date"))

    if single_date:
        parsed_date = parse_iso_date(single_date)
        return parsed_date, parsed_date

    start_date_text = clean_text(options.get("start_date"))
    end_date_text = clean_text(options.get("end_date"))

    if start_date_text:
        start_date = parse_iso_date(start_date_text)
    else:
        start_date = current_marvel_date()

    if end_date_text:
        end_date = parse_iso_date(end_date_text)
    else:
        end_date = start_date + timedelta(days=6)

    if start_date > end_date:
        raise CommandError("--start-date must be earlier than or equal to --end-date.")

    return start_date, end_date


def parse_iso_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def build_direct_url_collections(urls):
    collections = []

    for url in urls:
        if not CALENDAR_COLLECTION_LINK_RE.search(url):
            raise CommandError(f"Not a Marvel collection URL: {url}")

        collections.append(
            {
                "title": title_from_collection_url(url) or "[direct collection URL]",
                "published_date": None,
                "detail_url": url,
            }
        )

    return collections


def read_collection_calendar_with_playwright(*, calendar_url, headed, timeout_ms):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not headed,
        )
        context = build_browser_context(browser)

        try:
            return read_rendered_collection_calendar_page(
                context=context,
                calendar_url=calendar_url,
                timeout_ms=timeout_ms,
            )
        finally:
            context.close()
            browser.close()


def read_collection_details_with_playwright(*, collections, headed, timeout_ms):
    details = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not headed,
        )
        context = build_browser_context(browser)

        try:
            for collection in collections:
                details[collection["detail_url"]] = read_collection_detail_page(
                    context=context,
                    collection=collection,
                    timeout_ms=timeout_ms,
                )
        finally:
            context.close()
            browser.close()

    return details


def build_browser_context(browser):
    return browser.new_context(
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


def read_rendered_collection_calendar_page(*, context, calendar_url, timeout_ms):
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
                f"Marvel collection calendar page returned HTTP {status}. "
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
                    const links = Array.from(document.querySelectorAll("a"));
                    return links.some((link) => (link.href || "").includes("/comics/collection/"));
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
            elements => {
                function normalizeText(value) {
                    return String(value || "")
                        .replace(/\\u00a0/g, " ")
                        .replace(/[ \\t]+/g, " ")
                        .replace(/\\n[ \\t]+/g, "\\n")
                        .replace(/[ \\t]+\\n/g, "\\n")
                        .trim();
                }

                return elements
                    .map((element) => ({
                        text: normalizeText(element.innerText || element.textContent || ""),
                        href: element.href || ""
                    }))
                    .filter((item) => item.href && item.href.includes("/comics/collection/"));
            }
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


def read_collection_detail_page(*, context, collection, timeout_ms):
    detail_url = clean_text(collection.get("detail_url"))

    if not detail_url:
        detail = empty_collection_detail()
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
            detail = empty_collection_detail()
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
                    return text.includes("Collecting") ||
                           text.includes("COLLECTING") ||
                           text.includes("ISBN") ||
                           text.length > 1000;
                }
                """,
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError:
            pass

        page.wait_for_timeout(1000)

        text = page.locator("body").inner_text(timeout=timeout_ms)
        detail = parse_collection_detail_text(text=text)
        detail["read_attempted"] = True
        detail["error"] = ""
        detail["text_preview"] = text[:2500]
        return detail

    except Exception as exc:
        detail = empty_collection_detail()
        detail["read_attempted"] = True
        detail["error"] = str(exc)
        return detail
    finally:
        page.close()


def extract_calendar_collections(rendered_calendar):
    grouped = {}

    for link in rendered_calendar.get("links") or []:
        detail_url = clean_text(link.get("href"))

        if not detail_url or not CALENDAR_COLLECTION_LINK_RE.search(detail_url):
            continue

        grouped.setdefault(detail_url, []).append(clean_collection_title(link.get("text")))

    collections = []

    for detail_url, title_candidates in grouped.items():
        title = best_collection_title_candidate(title_candidates)

        if not title:
            title = title_from_collection_url(detail_url)

        published_date = parse_calendar_date_from_text(rendered_calendar.get("text"))

        collections.append(
            {
                "title": title or "[unknown collection title]",
                "published_date": published_date,
                "detail_url": detail_url,
            }
        )

    return sorted(collections, key=collection_sort_key)


def best_collection_title_candidate(title_candidates):
    cleaned_candidates = []

    for title in title_candidates:
        title = clean_collection_title(title)

        if not title:
            continue

        if len(title) < 4:
            continue

        if title.upper() in {"COMICS", "COLLECTIONS", "NEW COLLECTIONS"}:
            continue

        cleaned_candidates.append(title)

    if not cleaned_candidates:
        return ""

    cleaned_candidates = sorted(
        cleaned_candidates,
        key=lambda value: (
            collection_title_score(value),
            len(value),
        ),
        reverse=True,
    )

    return cleaned_candidates[0]


def collection_title_score(title):
    score = 0
    upper_title = title.upper()

    if "TRADE PAPERBACK" in upper_title:
        score += 5

    if "HARDCOVER" in upper_title:
        score += 5

    if "OMNIBUS" in upper_title:
        score += 3

    if "VOL." in upper_title or "VOL " in upper_title:
        score += 2

    if "(" in title and ")" in title:
        score += 2

    return score


def title_from_collection_url(url):
    match = re.search(r"/comics/collection/\d+/([^/?#]+)", clean_text(url))

    if not match:
        return ""

    slug = match.group(1)
    slug = slug.replace("_", " ")
    return clean_collection_title(slug.title())


def parse_collection_detail_text(*, text):
    description = extract_description_from_detail_text(text)
    collecting_text = extract_collecting_text(description)

    if not collecting_text:
        collecting_text = extract_collecting_text(text)

    run_links, one_shots = parse_collected_items(collecting_text)
    warnings = []

    if not description:
        warnings.append("No useful description text was found.")

    if not collecting_text:
        warnings.append("No explicit Collecting/Collects text was found.")

    if collecting_text and not run_links and not one_shots:
        warnings.append("Collecting text was found, but no run/year/issue references were parsed.")

    confidence = determine_parse_confidence(
        collecting_text=collecting_text,
        run_links=run_links,
        one_shots=one_shots,
    )

    return {
        "read_attempted": False,
        "error": "",
        "description": description,
        "collecting_text": collecting_text,
        "run_links": run_links,
        "one_shots": one_shots,
        "warnings": unique_list(warnings),
        "confidence": confidence,
        "text_preview": text[:2500],
    }


def extract_description_from_detail_text(text):
    lines = normalize_page_lines(text)

    if not lines:
        return ""

    start_index = find_description_start_index(lines)
    end_index = find_description_end_index(lines, start_index)

    if start_index is None or end_index is None or end_index <= start_index:
        return ""

    description_lines = []

    for line in lines[start_index:end_index]:
        if should_skip_description_line(line):
            continue

        description_lines.append(line)

    description = clean_description(" ".join(description_lines))

    if description:
        return description

    collecting_text = extract_collecting_text(normalize_text(text))

    if collecting_text:
        return collecting_text

    return ""


def find_description_start_index(lines):
    label_indices = []

    for index, line in enumerate(lines):
        label = normalize_label(line)

        if label in DETAIL_ROLE_LABELS:
            label_indices.append(index)

    if label_indices:
        last_label_index = label_indices[-1]

        if last_label_index + 2 < len(lines):
            return last_label_index + 2

    for index, line in enumerate(lines):
        if "Collecting " in line or "COLLECTING " in line:
            return index

    return None


def find_description_end_index(lines, start_index):
    if start_index is None:
        return None

    for index in range(start_index, len(lines)):
        if is_description_stop_line(lines[index]):
            return index

    return len(lines)


def is_description_stop_line(line):
    normalized = normalize_text(line)

    for marker in STOP_TEXT_MARKERS:
        if normalized.upper().startswith(marker.upper()):
            return True

    return False


def should_skip_description_line(line):
    normalized = normalize_text(line)

    if not normalized:
        return True

    if normalized.upper() in {
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
    }:
        return True

    return False


def extract_collecting_text(value):
    value = normalize_text(value)

    if not value:
        return ""

    match = COLLECTING_START_RE.search(value)

    if not match:
        return ""

    chunk = value[match.start():]
    chunk = truncate_at_stop_marker(chunk)
    chunk = truncate_collecting_sentence(chunk)
    return clean_description(chunk)


def truncate_collecting_sentence(value):
    value = normalize_text(value)
    period_match = re.search(r"\.(?:\s|$)", value)

    if period_match:
        return value[:period_match.start()]

    return value


def truncate_at_stop_marker(value):
    earliest_index = None

    for marker in STOP_TEXT_MARKERS:
        match = re.search(re.escape(marker), value, flags=re.IGNORECASE)

        if not match:
            continue

        if earliest_index is None or match.start() < earliest_index:
            earliest_index = match.start()

    if earliest_index is None:
        return value

    return value[:earliest_index]


def parse_collected_items(collecting_text):
    collecting_text = normalize_collecting_text(collecting_text)

    if not collecting_text:
        return [], []

    collecting_body = COLLECTING_START_RE.sub("", collecting_text, count=1).strip()
    run_tokens = find_collected_run_tokens(collecting_body)

    run_links = []
    one_shots = []

    for index, token in enumerate(run_tokens):
        next_start = run_tokens[index + 1]["start"] if index + 1 < len(run_tokens) else len(collecting_body)
        tail = collecting_body[token["end"]:next_start]

        issue_expressions, issue_numbers = parse_issue_tokens(tail)

        if not issue_expressions and token["embedded_issue"]:
            issue_expressions = [token["embedded_issue"]]
            issue_numbers = expand_issue_expression(token["embedded_issue"])

        one_shot_reason = one_shot_reason_for_token(
            token=token,
            issue_expressions=issue_expressions,
            issue_numbers=issue_numbers,
            token_index=index,
        )

        if one_shot_reason:
            one_shots.append(
                build_one_shot_candidate(
                    title=token["title"],
                    start_year=token["year"],
                    source_issue_expression=issue_expressions[0] if issue_expressions else "",
                    reason=one_shot_reason,
                )
            )
            continue

        if not issue_expressions:
            one_shots.append(
                build_one_shot_candidate(
                    title=token["title"],
                    start_year=token["year"],
                    source_issue_expression="",
                    reason="no issue number listed; treating as one-shot candidate",
                )
            )
            continue

        run_links.append(
            build_run_link(
                run_title=token["title"],
                start_year=token["year"],
                issue_expressions=issue_expressions,
                issue_numbers=issue_numbers,
            )
        )

    run_links = merge_run_link_duplicates(run_links)
    one_shots = merge_one_shot_duplicates(one_shots)

    for reference in run_links:
        reference["issue_numbers"] = sorted(
            unique_list(reference["issue_numbers"]),
            key=issue_number_sort_key,
        )
        reference["issue_expressions"] = unique_list(reference["issue_expressions"])
        reference["issue_numbers_text"] = ",".join(reference["issue_expressions"])
        reference["first_issue_number"] = first_issue_number(reference["issue_numbers"])
        reference["last_issue_number"] = last_issue_number(reference["issue_numbers"])

    return (
        sorted(
            run_links,
            key=lambda item: (
                normalize_title(item["run_title"]),
                item["start_year"],
            ),
        ),
        sorted(
            one_shots,
            key=lambda item: (
                normalize_title(item["title"]),
                item["start_year"],
            ),
        ),
    )


def normalize_collecting_text(value):
    value = normalize_text(value)
    value = value.replace("–", "-").replace("—", "-")
    return value.strip(" .")


def find_collected_run_tokens(collecting_body):
    candidates = []

    for match in PRE_YEAR_ISSUE_TOKEN_RE.finditer(collecting_body):
        title_prefix = clean_collected_run_title(match.group("title_prefix"))
        title_suffix = clean_collected_run_title(match.group("title_suffix"))
        title = f"{title_prefix}: {title_suffix}"
        title = clean_collected_run_title(title)
        embedded_issue = clean_issue_expression(match.group("issue"))

        candidates.append(
            {
                "start": match.start(),
                "end": match.end(),
                "title": title,
                "year": clean_text(match.group("year")),
                "embedded_issue": embedded_issue,
                "priority": 2,
            }
        )

    for match in NORMAL_RUN_TOKEN_RE.finditer(collecting_body):
        title = clean_collected_run_title(match.group("title"))

        if not title:
            continue

        candidates.append(
            {
                "start": match.start(),
                "end": match.end(),
                "title": title,
                "year": clean_text(match.group("year")),
                "embedded_issue": "",
                "priority": 1,
            }
        )

    candidates = remove_overlapping_run_tokens(candidates)

    return sorted(candidates, key=lambda token: token["start"])


def remove_overlapping_run_tokens(candidates):
    candidates = sorted(
        candidates,
        key=lambda token: (
            token["start"],
            -token["priority"],
            -(token["end"] - token["start"]),
        ),
    )
    kept = []

    for candidate in candidates:
        overlaps = False

        for kept_token in kept:
            if ranges_overlap(
                candidate["start"],
                candidate["end"],
                kept_token["start"],
                kept_token["end"],
            ):
                overlaps = True
                break

        if overlaps:
            continue

        kept.append(candidate)

    return kept


def ranges_overlap(left_start, left_end, right_start, right_end):
    return left_start < right_end and right_start < left_end


def parse_issue_tokens(value):
    expressions = []
    issue_numbers = []

    for match in ISSUE_TOKEN_RE.finditer(value):
        expression = clean_issue_expression(match.group("issue"))

        if not is_valid_issue_expression(expression):
            continue

        expressions.append(expression)

        for issue_number in expand_issue_expression(expression):
            issue_numbers.append(issue_number)

    return unique_list(expressions), unique_list(issue_numbers)


def one_shot_reason_for_token(*, token, issue_expressions, issue_numbers, token_index):
    if not issue_expressions:
        return "no issue number listed; treating as one-shot candidate"

    if len(issue_numbers) != 1:
        return ""

    only_issue_number = clean_text(issue_numbers[0])

    if only_issue_number not in {"0", "1"}:
        return ""

    if token["embedded_issue"]:
        return f"issue #{only_issue_number} appears inside title token"

    if token_index > 0:
        return f"single issue #{only_issue_number} after primary collected run"

    if title_looks_like_one_shot(token["title"]):
        return f"title looks like one-shot/special and only issue #{only_issue_number} is listed"

    return ""


def title_looks_like_one_shot(title):
    normalized = normalize_title(title)

    one_shot_markers = {
        "special",
        "one shot",
        "wedding special",
        "fallout",
        "negative zone",
        "grimm noir",
        "yancy street",
        "annual",
        "zero",
    }

    return any(marker in normalized for marker in one_shot_markers)


def build_run_link(*, run_title, start_year, issue_expressions, issue_numbers):
    return {
        "run_title": run_title,
        "start_year": start_year,
        "issue_expressions": unique_list(issue_expressions),
        "issue_numbers": unique_list(issue_numbers),
        "issue_numbers_text": "",
        "first_issue_number": "",
        "last_issue_number": "",
    }


def build_one_shot_candidate(*, title, start_year, source_issue_expression, reason):
    return {
        "title": title,
        "start_year": start_year,
        "source_issue_expression": clean_text(source_issue_expression),
        "reason": clean_text(reason),
    }


def merge_run_link_duplicates(references):
    merged = {}

    for reference in references:
        key = (
            normalize_title(reference["run_title"]),
            reference["start_year"],
        )
        existing = merged.setdefault(
            key,
            {
                "run_title": reference["run_title"],
                "start_year": reference["start_year"],
                "issue_expressions": [],
                "issue_numbers": [],
                "issue_numbers_text": "",
                "first_issue_number": "",
                "last_issue_number": "",
            },
        )

        existing["issue_expressions"].extend(reference["issue_expressions"])
        existing["issue_numbers"].extend(reference["issue_numbers"])

    return list(merged.values())


def merge_one_shot_duplicates(one_shots):
    merged = {}

    for one_shot in one_shots:
        key = (
            normalize_title(one_shot["title"]),
            one_shot["start_year"],
        )
        existing = merged.setdefault(
            key,
            {
                "title": one_shot["title"],
                "start_year": one_shot["start_year"],
                "source_issue_expression": "",
                "reason": "",
            },
        )

        if not existing["source_issue_expression"] and one_shot["source_issue_expression"]:
            existing["source_issue_expression"] = one_shot["source_issue_expression"]

        if not existing["reason"] and one_shot["reason"]:
            existing["reason"] = one_shot["reason"]

    return list(merged.values())


def first_issue_number(issue_numbers):
    if not issue_numbers:
        return ""

    sorted_numbers = sorted(issue_numbers, key=issue_number_sort_key)
    return clean_text(sorted_numbers[0])


def last_issue_number(issue_numbers):
    if not issue_numbers:
        return ""

    sorted_numbers = sorted(issue_numbers, key=issue_number_sort_key)
    return clean_text(sorted_numbers[-1])


def clean_issue_expression(value):
    value = clean_text(value)
    value = value.replace("–", "-").replace("—", "-")
    value = value.strip(" #,;:.")
    value = re.sub(r"\s*-\s*", "-", value)
    value = re.sub(r"\s+", "", value)
    return value


def is_valid_issue_expression(value):
    if not value:
        return False

    if not re.fullmatch(r"[A-Za-z0-9.]+(?:-[A-Za-z0-9.]+)?", value):
        return False

    if value.casefold() in {
        "and",
        "or",
        "the",
        "a",
        "an",
        "of",
        "from",
        "material",
    }:
        return False

    return True


def expand_issue_expression(expression):
    expression = clean_issue_expression(expression)

    if "-" not in expression:
        return [expression]

    start_text, end_text = expression.split("-", 1)

    if not start_text.isdigit() or not end_text.isdigit():
        return [expression]

    start = int(start_text)
    end = int(end_text)

    if end < start:
        return [expression]

    if end - start > 300:
        return [expression]

    return [str(number) for number in range(start, end + 1)]


def determine_parse_confidence(*, collecting_text, run_links, one_shots):
    if not collecting_text:
        return "none"

    if not run_links and not one_shots:
        return "none"

    return "high"


def empty_collection_detail():
    return {
        "read_attempted": False,
        "error": "",
        "description": "",
        "collecting_text": "",
        "run_links": [],
        "one_shots": [],
        "warnings": [],
        "confidence": "none",
        "text_preview": "",
    }


def parse_calendar_date_from_text(value):
    value = clean_text(value)

    for match in ON_SALE_NUMERIC_DATE_RE.finditer(value):
        parsed_date = parse_display_date(match.group("date"))

        if parsed_date:
            return parsed_date

    for match in ON_SALE_WORD_DATE_RE.finditer(value):
        parsed_date = parse_display_date(match.group("date"))

        if parsed_date:
            return parsed_date

    return None


def parse_display_date(value):
    value = clean_text(value)

    for date_format in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None


def build_collection_calendar_url(*, start_date, end_date):
    return (
        f"{MARVEL_CALENDAR_BASE_URL}"
        f"?dateEnd={end_date.isoformat()}"
        f"&dateStart={start_date.isoformat()}"
        f"&tab=collection"
        f"&variants=false"
    )


def clean_collection_title(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -:|")


def clean_collected_run_title(value):
    value = clean_text(value)
    value = re.sub(
        r"^(?:collecting|collects|plus|and|including|featuring|with|material\s+from)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,;:-")


def normalize_page_lines(text):
    lines = []

    for line in str(text or "").splitlines():
        line = clean_text(line)

        if not line:
            continue

        lines.append(line)

    return lines


def normalize_label(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" :").upper()


def clean_description(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_text(value):
    value = clean_text(value)
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


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


def collection_sort_key(collection):
    published_date = collection.get("published_date") or datetime.max.date()

    return (
        published_date,
        normalize_title(collection.get("title")),
        collection.get("detail_url") or "",
    )


def issue_number_sort_key(value):
    value = clean_text(value)
    match = re.match(r"^(\d+)(.*)$", value)

    if not match:
        return 999999, value

    return int(match.group(1)), match.group(2)


def summarize_issue_numbers(issue_numbers):
    if not issue_numbers:
        return "none"

    numeric_values = []

    for issue_number in issue_numbers:
        if str(issue_number).isdigit():
            numeric_values.append(int(issue_number))
        else:
            return ", ".join(f"#{value}" for value in issue_numbers)

    numeric_values = sorted(set(numeric_values))
    ranges = []
    start = numeric_values[0]
    previous = numeric_values[0]

    for value in numeric_values[1:]:
        if value == previous + 1:
            previous = value
            continue

        ranges.append((start, previous))
        start = value
        previous = value

    ranges.append((start, previous))

    parts = []

    for start_value, end_value in ranges:
        if start_value == end_value:
            parts.append(f"#{start_value}")
        else:
            parts.append(f"#{start_value}-{end_value}")

    return ", ".join(parts)


def unique_list(values):
    seen = set()
    unique_values = []

    for value in values:
        key = clean_text(value).casefold()

        if key in seen:
            continue

        seen.add(key)
        unique_values.append(value)

    return unique_values


def format_collection_row(collection):
    published_date = collection.get("published_date")

    if published_date:
        published_date_text = published_date.isoformat()
    else:
        published_date_text = "unknown-date"

    return f"{collection['title']} [{published_date_text}]"