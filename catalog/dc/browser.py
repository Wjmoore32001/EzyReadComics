import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django.core.management.base import CommandError

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


DC_BROWSE_BASE_URL = "https://www.dc.com/comics"
DC_TIME_ZONE = "America/New_York"
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
TRAILING_YEAR_RE = re.compile(r"^(?P<title>.+?)\s+(?P<start_year>\d{4})$")


@dataclass
class DcBrowseResult:
    page_number: int
    requested_url: str
    final_url: str
    detail_links: list[dict] = field(default_factory=list)
    browse_marker_found: bool = False


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
class DcDetail:
    url: str
    final_url: str
    item_type: str = ""
    classification: str = ""
    title: str = ""
    issue_number: str = ""
    issue_key: str = ""
    description: str = ""
    series: DcSeriesInfo = field(default_factory=DcSeriesInfo)
    on_sale_date_text: str = ""
    credits: list[dict] = field(default_factory=list)
    more_from_series_links: list[dict] = field(default_factory=list)
    candidate_issue_links: list[dict] = field(default_factory=list)
    related_graphic_novel_links: list[dict] = field(default_factory=list)
    collection_parse: DcCollectionParse = field(default_factory=DcCollectionParse)
    series_scroll_clicks: int = 0
    scanned_more_from_series: bool = False


def ensure_playwright():
    if sync_playwright is None:
        raise CommandError(
            "Playwright is not installed. Run: "
            "pip install playwright && python -m playwright install chromium"
        )


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
        timezone_id=DC_TIME_ZONE,
    )


@contextmanager
def dc_browser_context(*, headed=False):
    ensure_playwright()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = build_browser_context(browser)

        try:
            yield context
        finally:
            context.close()
            browser.close()


def build_browse_url(page_number):
    if page_number <= 1:
        return DC_BROWSE_BASE_URL

    return f"{DC_BROWSE_BASE_URL}?page={page_number}"


def read_browse_page(*, context, page_number, timeout_ms=DEFAULT_TIMEOUT_MS):
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
        browse_data = extract_browse_detail_links(page)

        return DcBrowseResult(
            page_number=page_number,
            requested_url=requested_url,
            final_url=page.url,
            detail_links=browse_data["links"],
            browse_marker_found=browse_data["marker_found"],
        )
    finally:
        page.close()


def read_detail_page(
    *,
    context,
    url,
    timeout_ms=DEFAULT_TIMEOUT_MS,
    scan_more_from_series=True,
    known_more_from_series_links=None,
):
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

        if scan_more_from_series:
            more_links, scroll_clicks = collect_more_from_series_links(
                page=page,
                timeout_ms=timeout_ms,
            )
        else:
            more_links = clean_detail_links(known_more_from_series_links or [])
            scroll_clicks = 0

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
            series_title=series.title,
        )
        issue_number = extract_issue_number(title)
        issue_key = build_dc_issue_key(title=title, issue_number=issue_number)
        classification = classify_detail(
            item_type=item_type,
            issue_number=issue_number,
            series=series,
            more_links=more_links,
            collection_parse=collection_parse,
        )

        return DcDetail(
            url=url,
            final_url=page.url,
            item_type=item_type,
            classification=classification,
            title=title,
            issue_number=issue_number,
            issue_key=issue_key,
            description=description,
            series=series,
            on_sale_date_text=first_value(specs.get("On Sale Date")),
            credits=credits_from_label_block(talent),
            more_from_series_links=more_links,
            candidate_issue_links=candidate_issue_links,
            related_graphic_novel_links=related_graphic_novel_links,
            collection_parse=collection_parse,
            series_scroll_clicks=scroll_clicks,
            scanned_more_from_series=scan_more_from_series,
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


def parse_collection_relationship(*, description, candidate_issue_links, series_title=""):
    issue_numbers = parse_collected_issue_numbers(description)
    matched_links = []
    unmatched_numbers = []

    for number in issue_numbers:
        match = first_matching_issue_link(
            number=number,
            links=candidate_issue_links,
            series_title=series_title,
        )

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
            numbers.extend(str(number) for number in range(start, end + 1))
        else:
            numbers.extend(str(number) for number in range(start, end - 1, -1))

    for match in ISSUE_NUMBER_ANYWHERE_RE.finditer(description):
        numbers.append(clean_text(match.group("number")))

    return unique_list(numbers)


def first_matching_issue_link(*, number, links, series_title=""):
    number = normalize_issue_number(number)
    exact_series_matches = []
    normal_matches = []
    special_matches = []

    for link in links:
        link_number = normalize_issue_number(link_issue_number(link))

        if link_number != number:
            continue

        label = clean_item_label(link.get("label"))
        base_title = link_base_title(label)

        if series_title and normalize_title(base_title) == normalize_title(series_title):
            exact_series_matches.append(link)
        elif looks_like_special_issue_label(label):
            special_matches.append(link)
        else:
            normal_matches.append(link)

    if exact_series_matches:
        return exact_series_matches[0]

    if normal_matches:
        return normal_matches[0]

    if special_matches:
        return special_matches[0]

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


def build_dc_issue_key(*, title, issue_number):
    title = clean_text(title)
    issue_number = clean_text(issue_number)

    if not title or not issue_number:
        return issue_number

    base = re.sub(r"#\s*" + re.escape(issue_number) + r"\s*$", "", title, flags=re.IGNORECASE)
    base = re.sub(r"\(\d{4}\s*-?\s*\)", "", base)
    base = clean_text(base).strip(" :-")

    if not base:
        return issue_number

    if looks_like_special_issue_label(title):
        return f"{base} #{issue_number}"

    return issue_number


def parse_series(value):
    value = clean_text(value)

    if not value:
        return DcSeriesInfo()

    match = SERIES_RE.match(value)

    if match:
        return DcSeriesInfo(
            raw=value,
            title=clean_text(match.group("title")),
            start_year=clean_text(match.group("start_year")),
            end_year=clean_text(match.group("end_year")),
            is_ongoing=bool(match.group("ongoing")) and not clean_text(match.group("end_year")),
        )

    trailing_year_match = TRAILING_YEAR_RE.match(value)

    if trailing_year_match:
        return DcSeriesInfo(
            raw=value,
            title=clean_text(trailing_year_match.group("title")),
            start_year=clean_text(trailing_year_match.group("start_year")),
        )

    return DcSeriesInfo(raw=value, title=value)


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


def credits_from_label_block(talent):
    credits = []

    for role, names in talent.items():
        normalized_role = normalize_credit_role(role)

        if not normalized_role:
            continue

        for name in names:
            for split_name in split_credit_names(name):
                credits.append(
                    {
                        "role": normalized_role,
                        "name": split_name,
                    }
                )

    return unique_credits(credits)


def normalize_credit_role(value):
    key = clean_text(value).casefold().strip(" :")

    aliases = {
        "writer": "Writer",
        "written by": "Writer",
        "art by": "Artist",
        "artist": "Artist",
        "artists": "Artist",
        "pencils": "Penciller",
        "penciller": "Penciller",
        "pencillers": "Penciller",
        "inks": "Inker",
        "inker": "Inker",
        "inkers": "Inker",
        "colorist": "Colorist",
        "colorists": "Colorist",
        "colourist": "Colorist",
        "letterer": "Letterer",
        "letterers": "Letterer",
        "cover": "Cover Artist",
        "cover by": "Cover Artist",
        "cover artist": "Cover Artist",
        "editor": "Editor",
    }

    return aliases.get(key, clean_text(value).strip(" :"))


def split_credit_names(value):
    value = clean_text(value)

    if not value:
        return []

    parts = re.split(r"\s*,\s*|\s+and\s+", value)
    return unique_list([part for part in parts if clean_text(part)])


def unique_credits(credits):
    output = []
    seen = set()

    for credit in credits:
        role = clean_text(credit.get("role"))
        name = clean_text(credit.get("name"))
        key = (role.casefold(), name.casefold())

        if not role or not name or key in seen:
            continue

        seen.add(key)
        output.append({"role": role, "name": name})

    return output


def link_base_title(label):
    label = clean_item_label(label)
    issue_number = extract_issue_number(label)

    if issue_number:
        label = re.sub(r"#\s*" + re.escape(issue_number) + r"\s*$", "", label, flags=re.IGNORECASE)

    label = re.sub(r"\(\d{4}\s*-?\s*\)", "", label)
    return clean_text(label).strip(" :-")


def normalize_title(value):
    value = clean_text(value)
    value = re.sub(r"\(\d{4}\s*-?\s*\)", "", value)
    value = re.sub(r"[^A-Za-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().casefold()


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


def looks_like_special_issue_label(value):
    value = clean_text(value).casefold()
    return any(
        marker in value
        for marker in [
            " annual ",
            " annual #",
            " noir edition ",
            " noir edition #",
            ": ark ",
            ": ark m",
            " special ",
            " special #",
        ]
    )


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


def safe_wait_for_networkidle(*, page, timeout_ms):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass