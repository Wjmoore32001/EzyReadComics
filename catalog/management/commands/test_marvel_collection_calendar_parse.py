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

RUN_TOKEN_RE = re.compile(
    r"(?P<title>[A-Za-z0-9][A-Za-z0-9 .:'’!?&/+,\-]{1,160}?)"
    r"\s*\((?P<year>\d{4})\)",
    re.IGNORECASE,
)

COLLECTING_START_RE = re.compile(
    r"\b(?P<label>COLLECTING|COLLECTS|Collecting|Collects)\b:?\s*",
    re.IGNORECASE,
)

ISSUE_LIST_AFTER_HASH_RE = re.compile(
    r"#\s*(?P<issue_list>[A-Za-z0-9.,#\s\-–—]+)",
    re.IGNORECASE,
)

STOP_TEXT_MARKERS = (
    "ISBN",
    "Rated",
    "Rating",
    "Format",
    "Page Count",
    "Pages",
    "Price",
    "Trim Size",
    "FOC",
    "See Variant Covers",
    "Digital Issue",
    "Read Online",
    "More Details",
    "About Marvel",
    "Terms of Use",
    "Privacy Policy",
    "©",
)

PARAGRAPH_SKIP_MARKERS = (
    "Skip menu",
    "Log in",
    "Sign up",
    "Marvel Unlimited",
    "Subscribe",
    "Follow Marvel",
    "Terms of Use",
    "Privacy Policy",
    "Your Privacy Choices",
    "Children's Online Privacy Policy",
    "Interest-Based Ads",
    "©",
)


class Command(BaseCommand):
    help = (
        "Test parsing official Marvel.com collection calendar pages and collection descriptions. "
        "No catalog data is created or updated."
    )

    def add_arguments(self, parser):
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

        start_date, end_date = resolve_date_range(options)
        calendar_url = build_collection_calendar_url(
            start_date=start_date,
            end_date=end_date,
        )

        headed = options["headed"]
        raw = options["raw"]
        verbose = options["verbose"]

        self.write_header(
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
            self.stdout.write(self.style.SUCCESS("Calendar collections parsed"))

            for collection in collections:
                self.stdout.write(format_collection_row(collection))

        details = read_collection_details_with_playwright(
            collections=collections,
            headed=headed,
            timeout_ms=detail_timeout,
        )

        parsed_with_refs = 0
        parsed_without_refs = 0
        explicit_collecting_text_count = 0

        for collection in collections:
            detail = details.get(collection["detail_url"], empty_collection_detail())

            if detail["collecting_texts"]:
                explicit_collecting_text_count += 1

            if detail["references"]:
                parsed_with_refs += 1
            else:
                parsed_without_refs += 1

            self.print_collection_result(
                collection=collection,
                detail=detail,
                raw=raw,
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel collection parse test complete."))
        self.stdout.write(f"Calendar collections found: {len(collections)}")
        self.stdout.write(f"Collections with explicit collecting text: {explicit_collecting_text_count}")
        self.stdout.write(f"Collections with parsed issue references: {parsed_with_refs}")
        self.stdout.write(f"Collections without parsed issue references: {parsed_without_refs}")
        self.stdout.write("Catalog writes: 0")

    def write_header(
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

    def print_collection_result(self, *, collection, detail, raw):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(format_collection_row(collection)))
        self.stdout.write(f"Detail URL: {collection['detail_url']}")
        self.stdout.write(f"Read attempted: {detail['read_attempted']}")
        self.stdout.write(f"Read error: {detail['error'] or 'none'}")
        self.stdout.write(f"Parse confidence: {detail['confidence']}")

        if detail["description"]:
            self.stdout.write("")
            self.stdout.write("Description candidate:")
            self.stdout.write(detail["description"])

        if detail["collecting_texts"]:
            self.stdout.write("")
            self.stdout.write("Collecting text candidate(s):")

            for collecting_text in detail["collecting_texts"]:
                self.stdout.write(f"- {collecting_text}")
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Collecting text candidate(s): none found"))

        if detail["references"]:
            self.stdout.write("")
            self.stdout.write("Parsed collected issue references:")

            for reference in detail["references"]:
                issue_summary = summarize_issue_numbers(reference["issue_numbers"])
                self.stdout.write(
                    f"- {reference['run_title']} "
                    f"({reference['start_year']}): "
                    f"{issue_summary}"
                )

                if reference["issue_expressions"]:
                    self.stdout.write(
                        "  source expressions: "
                        + ", ".join(reference["issue_expressions"])
                    )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Parsed collected issue references: none"))

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
                    return links.some((link) => (link.href || "").includes("/comics/collection"));
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

                function cardTextFor(element) {
                    let node = element;
                    let bestText = normalizeText(element.innerText || element.textContent || "");

                    for (let depth = 0; depth < 8 && node; depth += 1) {
                        const text = normalizeText(node.innerText || node.textContent || "");

                        if (
                            text &&
                            (
                                text.includes("ON SALE") ||
                                text.length > bestText.length
                            )
                        ) {
                            bestText = text;
                        }

                        if (text.includes("ON SALE")) {
                            break;
                        }

                        node = node.parentElement;
                    }

                    return bestText;
                }

                return elements
                    .map((element) => ({
                        text: normalizeText(element.innerText || element.textContent || ""),
                        href: element.href || "",
                        card_text: cardTextFor(element)
                    }))
                    .filter((item) => item.href && item.href.includes("/comics/collection"));
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
        paragraphs = page.eval_on_selector_all(
            "p",
            """
            elements => elements
                .map((element) => String(element.innerText || element.textContent || "").trim())
                .filter(Boolean)
            """,
        )

        detail = parse_collection_detail_text(
            text=text,
            paragraphs=paragraphs,
        )
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
    collections = []
    seen_urls = set()

    for link in rendered_calendar.get("links") or []:
        detail_url = clean_text(link.get("href"))

        if not detail_url or detail_url in seen_urls:
            continue

        title = clean_collection_title(link.get("text"))

        if not title:
            title = extract_collection_title_from_card_text(link.get("card_text"))

        published_date = parse_calendar_date_from_text(link.get("card_text"))

        if not published_date:
            published_date = parse_calendar_date_from_text(rendered_calendar.get("text"))

        collections.append(
            {
                "title": title or "[unknown collection title]",
                "published_date": published_date,
                "detail_url": detail_url,
                "card_text": clean_text(link.get("card_text")),
            }
        )
        seen_urls.add(detail_url)

    return sorted(collections, key=collection_sort_key)


def extract_collection_title_from_card_text(card_text):
    lines = normalize_page_lines(card_text)

    for line in lines:
        if normalize_text(line).startswith("ON SALE"):
            continue

        if line.lower() in {"new this week", "collections", "comics"}:
            continue

        if len(line) < 3:
            continue

        return clean_collection_title(line)

    return ""


def parse_collection_detail_text(*, text, paragraphs):
    description = extract_description_candidate(
        text=text,
        paragraphs=paragraphs,
    )
    collecting_texts = extract_collecting_texts(description)

    if not collecting_texts:
        collecting_texts = extract_collecting_texts(text)

    references = parse_collected_issue_references(collecting_texts)
    warnings = []

    if not description:
        warnings.append("No useful description paragraph was found.")

    if not collecting_texts:
        warnings.append("No explicit Collecting/Collects text was found.")

    if collecting_texts and not references:
        warnings.append("Collecting text was found, but no run/year/issue references were parsed.")

    if not collecting_texts and references:
        warnings.append("Issue references were parsed without explicit Collecting/Collects text.")

    confidence = determine_parse_confidence(
        collecting_texts=collecting_texts,
        references=references,
    )

    return {
        "read_attempted": False,
        "error": "",
        "description": description,
        "collecting_texts": collecting_texts,
        "references": references,
        "warnings": warnings,
        "confidence": confidence,
        "text_preview": text[:2500],
    }


def extract_description_candidate(*, text, paragraphs):
    candidates = []

    for paragraph in paragraphs or []:
        paragraph = clean_description(paragraph)

        if not paragraph:
            continue

        if should_skip_paragraph(paragraph):
            continue

        if len(paragraph) < 40:
            continue

        candidates.append(paragraph)

    collecting_candidates = [
        paragraph
        for paragraph in candidates
        if COLLECTING_START_RE.search(paragraph)
    ]

    if collecting_candidates:
        return "\n\n".join(collecting_candidates[:3])

    issue_reference_candidates = [
        paragraph
        for paragraph in candidates
        if RUN_TOKEN_RE.search(paragraph) and "#" in paragraph
    ]

    if issue_reference_candidates:
        return "\n\n".join(issue_reference_candidates[:3])

    if candidates:
        return "\n\n".join(candidates[:2])

    normalized_text = normalize_text(text)
    collecting_texts = extract_collecting_texts(normalized_text)

    if collecting_texts:
        return "\n\n".join(collecting_texts[:3])

    return ""


def extract_collecting_texts(value):
    value = normalize_text(value)

    if not value:
        return []

    matches = list(COLLECTING_START_RE.finditer(value))
    collecting_texts = []

    if matches:
        for index, match in enumerate(matches):
            start = match.start()
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(value)
            chunk = value[start:next_start]
            chunk = truncate_at_stop_marker(chunk)
            chunk = clean_description(chunk)

            if chunk:
                collecting_texts.append(chunk)

    if collecting_texts:
        return collecting_texts

    fallback_chunks = []

    for paragraph in split_into_candidate_sentences(value):
        if RUN_TOKEN_RE.search(paragraph) and "#" in paragraph:
            fallback_chunks.append(paragraph)

    return fallback_chunks


def parse_collected_issue_references(collecting_texts):
    reference_map = {}

    for collecting_text in collecting_texts:
        text = normalize_text(collecting_text)
        run_matches = list(RUN_TOKEN_RE.finditer(text))

        for index, match in enumerate(run_matches):
            run_title = clean_collected_run_title(match.group("title"))
            start_year = clean_text(match.group("year"))

            if not run_title or not start_year:
                continue

            next_start = run_matches[index + 1].start() if index + 1 < len(run_matches) else len(text)
            tail = text[match.end():next_start]
            issue_expressions, issue_numbers = parse_issue_references_from_tail(tail)

            if not issue_expressions:
                continue

            key = (normalize_title(run_title), start_year)
            existing = reference_map.setdefault(
                key,
                {
                    "run_title": run_title,
                    "start_year": start_year,
                    "issue_expressions": [],
                    "issue_numbers": [],
                },
            )

            for expression in issue_expressions:
                if expression not in existing["issue_expressions"]:
                    existing["issue_expressions"].append(expression)

            for issue_number in issue_numbers:
                if issue_number not in existing["issue_numbers"]:
                    existing["issue_numbers"].append(issue_number)

    references = list(reference_map.values())

    for reference in references:
        reference["issue_numbers"] = sorted(
            reference["issue_numbers"],
            key=issue_number_sort_key,
        )

    return sorted(
        references,
        key=lambda item: (
            normalize_title(item["run_title"]),
            item["start_year"],
        ),
    )


def parse_issue_references_from_tail(tail):
    tail = normalize_text(tail)
    tail = tail.replace("–", "-").replace("—", "-")

    hash_match = ISSUE_LIST_AFTER_HASH_RE.search(tail)

    if not hash_match:
        return [], []

    issue_list_text = hash_match.group("issue_list")
    issue_list_text = normalize_issue_list_text(issue_list_text)

    expressions = []
    issue_numbers = []

    for piece in issue_list_text.split(","):
        piece = clean_issue_expression(piece)

        if not piece:
            continue

        if not is_valid_issue_expression(piece):
            continue

        if piece not in expressions:
            expressions.append(piece)

        expanded_numbers = expand_issue_expression(piece)

        for issue_number in expanded_numbers:
            if issue_number not in issue_numbers:
                issue_numbers.append(issue_number)

    return expressions, issue_numbers


def normalize_issue_list_text(value):
    value = clean_text(value)
    value = value.replace("#", ",")
    value = re.sub(r"\s+and\s+#", ", #", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+and\s+([A-Za-z0-9])", r", \1", value, flags=re.IGNORECASE)

    stop_patterns = (
        r"\bmaterial\s+from\b",
        r"\bplus\b",
        r"\bwith\b",
        r"\bfeaturing\b",
        r"\bincluding\b",
        r"\balongside\b",
        r"\bbonus\b",
        r"\bvariant\b",
        r"\bcovers?\b",
        r"\bpages?\b",
        r"\bby\b",
    )

    for pattern in stop_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)

        if match:
            value = value[:match.start()]
            break

    value = value.split(".")[0]
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*,\s*", ",", value)
    return value.strip(" ,;")


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

    if value.lower() in {
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


def determine_parse_confidence(*, collecting_texts, references):
    if collecting_texts and references:
        return "high"

    if references:
        return "medium"

    return "none"


def truncate_at_stop_marker(value):
    earliest_index = None

    for marker in STOP_TEXT_MARKERS:
        index = value.find(marker)

        if index == -1:
            continue

        if earliest_index is None or index < earliest_index:
            earliest_index = index

    if earliest_index is None:
        return value

    return value[:earliest_index]


def split_into_candidate_sentences(value):
    value = normalize_text(value)
    pieces = re.split(r"(?<=[.!?])\s+", value)

    return [
        clean_description(piece)
        for piece in pieces
        if clean_description(piece)
    ]


def should_skip_paragraph(paragraph):
    normalized = paragraph.lower()

    for marker in PARAGRAPH_SKIP_MARKERS:
        if marker.lower() in normalized:
            return True

    if len(paragraph) > 2000:
        return True

    return False


def empty_collection_detail():
    return {
        "read_attempted": False,
        "error": "",
        "description": "",
        "collecting_texts": [],
        "references": [],
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


def format_collection_row(collection):
    published_date = collection.get("published_date")

    if published_date:
        published_date_text = published_date.isoformat()
    else:
        published_date_text = "unknown-date"

    return f"{collection['title']} [{published_date_text}]"