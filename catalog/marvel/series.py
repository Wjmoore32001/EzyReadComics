import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from catalog.marvel.browser import (
    marvel_browser_context,
    safe_wait_for_networkidle,
)
from catalog.marvel.text import (
    canonical_issue_number,
    clean_text,
    issue_number_sort_key,
)
from catalog.marvel.urls import (
    parse_marvel_issue_url,
    parse_marvel_series_url,
)


ISSUE_PAGE_SERIES_URL_ATTEMPTS = 3
SERIES_PAGE_READ_ATTEMPTS = 3
RETRY_SETTLE_MS = 500

ISSUE_TEXT_RE = re.compile(
    r"(?P<title>[A-Z0-9][^\n\r]{1,220}?)\s*"
    r"\((?P<year>\d{4})\)\s*"
    r"#(?P<issue>[A-Z0-9][A-Z0-9.\-/]*)",
    re.IGNORECASE,
)

SERIES_YEAR_RE = re.compile(
    r"\((?P<start_year>\d{4})(?:\s*-\s*(?P<end_value>Present|\d{4}))?\)",
    re.IGNORECASE,
)


@dataclass
class MarvelSeriesIssue:
    run_title: str
    start_year: str
    issue_number: str
    detail_url: str
    marvel_issue_id: str = ""
    issue_slug: str = ""


@dataclass
class MarvelSeries:
    title: str = ""
    start_year: str = ""
    end_value: str = ""
    status: str = "unknown"
    url: str = ""
    marvel_series_id: str = ""
    series_slug: str = ""
    raw_issue_link_count: int = 0
    load_more_clicks: int = 0
    issues: list[MarvelSeriesIssue] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def read_series_from_issue_url_with_browser(*, issue_url, headed=False, timeout_ms=45000):
    with marvel_browser_context(headed=headed) as context:
        series_url = read_issue_page_series_url(
            context=context,
            issue_url=issue_url,
            timeout_ms=timeout_ms,
        )

        if not series_url:
            return MarvelSeries(
                errors=["No Back to Series URL found on issue page."],
            )

        return read_series_page(
            context=context,
            series_url=series_url,
            timeout_ms=timeout_ms,
        )


def read_series_page_with_browser(*, series_url, headed=False, timeout_ms=45000):
    with marvel_browser_context(headed=headed) as context:
        return read_series_page(
            context=context,
            series_url=series_url,
            timeout_ms=timeout_ms,
        )


def read_issue_page_series_url(*, context, issue_url, timeout_ms):
    issue_url = clean_text(issue_url)

    if not issue_url:
        return ""

    for attempt in range(ISSUE_PAGE_SERIES_URL_ATTEMPTS):
        series_url = read_issue_page_series_url_once(
            context=context,
            issue_url=issue_url,
            timeout_ms=timeout_ms,
        )

        if series_url:
            return series_url

        if attempt < ISSUE_PAGE_SERIES_URL_ATTEMPTS - 1:
            settle_browser_context(context=context)

    return ""


def read_issue_page_series_url_once(*, context, issue_url, timeout_ms):
    page = None

    try:
        page = context.new_page()

        response = page.goto(
            issue_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        status = response.status if response else None

        if status and status >= 400:
            return ""

        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

        try:
            page.wait_for_function(
                """
                () => {
                    return Array.from(document.querySelectorAll("a"))
                        .some((link) => (link.href || "").includes("/comics/series/"));
                }
                """,
                timeout=timeout_ms,
            )
        except Exception:
            pass

        page.wait_for_timeout(500)

        return extract_back_to_series_url(page)

    except Exception:
        return ""

    finally:
        safe_close_page(page)


def extract_back_to_series_url(page):
    links = page.eval_on_selector_all(
        "a",
        """
        elements => elements
            .map((element) => ({
                text: (element.innerText || element.textContent || "").trim(),
                href: element.href || "",
                aria: element.getAttribute("aria-label") || ""
            }))
            .filter((item) => item.href.includes("/comics/series/"))
        """,
    )

    for link in links:
        text = clean_text(link.get("text"))
        aria = clean_text(link.get("aria"))

        if "back to series" in text.casefold() or "back to series" in aria.casefold():
            return clean_text(link.get("href"))

    if links:
        return clean_text(links[0].get("href"))

    return ""


def read_series_page(*, context, series_url, timeout_ms):
    series_url = clean_text(series_url)
    parsed_series_url = parse_marvel_series_url(series_url)

    series = MarvelSeries(
        url=series_url,
        marvel_series_id=parsed_series_url.marvel_id if parsed_series_url else "",
        series_slug=parsed_series_url.slug if parsed_series_url else "",
    )

    if not series_url:
        series.errors.append("Missing series URL.")
        return series

    last_error = ""

    for attempt in range(SERIES_PAGE_READ_ATTEMPTS):
        read_series_page_once(
            context=context,
            series=series,
            series_url=series_url,
            timeout_ms=timeout_ms,
        )

        if not series.errors:
            return series

        last_error = series.errors[-1]
        series.errors.clear()

        if attempt < SERIES_PAGE_READ_ATTEMPTS - 1:
            settle_browser_context(context=context)

    series.errors.append(last_error or "Series page read failed.")
    return series


def read_series_page_once(*, context, series, series_url, timeout_ms):
    page = None

    try:
        page = context.new_page()

        response = page.goto(
            series_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        status = response.status if response else None

        if status and status >= 400:
            series.errors.append(f"Series page returned HTTP {status}.")
            return

        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

        try:
            page.wait_for_function(
                """
                () => {
                    const text = document.body ? document.body.innerText : "";
                    return text.includes("Showing") ||
                           text.includes("Load More") ||
                           Array.from(document.querySelectorAll("a"))
                               .some((link) => (link.href || "").includes("/comics/issue/"));
                }
                """,
                timeout=timeout_ms,
            )
        except Exception:
            pass

        page.wait_for_timeout(750)

        series.load_more_clicks = click_load_more_until_exhausted(
            page=page,
            timeout_ms=timeout_ms,
        )

        text = page.locator("body").inner_text(timeout=timeout_ms)
        title, start_year, end_value = parse_series_title_years(text=text)

        series.title = title
        series.start_year = start_year
        series.end_value = end_value
        series.status = derive_status_from_series_end_value(end_value)
        series.raw_issue_link_count = count_issue_links(page)
        series.issues = extract_series_issues_from_page(page)

    except Exception as exc:
        series.errors.append(f"Series page read failed: {exc}")

    finally:
        safe_close_page(page)


def click_load_more_until_exhausted(*, page, timeout_ms):
    clicks = 0
    previous_count = count_issue_links(page)

    while True:
        clicked = click_load_more_once(page)

        if not clicked:
            break

        clicks += 1

        try:
            page.wait_for_function(
                """
                previousCount => {
                    return Array.from(document.querySelectorAll("a"))
                        .filter((link) => (link.href || "").includes("/comics/issue/"))
                        .length > previousCount;
                }
                """,
                arg=previous_count,
                timeout=min(timeout_ms, 15000),
            )
        except Exception:
            pass

        safe_wait_for_networkidle(page=page, timeout_ms=min(timeout_ms, 15000))

        try:
            page.wait_for_timeout(750)
        except Exception:
            break

        current_count = count_issue_links(page)

        if current_count <= previous_count:
            break

        previous_count = current_count

        if clicks >= 50:
            break

    return clicks


def click_load_more_once(page):
    locators = [
        page.get_by_role("button", name=re.compile(r"load more", re.IGNORECASE)),
        page.get_by_text(re.compile(r"load more", re.IGNORECASE)),
    ]

    for locator in locators:
        try:
            count = locator.count()

            for index in range(count):
                item = locator.nth(index)

                if not item.is_visible():
                    continue

                item.click(timeout=5000)
                return True
        except Exception:
            continue

    return False


def count_issue_links(page):
    try:
        return page.eval_on_selector_all(
            "a",
            """
            elements => elements
                .filter((element) => (element.href || "").includes("/comics/issue/"))
                .length
            """,
        )
    except Exception:
        return 0


def extract_series_issues_from_page(page):
    links = page.eval_on_selector_all(
        "a",
        """
        elements => elements
            .map((element) => ({
                text: (element.innerText || element.textContent || "").trim(),
                href: element.href || ""
            }))
            .filter((item) => item.href.includes("/comics/issue/"))
        """,
    )

    by_issue_id = {}
    by_fallback_key = {}

    for link in links:
        if not is_uppercase_issue_text(link.get("text")):
            continue

        parsed = parse_series_issue_link(link)

        if parsed is None:
            continue

        if parsed.marvel_issue_id:
            by_issue_id[parsed.marvel_issue_id] = parsed
            continue

        fallback_key = (
            parsed.detail_url,
            parsed.run_title,
            parsed.start_year,
            parsed.issue_number,
        )
        by_fallback_key[fallback_key] = parsed

    issues = list(by_issue_id.values()) + list(by_fallback_key.values())

    return sorted(
        issues,
        key=lambda issue: issue_number_sort_key(issue.issue_number),
    )


def parse_series_issue_link(link):
    text = clean_text(link.get("text"))
    href = clean_text(link.get("href"))

    if not href:
        return None

    match = ISSUE_TEXT_RE.search(text)

    if match:
        run_title = clean_text(match.group("title"))
        start_year = clean_text(match.group("year"))
        issue_number = canonical_issue_number(match.group("issue"))
    else:
        parsed_url = parse_marvel_issue_url(href)

        if parsed_url is None:
            return None

        run_title = parsed_url.run_title
        start_year = parsed_url.start_year
        issue_number = parsed_url.issue_number

    parsed_url = parse_marvel_issue_url(href)

    return MarvelSeriesIssue(
        run_title=run_title,
        start_year=start_year,
        issue_number=issue_number,
        detail_url=href,
        marvel_issue_id=parsed_url.marvel_id if parsed_url else "",
        issue_slug=parsed_url.slug if parsed_url else clean_text(unquote(href.rsplit("/", 1)[-1])),
    )


def is_uppercase_issue_text(value):
    value = clean_text(value)

    if not value:
        return False

    match = ISSUE_TEXT_RE.search(value)

    if not match:
        return False

    title = clean_text(match.group("title"))

    if not re.search(r"[A-Za-z]", title):
        return False

    return title == title.upper()


def parse_series_title_years(*, text):
    lines = [
        clean_text(line)
        for line in str(text or "").splitlines()
        if clean_text(line)
    ]

    for line in lines:
        match = SERIES_YEAR_RE.search(line)

        if not match:
            continue

        title = clean_text(line[: match.start()])
        start_year = clean_text(match.group("start_year"))
        end_value = clean_text(match.group("end_value"))

        if not title:
            continue

        return title, start_year, end_value

    return "", "", ""


def derive_status_from_series_end_value(end_value):
    if clean_text(end_value).casefold() == "present":
        return "ongoing"

    if clean_text(end_value):
        return "ended"

    return "unknown"


def settle_browser_context(*, context):
    page = None

    try:
        page = context.new_page()
        page.wait_for_timeout(RETRY_SETTLE_MS)
    except Exception:
        pass
    finally:
        safe_close_page(page)


def safe_close_page(page):
    if page is None:
        return

    try:
        page.close()
    except Exception:
        pass