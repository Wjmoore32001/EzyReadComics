import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


DC_BROWSE_BASE_URL = "https://www.dc.com/comics"
DEFAULT_TIMEOUT_MS = 45000

DETAIL_URL_RE = re.compile(
    r"^https?://(?:www\.)?dc\.com/(?:comics|graphic-novels)/[^/?#]+/[^/?#]+/?$",
    re.IGNORECASE,
)
ISSUE_NUMBER_RE = re.compile(r"#\s*(?P<number>\d+[A-Za-z]?)\s*$")
ISSUE_NUMBER_ANYWHERE_RE = re.compile(r"#\s*(?P<number>\d+[A-Za-z]?)")
COLLECTED_RANGE_RE = re.compile(
    r"#\s*(?P<start>\d+)\s*(?:-|–|—|to|through)\s*#?\s*(?P<end>\d+)",
    re.IGNORECASE,
)
SERIES_RE = re.compile(
    r"^(?P<title>.+?)\s*\((?P<start_year>\d{4})(?P<ongoing>\s*-\s*)?(?P<end_year>\d{4})?\)\s*$"
)


@dataclass
class DcBrowseResult:
    page_number: int
    requested_url: str
    final_url: str
    page_title: str
    text_length: int
    browse_marker_found: bool
    detail_links: list[dict] = field(default_factory=list)
    text_preview: str = ""


@dataclass
class DcSeriesInfo:
    raw: str = ""
    title: str = ""
    start_year: str = ""
    end_year: str = ""
    is_ongoing: bool = False


@dataclass
class DcCollectionParse:
    issue_numbers: list[str] = field(default_factory=list)
    matched_issue_links: list[dict] = field(default_factory=list)
    unmatched_issue_numbers: list[str] = field(default_factory=list)


@dataclass
class DcDetailResult:
    url: str
    final_url: str
    page_title: str
    text_length: int
    classification: str = ""
    item_type: str = ""
    title: str = ""
    issue_number: str = ""
    description: str = ""
    series: DcSeriesInfo = field(default_factory=DcSeriesInfo)
    on_sale_date: str = ""
    talent: dict = field(default_factory=dict)
    more_from_series_links: list[dict] = field(default_factory=list)
    candidate_issue_links: list[dict] = field(default_factory=list)
    related_graphic_novel_links: list[dict] = field(default_factory=list)
    collection_parse: DcCollectionParse = field(default_factory=DcCollectionParse)
    series_scroll_clicks: int = 0
    text_preview: str = ""


class Command(BaseCommand):
    help = (
        "Read-only Playwright probe for DC.com comics pages. "
        "Browse pages collect URLs only. Detail pages are treated as source of truth."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--page",
            type=int,
            default=1,
            help="Browse page number to start from. Default: 1.",
        )
        parser.add_argument(
            "--page-count",
            type=int,
            default=1,
            help="Number of browse pages to read by direct URL, starting from --page. Default: 1.",
        )
        parser.add_argument(
            "--detail-url",
            default="",
            help="Specific DC detail URL to probe. If omitted, detail URLs come from browse pages.",
        )
        parser.add_argument(
            "--detail-limit",
            type=int,
            default=1,
            help="Number of browse-collected detail URLs to probe. Use 0 to skip. Default: 1.",
        )
        parser.add_argument(
            "--no-related-graphic-novels",
            action="store_false",
            dest="follow_related_graphic_novels",
            help="Do not probe graphic novels found in More From This Series.",
        )
        parser.set_defaults(follow_related_graphic_novels=True)
        parser.add_argument(
            "--timeout",
            type=int,
            default=DEFAULT_TIMEOUT_MS,
            help=f"Playwright timeout in milliseconds. Default: {DEFAULT_TIMEOUT_MS}.",
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print rendered text previews.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print more parsed data.",
        )

    def handle(self, *args, **options):
        ensure_playwright()

        start_page = options["page"]
        page_count = options["page_count"]
        detail_url = clean_text(options["detail_url"])
        detail_limit = options["detail_limit"]
        follow_related_graphic_novels = options["follow_related_graphic_novels"]
        timeout_ms = options["timeout"]
        headed = options["headed"]
        raw = options["raw"]
        verbose = options["verbose"]

        if start_page < 1:
            raise CommandError("--page must be at least 1.")

        if page_count < 1:
            raise CommandError("--page-count must be at least 1.")

        if detail_limit < 0:
            raise CommandError("--detail-limit cannot be negative.")

        if timeout_ms < 1000:
            raise CommandError("--timeout must be at least 1000 milliseconds.")

        self.print_header(
            start_page=start_page,
            page_count=page_count,
            detail_url=detail_url,
            detail_limit=detail_limit,
            follow_related_graphic_novels=follow_related_graphic_novels,
            timeout_ms=timeout_ms,
            headed=headed,
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not headed)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 1800},
                locale="en-US",
                timezone_id="America/New_York",
            )

            try:
                browse_results = []

                for page_number in range(start_page, start_page + page_count):
                    result = read_browse_page(
                        context=context,
                        page_number=page_number,
                        timeout_ms=timeout_ms,
                    )
                    browse_results.append(result)
                    self.print_browse_result(result, raw=raw, verbose=verbose)

                detail_urls = collect_detail_urls_for_probe(
                    detail_url=detail_url,
                    detail_limit=detail_limit,
                    browse_results=browse_results,
                )

                if detail_urls:
                    self.stdout.write("")
                    self.stdout.write(self.style.SUCCESS("Detail page probes"))

                    probed_urls = {url.casefold() for url in detail_urls}

                    for url in detail_urls:
                        result = read_detail_page(
                            context=context,
                            url=url,
                            timeout_ms=timeout_ms,
                        )
                        self.print_detail_result(result, raw=raw, verbose=verbose)

                        if not follow_related_graphic_novels:
                            continue

                        for related_link in result.related_graphic_novel_links:
                            related_url = clean_text(related_link.get("href"))
                            related_key = related_url.casefold()

                            if not related_url or related_key in probed_urls:
                                continue

                            probed_urls.add(related_key)

                            self.stdout.write("")
                            self.stdout.write(self.style.SUCCESS("Related graphic novel probe"))

                            related_result = read_detail_page(
                                context=context,
                                url=related_url,
                                timeout_ms=timeout_ms,
                            )
                            self.print_detail_result(
                                related_result,
                                raw=raw,
                                verbose=verbose,
                            )
                else:
                    self.stdout.write("")
                    self.stdout.write(
                        self.style.WARNING(
                            "No detail pages were probed. Provide --detail-url or use --detail-limit above 0."
                        )
                    )

            finally:
                context.close()
                browser.close()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("DC site probe complete."))
        self.stdout.write("Catalog writes: 0")

    def print_header(
        self,
        *,
        start_page,
        page_count,
        detail_url,
        detail_limit,
        follow_related_graphic_novels,
        timeout_ms,
        headed,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("DC site probe"))
        self.stdout.write("Mode: read-only Playwright probe")
        self.stdout.write(f"Browse source: {DC_BROWSE_BASE_URL}")
        self.stdout.write(f"Start page: {start_page}")
        self.stdout.write(f"Browse pages to read by URL: {page_count}")
        self.stdout.write("Browse behavior: collect URLs only from Browse Comics section")
        self.stdout.write("Detail behavior: source of truth")
        self.stdout.write("Series year dash behavior: dash means ongoing; do not store dash as year text")
        self.stdout.write("More From This Series behavior: scroll until no new links/states are found")
        self.stdout.write("Collection range behavior: parse collected issues only from # tokens in description")
        self.stdout.write("Graphic novel behavior: collection vs one-shot is decided from detail page shape")
        self.stdout.write(
            "Related graphic novel probes: "
            + ("on" if follow_related_graphic_novels else "off")
        )
        self.stdout.write(f"Specific detail URL: {detail_url or 'none'}")
        self.stdout.write(f"Browse detail probe limit: {detail_limit}")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Timeout: {timeout_ms} ms")
        self.stdout.write("Filters changed: no")
        self.stdout.write("Catalog writes: 0")
        self.stdout.write("")

    def print_browse_result(self, result, *, raw, verbose):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Browse page {result.page_number}"))
        self.stdout.write(f"Requested URL: {result.requested_url}")
        self.stdout.write(f"Final URL: {result.final_url}")
        self.stdout.write(f"Page title: {result.page_title}")
        self.stdout.write(f"Rendered text length: {result.text_length}")
        self.stdout.write(
            f"Browse Comics marker found: {'yes' if result.browse_marker_found else 'no'}"
        )
        self.stdout.write(f"Browse detail URLs found: {len(result.detail_links)}")

        if result.detail_links:
            preview_count = len(result.detail_links) if verbose else min(len(result.detail_links), 10)
            self.stdout.write("Browse URL preview:")

            for link in result.detail_links[:preview_count]:
                label = link.get("label") or "[blank]"
                self.stdout.write(f"  - {label} -> {link.get('href')}")

        if raw:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Rendered browse text preview"))
            self.stdout.write(result.text_preview)

    def print_detail_result(self, result, *, raw, verbose):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(result.title or result.url))
        self.stdout.write(f"URL: {result.url}")
        self.stdout.write(f"Final URL: {result.final_url}")
        self.stdout.write(f"Page title: {result.page_title}")
        self.stdout.write(f"Rendered text length: {result.text_length}")
        self.stdout.write(f"Type: {result.item_type or 'not found'}")
        self.stdout.write(f"Classification: {result.classification or 'not found'}")
        self.stdout.write(f"Title: {result.title or 'not found'}")

        if result.issue_number:
            self.stdout.write(f"Issue number: {result.issue_number}")

        if result.series.raw:
            self.stdout.write(f"Series raw: {result.series.raw}")
            self.stdout.write(
                "Series parsed: "
                f"title={result.series.title or 'not found'} | "
                f"start_year={result.series.start_year or 'not found'} | "
                f"ongoing={'yes' if result.series.is_ongoing else 'no'}"
                + (f" | end_year={result.series.end_year}" if result.series.end_year else "")
            )
        else:
            self.stdout.write("Series: not found")

        self.stdout.write(f"On Sale Date: {result.on_sale_date or 'not found'}")
        self.stdout.write(
            "Description: "
            + (truncate_text(result.description, 240) if result.description else "not found")
        )

        if result.talent:
            self.stdout.write("Talent:")

            for role, names in result.talent.items():
                self.stdout.write(f"  - {role}: {', '.join(names)}")
        else:
            self.stdout.write("Talent: not found")

        self.stdout.write(f"More From This Series scroll clicks: {result.series_scroll_clicks}")
        self.stdout.write(f"More From This Series links: {len(result.more_from_series_links)}")

        link_preview_count = (
            len(result.more_from_series_links)
            if verbose
            else min(len(result.more_from_series_links), 20)
        )

        for link in result.more_from_series_links[:link_preview_count]:
            label = link.get("label") or "[blank]"
            self.stdout.write(f"  - {label} -> {link.get('href')}")

        self.stdout.write(f"Candidate issue links in series: {len(result.candidate_issue_links)}")

        if verbose and result.candidate_issue_links:
            for link in result.candidate_issue_links:
                number = link_issue_number(link) or "?"
                label = link.get("label") or "[blank]"
                self.stdout.write(f"  - #{number}: {label} -> {link.get('href')}")

        if result.related_graphic_novel_links:
            self.stdout.write(
                f"Related graphic novels in series: {len(result.related_graphic_novel_links)}"
            )

            for link in result.related_graphic_novel_links:
                label = link.get("label") or "[blank]"
                self.stdout.write(f"  - {label} -> {link.get('href')}")

        if result.collection_parse.issue_numbers:
            self.stdout.write(
                "Parsed collected issue numbers from description: "
                + ", ".join(result.collection_parse.issue_numbers)
            )
            self.stdout.write(
                f"Matched collected issue links: {len(result.collection_parse.matched_issue_links)}"
            )

            for link in result.collection_parse.matched_issue_links:
                number = link_issue_number(link) or "?"
                label = link.get("label") or "[blank]"
                self.stdout.write(f"  - #{number}: {label} -> {link.get('href')}")

            if result.collection_parse.unmatched_issue_numbers:
                self.stdout.write(
                    "Unmatched collected issue numbers: "
                    + ", ".join(result.collection_parse.unmatched_issue_numbers)
                )
        elif result.item_type == "GRAPHIC NOVEL":
            self.stdout.write("Parsed collected issue numbers from description: none")

        if raw:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Rendered detail text preview"))
            self.stdout.write(result.text_preview)


