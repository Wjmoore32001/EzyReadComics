import re
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from catalog.marvel.browser import (
    MARVEL_CALENDAR_TIME_ZONE,
    marvel_browser_context,
    safe_wait_for_networkidle,
)
from catalog.marvel.text import (
    canonical_issue_number,
    clean_text,
    normalize_issue_number,
    normalize_title,
)
from catalog.marvel.urls import parse_marvel_issue_url


MARVEL_CALENDAR_BASE_URL = "https://www.marvel.com/comics/calendar"

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


@dataclass
class MarvelCalendarIssue:
    run_title: str
    start_year: str
    issue_number: str
    published_date: object
    detail_url: str = ""
    marvel_issue_id: str = ""
    issue_slug: str = ""


def current_marvel_date():
    return timezone.localtime(
        timezone.now(),
        ZoneInfo(MARVEL_CALENDAR_TIME_ZONE),
    ).date()


def build_release_calendar_url(*, start_date, end_date):
    return (
        f"{MARVEL_CALENDAR_BASE_URL}"
        f"?dateEnd={end_date.isoformat()}"
        f"&dateStart={start_date.isoformat()}"
        f"&tab=comic"
        f"&variants=false"
    )


def build_current_release_calendar_url():
    start_date = current_marvel_date()
    end_date = start_date + timedelta(days=6)

    return build_release_calendar_url(
        start_date=start_date,
        end_date=end_date,
    )


def read_release_calendar_with_browser(*, calendar_url, headed=False, timeout_ms=45000):
    with marvel_browser_context(headed=headed) as context:
        return read_release_calendar_page(
            context=context,
            calendar_url=calendar_url,
            timeout_ms=timeout_ms,
        )


def read_release_calendar_page(*, context, calendar_url, timeout_ms):
    page = context.new_page()

    try:
        response = page.goto(
            calendar_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        status = response.status if response else None

        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

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
        except Exception:
            pass

        page.wait_for_timeout(1000)

        return {
            "title": page.title(),
            "status": status,
            "text": page.locator("body").inner_text(timeout=timeout_ms),
            "links": extract_calendar_issue_links(page),
        }

    finally:
        page.close()


def extract_calendar_issue_links(page):
    return page.eval_on_selector_all(
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


def extract_release_calendar_issues(*, rendered_calendar):
    text_issues = extract_release_calendar_issues_from_text(rendered_calendar["text"])
    link_map = build_issue_link_map(rendered_calendar["links"])

    issues = []
    seen = set()
    incomplete_count = 0

    for issue in text_issues:
        identity = calendar_issue_identity(issue)

        if not identity:
            incomplete_count += 1
            continue

        if identity in seen:
            continue

        seen.add(identity)

        detail_url = link_map.get(
            (
                normalize_title(issue.run_title),
                clean_text(issue.start_year),
                normalize_issue_number(issue.issue_number),
            )
        )

        if detail_url:
            issue.detail_url = detail_url
            parsed_url = parse_marvel_issue_url(detail_url)

            if parsed_url:
                issue.marvel_issue_id = parsed_url.marvel_id
                issue.issue_slug = parsed_url.slug

        issues.append(issue)

    return issues, incomplete_count


def extract_release_calendar_issues_from_text(text):
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
            MarvelCalendarIssue(
                run_title=run_title,
                start_year=start_year,
                issue_number=issue_number,
                published_date=published_date,
            )
        )

    return issues


def build_issue_link_map(links):
    link_map = {}

    for link in links or []:
        issue = parse_calendar_issue_link(link)

        if issue is None:
            continue

        key = (
            normalize_title(issue.run_title),
            clean_text(issue.start_year),
            normalize_issue_number(issue.issue_number),
        )
        link_map[key] = issue.detail_url

    return link_map


def parse_calendar_issue_link(link):
    text = clean_text(link.get("text"))
    href = clean_text(link.get("href"))

    if not href:
        return None

    match = ISSUE_TEXT_RE.search(text)

    if match:
        parsed_url = parse_marvel_issue_url(href)

        return MarvelCalendarIssue(
            run_title=clean_calendar_title(match.group("title")),
            start_year=clean_text(match.group("year")),
            issue_number=canonical_issue_number(match.group("issue")),
            published_date=None,
            detail_url=href,
            marvel_issue_id=parsed_url.marvel_id if parsed_url else "",
            issue_slug=parsed_url.slug if parsed_url else "",
        )

    parsed_url = parse_marvel_issue_url(href)

    if not parsed_url:
        return None

    return MarvelCalendarIssue(
        run_title=parsed_url.run_title,
        start_year=parsed_url.start_year,
        issue_number=parsed_url.issue_number,
        published_date=None,
        detail_url=href,
        marvel_issue_id=parsed_url.marvel_id,
        issue_slug=parsed_url.slug,
    )


def calendar_issue_identity(issue):
    if not issue.run_title or not issue.start_year or not issue.issue_number or not issue.published_date:
        return None

    return (
        normalize_title(issue.run_title),
        clean_text(issue.start_year),
        normalize_issue_number(issue.issue_number),
        issue.published_date,
    )


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


def parse_calendar_display_date(value):
    value = clean_text(value)

    for date_format in ("%m/%d/%Y", "%B %d, %Y"):
        try:
            return timezone.datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None


def clean_calendar_title(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" -–—")
    return value