import re
from dataclasses import dataclass, field

from catalog.marvel.browser import PlaywrightTimeoutError, safe_wait_for_networkidle
from catalog.marvel.credits import (
    DETAIL_CREDIT_LABELS,
    extract_detail_credits_from_page,
    normalize_credit_list,
    split_credit_names,
)
from catalog.marvel.text import (
    canonical_issue_number,
    clean_text,
    normalize_issue_number,
    normalize_title,
)
from catalog.marvel.urls import parse_marvel_issue_url


ISSUE_TEXT_RE = re.compile(
    r"(?P<title>[A-Z0-9][^\n\r#]{1,180}?)\s*"
    r"\((?P<year>\d{4})\)\s*"
    r"#(?P<issue>[A-Z0-9][A-Z0-9.\-/]*)",
    re.IGNORECASE,
)

PUBLISHED_DATE_RE = re.compile(
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

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


@dataclass
class MarvelIssueDetail:
    checked: bool = False
    read_attempted: bool = False
    error: str = ""
    published_date: object = None
    description: str = ""
    credits: list[dict] = field(default_factory=list)
    issue_links: list[dict] = field(default_factory=list)
    text_preview: str = ""


def empty_issue_detail():
    return MarvelIssueDetail()


def read_issue_detail_page(*, context, issue, timeout_ms):
    detail_url = get_issue_value(issue, "detail_url")

    if not detail_url:
        detail = empty_issue_detail()
        detail.checked = True
        detail.read_attempted = False
        detail.error = "missing detail URL"
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
            detail = empty_issue_detail()
            detail.checked = True
            detail.read_attempted = True
            detail.error = f"HTTP {status}"
            return detail

        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

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
        except Exception:
            pass

        page.wait_for_timeout(1000)

        text = page.locator("body").inner_text(timeout=timeout_ms)
        issue_links = extract_issue_links_from_page(page)
        dom_credits = extract_detail_credits_from_page(page)

        detail = parse_issue_detail_text(
            text=text,
            issue=issue,
            dom_credits=dom_credits,
        )
        detail.checked = True
        detail.read_attempted = True
        detail.error = ""
        detail.issue_links = issue_links
        detail.text_preview = text[:2000]
        return detail

    except Exception as exc:
        detail = empty_issue_detail()
        detail.checked = True
        detail.read_attempted = True
        detail.error = str(exc)
        return detail

    finally:
        page.close()


def extract_issue_links_from_page(page):
    try:
        return page.eval_on_selector_all(
            "a",
            """
            elements => elements
                .map((element) => ({
                    text: (element.innerText || "").trim(),
                    href: element.href || ""
                }))
                .filter((item) => item.href && item.href.includes("/comics/issue/"))
            """,
        )
    except Exception:
        return []


def parse_issue_detail_text(*, text, issue, dom_credits=None):
    lines = normalize_page_lines(text)
    title_index = find_detail_title_index(lines=lines, issue=issue)
    end_index = find_detail_end_index(lines=lines, start_index=title_index)

    text_credits = []
    published_date = None
    last_metadata_index = title_index
    index = title_index + 1

    while index < end_index:
        line = lines[index]
        label, inline_value = parse_detail_label_line(line)

        if label == "PUBLISHED":
            published_date = parse_detail_published_date(inline_value)

            if published_date:
                last_metadata_index = max(last_metadata_index, index)
                index += 1
                continue

            value_index = find_next_value_line_index(
                lines=lines,
                start_index=index + 1,
                end_index=end_index,
            )

            if value_index is not None:
                published_date = parse_detail_published_date(lines[value_index])
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
                text_credits.append(
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

    if published_date is None:
        published_date = get_issue_value(issue, "published_date")

    credits = combine_dom_and_text_credits(
        dom_credits=dom_credits or [],
        text_credits=text_credits,
    )

    return MarvelIssueDetail(
        checked=False,
        read_attempted=False,
        error="",
        published_date=published_date,
        description=description,
        credits=credits,
        issue_links=[],
        text_preview=text[:2000],
    )


def combine_dom_and_text_credits(*, dom_credits, text_credits):
    normalized_dom_credits = normalize_credit_list(dom_credits)
    normalized_text_credits = normalize_credit_list(text_credits)
    roles_with_dom_credits = {
        credit["role"].casefold()
        for credit in normalized_dom_credits
    }

    combined = list(normalized_dom_credits)

    for credit in normalized_text_credits:
        if credit["role"].casefold() in roles_with_dom_credits:
            continue

        combined.append(credit)

    return normalize_credit_list(combined)


def get_issue_missing_fields(detail):
    missing_fields = []

    if not clean_text(get_detail_value(detail, "description")):
        missing_fields.append("description")

    if not detail_has_writer(detail):
        missing_fields.append("writer")

    return missing_fields


def issue_detail_is_complete(detail):
    return not get_issue_missing_fields(detail)


def detail_has_writer(detail):
    for credit in get_detail_value(detail, "credits") or []:
        role = clean_text(credit.get("role"))

        if role.casefold() == "writer":
            return True

    return False


def normalize_page_lines(text):
    lines = []

    for line in str(text or "").splitlines():
        line = clean_text(line)

        if not line:
            continue

        lines.append(line)

    return lines


def find_detail_title_index(*, lines, issue):
    normalized_target_title = normalize_title(get_issue_value(issue, "run_title"))
    target_issue_number = normalize_issue_number(get_issue_value(issue, "issue_number"))

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


def parse_detail_published_date(value):
    value = clean_text(value)

    if not value:
        return None

    match = PUBLISHED_DATE_RE.search(value)

    if not match:
        return None

    month = match.group("month")
    day = match.group("day")
    year = match.group("year")

    try:
        from datetime import datetime

        return datetime.strptime(
            f"{month} {day}, {year}",
            "%B %d, %Y",
        ).date()
    except ValueError:
        return None


def looks_like_people_line(line):
    line = clean_text(line)

    if not line:
        return False

    if len(line) > 180:
        return False

    if re.search(r"[!?]", line):
        return False

    words = re.findall(r"[A-Za-z][A-Za-z.'-]*", line)

    if len(words) > 16:
        return False

    return True


def clean_description(value):
    value = clean_text(value)

    if not value:
        return ""

    value = re.sub(r"\bRead\s+More\b.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\bSee\s+Variant\s+Covers\b.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\bDigital\s+Issue\b.*$", "", value, flags=re.IGNORECASE)
    value = clean_text(value)

    return value


def should_skip_description_line(line):
    line = clean_text(line)

    if not line:
        return True

    normalized = normalize_detail_label(line)

    if normalized in DETAIL_SKIP_LINES:
        return True

    if normalized in DETAIL_STOP_LINES:
        return True

    if normalized in DETAIL_CREDIT_LABELS:
        return True

    if ISSUE_TEXT_RE.search(line):
        return True

    if line.startswith("http://") or line.startswith("https://"):
        return True

    return False


def get_issue_value(issue, name):
    if isinstance(issue, dict):
        return issue.get(name)

    return getattr(issue, name, None)


def get_detail_value(detail, name):
    if isinstance(detail, dict):
        return detail.get(name)

    return getattr(detail, name, None)


def issue_from_detail_url(detail_url):
    parsed_url = parse_marvel_issue_url(detail_url)

    if parsed_url is None:
        return {
            "run_title": "",
            "start_year": "",
            "issue_number": "",
            "published_date": None,
            "detail_url": detail_url,
        }

    return {
        "run_title": parsed_url.run_title,
        "start_year": parsed_url.start_year,
        "issue_number": canonical_issue_number(parsed_url.issue_number),
        "published_date": None,
        "detail_url": detail_url,
        "marvel_issue_id": parsed_url.marvel_id,
        "issue_slug": parsed_url.slug,
    }