def ensure_playwright():
    if sync_playwright is None:
        raise CommandError(
            "Playwright is not installed in this environment. "
            "Run this command in the same environment that runs the Marvel Playwright commands."
        )


def build_browse_url(page_number):
    if page_number <= 1:
        return DC_BROWSE_BASE_URL

    return f"{DC_BROWSE_BASE_URL}?page={page_number}"


def read_browse_page(*, context, page_number, timeout_ms):
    page = context.new_page()

    try:
        requested_url = build_browse_url(page_number)
        page.goto(requested_url, wait_until="domcontentloaded", timeout=timeout_ms)
        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

        try:
            page.wait_for_function(
                """
                () => {
                    const text = document.body ? document.body.innerText : "";
                    return text.includes("Browse Comics");
                }
                """,
                timeout=timeout_ms,
            )
        except Exception:
            pass

        page.wait_for_timeout(750)

        text = page.locator("body").inner_text(timeout=timeout_ms)
        browse_data = extract_browse_detail_links(page)

        return DcBrowseResult(
            page_number=page_number,
            requested_url=requested_url,
            final_url=page.url,
            page_title=page.title(),
            text_length=len(text),
            browse_marker_found=browse_data["marker_found"],
            detail_links=browse_data["links"],
            text_preview=text[:5000],
        )
    finally:
        page.close()


def read_detail_page(*, context, url, timeout_ms):
    page = context.new_page()

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

        try:
            page.wait_for_function(
                """
                () => {
                    const text = document.body ? document.body.innerText : "";
                    return text.includes("SPECS") ||
                           text.includes("Talent") ||
                           text.includes("MORE FROM THIS SERIES") ||
                           text.includes("GRAPHIC NOVEL") ||
                           text.includes("COMIC BOOK");
                }
                """,
                timeout=timeout_ms,
            )
        except Exception:
            pass

        page.wait_for_timeout(750)

        more_links, scroll_clicks = collect_more_from_series_links(
            page=page,
            timeout_ms=timeout_ms,
        )

        text = page.locator("body").inner_text(timeout=timeout_ms)
        lines = normalize_lines(text)

        item_type = extract_item_type(lines)
        title = extract_detail_title(lines=lines, item_type=item_type)
        description = extract_description(lines=lines, item_type=item_type, title=title)
        specs = extract_label_block(
            lines=lines,
            start_marker="SPECS",
            end_markers={"Starring", "MORE FROM THIS SERIES"},
        )
        talent = extract_label_block(
            lines=lines,
            start_marker="Talent",
            end_markers={"SPECS"},
        )
        series = parse_series(first_value(specs.get("Series")))
        candidate_issue_links = [
            link for link in more_links if is_comic_issue_url(link.get("href"))
        ]
        related_graphic_novel_links = [
            link for link in more_links if is_graphic_novel_url(link.get("href"))
        ]
        collection_parse = parse_collection_relationship(
            description=description,
            candidate_issue_links=candidate_issue_links,
        )
        issue_number = extract_issue_number(title)
        classification = classify_detail(
            item_type=item_type,
            issue_number=issue_number,
            series=series,
            more_links=more_links,
            collection_parse=collection_parse,
        )

        return DcDetailResult(
            url=url,
            final_url=page.url,
            page_title=page.title(),
            text_length=len(text),
            classification=classification,
            item_type=item_type,
            title=title,
            issue_number=issue_number,
            description=description,
            series=series,
            on_sale_date=first_value(specs.get("On Sale Date")),
            talent=talent,
            more_from_series_links=more_links,
            candidate_issue_links=candidate_issue_links,
            related_graphic_novel_links=related_graphic_novel_links,
            collection_parse=collection_parse,
            series_scroll_clicks=scroll_clicks,
            text_preview=text[:5000],
        )
    finally:
        page.close()


def extract_browse_detail_links(page):
    try:
        result = page.evaluate(
            """
            () => {
                function normalizeText(value) {
                    return String(value || "")
                        .replace(/\\u00a0/g, " ")
                        .replace(/[ \\t]+/g, " ")
                        .replace(/\\n[ \\t]+/g, "\\n")
                        .replace(/[ \\t]+\\n/g, "\\n")
                        .trim();
                }

                function isVisible(element) {
                    const style = window.getComputedStyle(element);

                    if (!style || style.display === "none" || style.visibility === "hidden") {
                        return false;
                    }

                    const rect = element.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                function isDcDetailUrl(href) {
                    try {
                        const url = new URL(href);

                        if (!["dc.com", "www.dc.com"].includes(url.hostname)) {
                            return false;
                        }

                        const parts = url.pathname.split("/").filter(Boolean);

                        if (parts.length !== 3) {
                            return false;
                        }

                        return parts[0] === "comics" || parts[0] === "graphic-novels";
                    } catch {
                        return false;
                    }
                }

                function linkLabel(link) {
                    const image = link.querySelector("img");
                    const text = normalizeText(link.innerText || link.textContent || "");
                    const imageAlt = image ? normalizeText(image.getAttribute("alt") || "") : "";
                    const aria = normalizeText(link.getAttribute("aria-label") || "");
                    const title = normalizeText(link.getAttribute("title") || "");

                    return text || imageAlt || aria || title;
                }

                const marker = Array.from(
                    document.querySelectorAll("h1,h2,h3,h4,h5,h6,p,span")
                ).find((element) => {
                    if (!isVisible(element)) {
                        return false;
                    }

                    const text = normalizeText(element.innerText || element.textContent || "");

                    if (text.length > 80) {
                        return false;
                    }

                    return /^Browse Comics(?:\\s*\\(|$)/i.test(text);
                });

                if (!marker) {
                    return {marker_found: false, links: []};
                }

                const links = Array.from(document.querySelectorAll("a"))
                    .filter((link) => {
                        if (!isDcDetailUrl(link.href || "")) {
                            return false;
                        }

                        return Boolean(
                            marker.compareDocumentPosition(link) &
                            Node.DOCUMENT_POSITION_FOLLOWING
                        );
                    })
                    .map((link) => ({
                        label: linkLabel(link),
                        href: link.href || ""
                    }));

                return {marker_found: true, links};
            }
            """
        )
    except Exception:
        return {"marker_found": False, "links": []}

    return {
        "marker_found": bool(result.get("marker_found")),
        "links": clean_detail_links(result.get("links") or []),
    }


