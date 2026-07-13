import re
from datetime import timedelta

from django.core.management.base import CommandError

from catalog.marvel.browser import marvel_browser_context, safe_wait_for_networkidle
from catalog.marvel.calendar import current_marvel_date
from catalog.marvel.text import (
    canonical_issue_number,
    clean_text,
    issue_number_sort_key,
    normalize_title,
)
from catalog.marvel.urls import parse_marvel_collection_url, parse_marvel_issue_url


MARVEL_CALENDAR_BASE_URL = "https://www.marvel.com/comics/calendar"

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
    r"(?P<title>[A-Z][A-Z0-9 .:'’!?&/+,\-]+?)\s*\((?P<year>\d{4})\)"
)

PRE_YEAR_ISSUE_TOKEN_RE = re.compile(
    r"(?P<title_prefix>[A-Z][A-Z0-9 .:'’!?&/+,\-]*?)\s+"
    r"#(?P<issue>[A-Z0-9.]+(?:\s*[-–—]\s*[A-Z0-9.]+)?)\s+"
    r"(?P<title_suffix>[A-Z][A-Z0-9 .:'’!?&/+,\-]*?)\s*"
    r"\((?P<year>\d{4})\)"
)

ISSUE_TOKEN_RE = re.compile(
    r"#\s*(?P<issue>[A-Za-z0-9.]+(?:\s*[-–—]\s*[A-Za-z0-9.]+)?)"
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


def build_collection_calendar_url(*, start_date, end_date):
    return (
        f"{MARVEL_CALENDAR_BASE_URL}"
        f"?dateEnd={end_date.isoformat()}"
        f"&dateStart={start_date.isoformat()}"
        f"&tab=collection"
        f"&variants=false"
    )


def build_current_collection_calendar_url():
    start_date = current_marvel_date()
    end_date = start_date + timedelta(days=6)

    return build_collection_calendar_url(
        start_date=start_date,
        end_date=end_date,
    )


def read_collection_calendar_with_browser(*, calendar_url, headed=False, timeout_ms=45000):
    with marvel_browser_context(headed=headed) as context:
        return read_collection_calendar_page(
            context=context,
            calendar_url=calendar_url,
            timeout_ms=timeout_ms,
        )


def read_collection_details_with_browser(*, collections, headed=False, timeout_ms=45000):
    details = {}

    with marvel_browser_context(headed=headed) as context:
        for collection in collections:
            details[collection["detail_url"]] = read_collection_detail_page(
                context=context,
                collection=collection,
                timeout_ms=timeout_ms,
            )

    return details


def read_collection_calendar_page(*, context, calendar_url, timeout_ms):
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

        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

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
        except Exception:
            pass

        page.wait_for_timeout(1000)

        return {
            "title": page.title(),
            "status": status,
            "text": page.locator("body").inner_text(timeout=timeout_ms),
            "links": extract_collection_links_from_page(page),
        }
    finally:
        page.close()


def extract_collection_links_from_page(page):
    return page.eval_on_selector_all(
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

        safe_wait_for_networkidle(page=page, timeout_ms=timeout_ms)

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
        except Exception:
            pass

        page.wait_for_timeout(1000)

        text = page.locator("body").inner_text(timeout=timeout_ms)
        detail = parse_collection_detail_text(text=text)
        detail["read_attempted"] = True
        detail["error"] = ""
        detail["issue_links"] = extract_issue_links_from_collection_page(page)
        detail["text_preview"] = text[:2500]
        return detail

    except Exception as exc:
        detail = empty_collection_detail()
        detail["read_attempted"] = True
        detail["error"] = str(exc)
        return detail
    finally:
        page.close()


def extract_issue_links_from_collection_page(page):
    try:
        return page.eval_on_selector_all(
            "a",
            """
            elements => elements
                .map((element) => ({
                    text: (element.innerText || element.textContent || "").trim(),
                    href: element.href || ""
                }))
                .filter((item) => item.href && item.href.includes("/comics/issue/"))
            """,
        )
    except Exception:
        return []


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

        parsed_url = parse_marvel_collection_url(detail_url)
        published_date = parse_calendar_date_from_text(rendered_calendar.get("text"))

        collections.append(
            {
                "title": title or "[unknown collection title]",
                "published_date": published_date,
                "detail_url": detail_url,
                "marvel_collection_id": parsed_url.marvel_id if parsed_url else "",
                "collection_slug": parsed_url.slug if parsed_url else "",
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


def collection_sort_key(collection):
    published_date = collection.get("published_date")

    return (
        published_date or current_marvel_date(),
        normalize_title(collection.get("title")),
        collection.get("detail_url") or "",
    )


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
        "issue_links": [],
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

    return ""


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
        return [canonical_issue_number(expression)]

    start_text, end_text = expression.split("-", 1)

    if not start_text.isdigit() or not end_text.isdigit():
        return [canonical_issue_number(expression)]

    start = int(start_text)
    end = int(end_text)

    if end < start:
        return [canonical_issue_number(expression)]

    if end - start > 300:
        return [canonical_issue_number(expression)]

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
        "issue_links": [],
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
    from datetime import datetime

    value = clean_text(value)

    for date_format in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None


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


def unique_list(values):
    seen = set()
    result = []

    for value in values:
        key = clean_text(value).casefold()

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(value)

    return result


def format_collection_row(collection):
    published_date = collection.get("published_date")
    date_text = published_date.isoformat() if published_date else "no date"

    return f"{collection.get('title', '[unknown]')} [{date_text}]"


def parsed_collection_issue_links(detail):
    parsed_links = []

    for link in detail.get("issue_links") or []:
        parsed = parse_marvel_issue_url(link.get("href"))

        if not parsed:
            continue

        parsed_links.append(
            {
                "text": clean_text(link.get("text")),
                "href": clean_text(link.get("href")),
                "run_title": parsed.run_title,
                "start_year": parsed.start_year,
                "issue_number": parsed.issue_number,
                "marvel_issue_id": parsed.marvel_id,
                "issue_slug": parsed.slug,
            }
        )

    return parsed_links