def collect_more_from_series_links(*, page, timeout_ms):
    links = []
    seen_hrefs = set()
    seen_states = set()
    clicks = 0

    def add_links():
        added = 0

        for link in extract_more_from_series_links(page):
            href = clean_text(link.get("href"))

            if not href:
                continue

            key = href.casefold()

            if key in seen_hrefs:
                continue

            seen_hrefs.add(key)
            links.append(link)
            added += 1

        return added

    add_links()
    state = get_more_from_series_visible_state(page)

    if state:
        seen_states.add(state)

    while True:
        clicked = click_more_from_series_next(page)

        if not clicked:
            break

        clicks += 1
        safe_wait_for_networkidle(page=page, timeout_ms=min(timeout_ms, 10000))
        page.wait_for_timeout(400)

        added = add_links()
        state = get_more_from_series_visible_state(page)

        if not state and added == 0:
            break

        if state in seen_states and added == 0:
            break

        if state:
            seen_states.add(state)

    return links, clicks


def extract_more_from_series_links(page):
    try:
        links = page.evaluate(
            """
            () => {
                function normalizeText(value) {
                    return String(value || "")
                        .replace(/\\u00a0/g, " ")
                        .replace(/[ \\t]+/g, " ")
                        .replace(/\\n[ \\t]+/g, "\\n")
                        .replace(/[ \\t]+\\n/g, "\\n")
                        .trim();
                }

                function isVisible(element) {
                    const style = window.getComputedStyle(element);

                    if (!style || style.display === "none" || style.visibility === "hidden") {
                        return false;
                    }

                    const rect = element.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                function isDcDetailUrl(href) {
                    try {
                        const url = new URL(href);

                        if (!["dc.com", "www.dc.com"].includes(url.hostname)) {
                            return false;
                        }

                        const parts = url.pathname.split("/").filter(Boolean);

                        if (parts.length !== 3) {
                            return false;
                        }

                        return parts[0] === "comics" || parts[0] === "graphic-novels";
                    } catch {
                        return false;
                    }
                }

                function linkLabel(link) {
                    const image = link.querySelector("img");
                    const text = normalizeText(link.innerText || link.textContent || "");
                    const imageAlt = image ? normalizeText(image.getAttribute("alt") || "") : "";
                    const aria = normalizeText(link.getAttribute("aria-label") || "");
                    const title = normalizeText(link.getAttribute("title") || "");

                    return text || imageAlt || aria || title;
                }

                const marker = findMoreFromSeriesMarker();

                if (!marker) {
                    return [];
                }

                const markerY = marker.getBoundingClientRect().top + window.scrollY;

                return Array.from(document.querySelectorAll("a"))
                    .filter((link) => {
                        if (!isDcDetailUrl(link.href || "")) {
                            return false;
                        }

                        const rect = link.getBoundingClientRect();
                        const y = rect.top + window.scrollY;

                        return y >= markerY - 10;
                    })
                    .map((link) => ({
                        label: linkLabel(link),
                        href: link.href || ""
                    }));

                function findMoreFromSeriesMarker() {
                    return Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6,p,span,div"))
                        .find((element) => {
                            if (!isVisible(element)) {
                                return false;
                            }

                            const text = normalizeText(element.innerText || element.textContent || "");

                            if (text.length > 120) {
                                return false;
                            }

                            return /^MORE FROM THIS SERIES$/i.test(text);
                        });
                }
            }
            """
        )
    except Exception:
        return []

    return clean_detail_links(links)


def get_more_from_series_visible_state(page):
    try:
        return clean_text(
            page.evaluate(
                """
                () => {
                    function normalizeText(value) {
                        return String(value || "")
                            .replace(/\\u00a0/g, " ")
                            .replace(/[ \\t]+/g, " ")
                            .trim();
                    }

                    function isVisible(element) {
                        const style = window.getComputedStyle(element);

                        if (!style || style.display === "none" || style.visibility === "hidden") {
                            return false;
                        }

                        const rect = element.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    }

                    function isDcDetailUrl(href) {
                        try {
                            const url = new URL(href);

                            if (!["dc.com", "www.dc.com"].includes(url.hostname)) {
                                return false;
                            }

                            const parts = url.pathname.split("/").filter(Boolean);

                            if (parts.length !== 3) {
                                return false;
                            }

                            return parts[0] === "comics" || parts[0] === "graphic-novels";
                        } catch {
                            return false;
                        }
                    }

                    const marker = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6,p,span,div"))
                        .find((element) => {
                            if (!isVisible(element)) {
                                return false;
                            }

                            const text = normalizeText(element.innerText || element.textContent || "");

                            if (text.length > 120) {
                                return false;
                            }

                            return /^MORE FROM THIS SERIES$/i.test(text);
                        });

                    if (!marker) {
                        return "";
                    }

                    const markerY = marker.getBoundingClientRect().top + window.scrollY;

                    const visibleHrefs = Array.from(document.querySelectorAll("a"))
                        .filter((link) => {
                            if (!isDcDetailUrl(link.href || "")) {
                                return false;
                            }

                            if (!isVisible(link)) {
                                return false;
                            }

                            const rect = link.getBoundingClientRect();
                            const y = rect.top + window.scrollY;

                            return y >= markerY - 10 && y <= markerY + 1200;
                        })
                        .map((link) => link.href)
                        .join("|");

                    const movingParts = Array.from(document.querySelectorAll("*"))
                        .filter((element) => {
                            const rect = element.getBoundingClientRect();
                            const y = rect.top + window.scrollY;

                            return y >= markerY - 10 && y <= markerY + 1200;
                        })
                        .map((element) => {
                            const style = window.getComputedStyle(element);
                            const transform = style ? style.transform : "";
                            const left = Math.round(element.getBoundingClientRect().left);
                            const scrollLeft = element.scrollLeft || 0;

                            if (!transform || transform === "none") {
                                return "";
                            }

                            return `${element.tagName}:${left}:${scrollLeft}:${transform}`;
                        })
                        .filter(Boolean)
                        .join("|");

                    return `${visibleHrefs}::${movingParts}`;
                }
                """
            )
        )
    except Exception:
        return ""


def click_more_from_series_next(page):
    try:
        return bool(
            page.evaluate(
                """
                () => {
                    function normalizeText(value) {
                        return String(value || "")
                            .replace(/\\u00a0/g, " ")
                            .replace(/[ \\t]+/g, " ")
                            .trim();
                    }

                    function isVisible(element) {
                        const style = window.getComputedStyle(element);

                        if (!style || style.display === "none" || style.visibility === "hidden") {
                            return false;
                        }

                        const rect = element.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    }

                    function isDisabled(element) {
                        return Boolean(
                            element.disabled ||
                            element.getAttribute("aria-disabled") === "true" ||
                            element.classList.contains("disabled")
                        );
                    }

                    const marker = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6,p,span,div"))
                        .find((element) => {
                            if (!isVisible(element)) {
                                return false;
                            }

                            const text = normalizeText(element.innerText || element.textContent || "");

                            if (text.length > 120) {
                                return false;
                            }

                            return /^MORE FROM THIS SERIES$/i.test(text);
                        });

                    if (!marker) {
                        return false;
                    }

                    marker.scrollIntoView({ block: "center", inline: "nearest" });

                    const markerY = marker.getBoundingClientRect().top + window.scrollY;
                    const candidates = Array.from(document.querySelectorAll("button,[role='button'],a"))
                        .map((element) => {
                            const rect = element.getBoundingClientRect();
                            const y = rect.top + window.scrollY;
                            const blob = [
                                element.innerText || element.textContent || "",
                                element.getAttribute("aria-label") || "",
                                element.getAttribute("title") || "",
                                element.getAttribute("class") || ""
                            ].join(" ");

                            return {
                                element,
                                rect,
                                y,
                                blob: normalizeText(blob)
                            };
                        })
                        .filter((item) => {
                            if (item.y < markerY - 10 || item.y > markerY + 1200) {
                                return false;
                            }

                            if (!isVisible(item.element) || isDisabled(item.element)) {
                                return false;
                            }

                            return true;
                        });

                    const explicitNext = candidates
                        .filter((item) => /next|right|arrow|swiper-button-next|slick-next/i.test(item.blob))
                        .sort((a, b) => {
                            if (Math.abs(a.rect.top - b.rect.top) > 20) {
                                return a.rect.top - b.rect.top;
                            }

                            return b.rect.left - a.rect.left;
                        });

                    const fallbackRightSide = candidates
                        .filter((item) => item.rect.left > window.innerWidth * 0.5)
                        .sort((a, b) => {
                            if (Math.abs(a.rect.top - b.rect.top) > 20) {
                                return a.rect.top - b.rect.top;
                            }

                            return b.rect.left - a.rect.left;
                        });

                    const target = explicitNext[0] || fallbackRightSide[0];

                    if (!target) {
                        return false;
                    }

                    target.element.click();
                    return true;
                }
                """
            )
        )
    except Exception:
        return False


def parse_collection_relationship(*, description, candidate_issue_links):
    issue_numbers = parse_collected_issue_numbers(description)
    matched_links = []
    unmatched_numbers = []

    for number in issue_numbers:
        match = first_matching_issue_link(number=number, links=candidate_issue_links)

        if match:
            matched_links.append(match)
        else:
            unmatched_numbers.append(number)

    return DcCollectionParse(
        issue_numbers=issue_numbers,
        matched_issue_links=matched_links,
        unmatched_issue_numbers=unmatched_numbers,
    )


def parse_collected_issue_numbers(description):
    description = clean_text(description)
    numbers = []

    for match in COLLECTED_RANGE_RE.finditer(description):
        start = int(match.group("start"))
        end = int(match.group("end"))

        if start <= end:
            for number in range(start, end + 1):
                numbers.append(str(number))
        else:
            for number in range(start, end - 1, -1):
                numbers.append(str(number))

    for match in ISSUE_NUMBER_ANYWHERE_RE.finditer(description):
        numbers.append(clean_text(match.group("number")))

    return unique_list(numbers)


def first_matching_issue_link(*, number, links):
    number = normalize_issue_number(number)

    for link in links:
        if normalize_issue_number(link_issue_number(link)) == number:
            return link

    return None


def link_issue_number(link):
    label = clean_item_label(link.get("label"))
    href = clean_text(link.get("href"))

    label_match = ISSUE_NUMBER_RE.search(label)

    if label_match:
        return clean_text(label_match.group("number"))

    parsed = urlparse(href)
    parts = [part for part in parsed.path.split("/") if part]

    if not parts:
        return ""

    slug = parts[-1]
    slug_match = re.search(r"-(?P<number>\d+[A-Za-z]?)$", slug)

    if slug_match:
        return clean_text(slug_match.group("number"))

    return ""


def classify_detail(*, item_type, issue_number, series, more_links, collection_parse):
    if item_type == "COMIC BOOK":
        if issue_number:
            return "issue"

        return "comic_book_needs_review"

    if item_type == "GRAPHIC NOVEL":
        if collection_parse.issue_numbers and series.raw:
            return "collected_volume"

        if not series.raw and not more_links and not collection_parse.issue_numbers:
            return "standalone_graphic_novel_or_one_shot"

        if series.raw and not collection_parse.issue_numbers:
            return "graphic_novel_series_item_needs_review"

        return "graphic_novel_needs_review"

    return "unknown"


def clean_detail_links(raw_links):
    links = []
    seen = set()

    for link in raw_links:
        href = clean_text(link.get("href"))
        label = clean_item_label(link.get("label"))

        if not href or not DETAIL_URL_RE.match(href):
            continue

        if not label:
            label = title_from_url(href)

        key = href.casefold()

        if key in seen:
            continue

        seen.add(key)
        links.append({"label": label, "href": href})

    return links


def collect_detail_urls_for_probe(*, detail_url, detail_limit, browse_results):
    if detail_url:
        return [detail_url]

    if detail_limit == 0:
        return []

    urls = []

    for result in browse_results:
        for link in result.detail_links:
            href = clean_text(link.get("href"))

            if not href or href in urls:
                continue

            urls.append(href)

            if len(urls) >= detail_limit:
                return urls

    return urls


def extract_item_type(lines):
    for line in lines:
        normalized = line.upper()

        if normalized in {"COMIC BOOK", "GRAPHIC NOVEL"}:
            return normalized

    return ""


def extract_detail_title(*, lines, item_type):
    if item_type:
        for index, line in enumerate(lines):
            if line.upper() != item_type:
                continue

            for next_line in lines[index + 1:]:
                if is_noise_line(next_line):
                    continue

                return next_line.lstrip("#").strip()

    return ""


def extract_issue_number(title):
    match = ISSUE_NUMBER_RE.search(clean_text(title))

    if not match:
        return ""

    return clean_text(match.group("number"))


def parse_series(value):
    value = clean_text(value)

    if not value:
        return DcSeriesInfo()

    match = SERIES_RE.match(value)

    if not match:
        return DcSeriesInfo(raw=value, title=value)

    return DcSeriesInfo(
        raw=value,
        title=clean_text(match.group("title")),
        start_year=clean_text(match.group("start_year")),
        end_year=clean_text(match.group("end_year")),
        is_ongoing=bool(match.group("ongoing")) and not clean_text(match.group("end_year")),
    )


def extract_description(*, lines, item_type, title):
    start_index = None

    if title:
        title_key = normalize_key(title)

        for index, line in enumerate(lines):
            if normalize_key(line.lstrip("#").strip()) == title_key:
                start_index = index + 1
                break

    if start_index is None and item_type:
        for index, line in enumerate(lines):
            if line.upper() == item_type:
                start_index = index + 1
                break

    if start_index is None:
        return ""

    description_lines = []

    for line in lines[start_index:]:
        if is_description_stop_line(line):
            break

        if is_noise_line(line):
            continue

        if title and normalize_key(line.lstrip("#").strip()) == normalize_key(title):
            continue

        description_lines.append(line)

    return clean_text(" ".join(description_lines))


def extract_label_block(*, lines, start_marker, end_markers):
    start_index = find_marker_index(lines=lines, marker=start_marker)

    if start_index is None:
        return {}

    end_index = len(lines)

    for marker in end_markers:
        marker_index = find_marker_index(
            lines=lines,
            marker=marker,
            start=start_index + 1,
        )

        if marker_index is not None:
            end_index = min(end_index, marker_index)

    block = {}
    current_label = ""

    for line in lines[start_index + 1:end_index]:
        label = label_from_line(line)

        if label:
            current_label = label
            block.setdefault(current_label, [])
            continue

        if not current_label or is_noise_line(line):
            continue

        block[current_label].append(line)

    return {
        label: unique_list(values)
        for label, values in block.items()
        if values
    }


def find_marker_index(*, lines, marker, start=0):
    marker_key = normalize_key(marker)

    for index in range(start, len(lines)):
        if normalize_key(lines[index]) == marker_key:
            return index

    return None


def label_from_line(line):
    line = clean_text(line)

    if not line.endswith(":"):
        return ""

    label = line.strip(":").strip()

    if not label or len(label) > 80:
        return ""

    return label


def is_comic_issue_url(value):
    return "/comics/" in clean_text(value)


def is_graphic_novel_url(value):
    return "/graphic-novels/" in clean_text(value)


def is_description_stop_line(line):
    return normalize_key(line) in {
        "join dc universe infinite",
        "find a comic shop near you",
        "talent",
        "specs",
        "starring",
        "more from this series",
    }


def is_noise_line(line):
    return normalize_key(line) in {
        "",
        "sign up",
        "log in",
        "search",
        "comics",
        "characters",
        "movies tv",
        "games",
        "news",
        "video",
        "shop",
        "community",
        "more",
    }


def title_from_url(url):
    parsed = urlparse(clean_text(url))
    parts = [part for part in parsed.path.split("/") if part]

    if not parts:
        return ""

    return clean_item_label(parts[-1].replace("-", " ").title())


def normalize_lines(text):
    lines = []

    for line in str(text or "").splitlines():
        line = clean_text(line)

        if line:
            lines.append(line)

    return lines


def clean_item_label(value):
    value = clean_text(value)
    value = re.sub(r"^Image:\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_text(value):
    value = str(value or "")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\s+\n", "\n", value)
    value = re.sub(r"\n\s+", "\n", value)
    return value.strip()


def normalize_key(value):
    value = clean_text(value)
    value = value.replace("&", " and ")
    value = re.sub(r"[^A-Za-z0-9#]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().casefold()


def normalize_issue_number(value):
    return clean_text(value).casefold()


def first_value(values):
    if not values:
        return ""

    return values[0]


def unique_list(values):
    output = []
    seen = set()

    for value in values:
        value = clean_text(value)

        if not value:
            continue

        key = value.casefold()

        if key in seen:
            continue

        seen.add(key)
        output.append(value)

    return output


def truncate_text(value, max_length):
    value = clean_text(value)

    if len(value) <= max_length:
        return value

    return value[: max_length - 3].rstrip() + "..."


def safe_wait_for_networkidle(*, page, timeout_ms):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass