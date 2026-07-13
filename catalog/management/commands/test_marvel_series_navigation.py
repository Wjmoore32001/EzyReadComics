import re
from datetime import timedelta
from urllib.parse import unquote

from django.core.management.base import BaseCommand, CommandError

from catalog.management.commands.sync_marvel_release_calendar_ai import (
    DEFAULT_CALENDAR_TIMEOUT_MS,
    MARVEL_CALENDAR_TIME_ZONE,
    build_browser_context,
    build_calendar_url,
    clean_text,
    current_marvel_date,
    extract_calendar_issues,
    format_calendar_issue,
    format_credits,
    get_detail_missing_fields,
    issue_number_sort_key,
    parse_issue_link,
    read_calendar_with_playwright,
    read_issue_detail_page,
    sync_playwright,
)


MARVEL_SERIES_URL_RE = re.compile(
    r"/comics/series/(?P<series_id>\d+)/(?P<slug>[^/?#]+)",
    re.IGNORECASE,
)

MARVEL_ISSUE_URL_RE = re.compile(
    r"/comics/issue/(?P<issue_id>\d+)/(?P<slug>[^/?#]+)",
    re.IGNORECASE,
)

ISSUE_TEXT_RE = re.compile(
    r"(?P<title>[A-Z0-9][^\n\r#]{1,180}?)\s*"
    r"\((?P<year>\d{4})\)\s*"
    r"#(?P<issue>[A-Z0-9][A-Z0-9.\-/]*)",
    re.IGNORECASE,
)

SERIES_YEAR_RE = re.compile(
    r"\((?P<start_year>\d{4})(?:\s*-\s*(?P<end_value>Present|\d{4}))?\)",
    re.IGNORECASE,
)


class Command(BaseCommand):
    help = (
        "Temporary scanner for testing Marvel navigation: "
        "release calendar issue -> issue detail -> Back to Series -> full series issue list -> optional issue detail checks."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Calendar date to scan, YYYY-MM-DD. Default: current Marvel ET date.",
        )
        parser.add_argument(
            "--issue-url",
            help="Skip the calendar and start from a specific Marvel issue URL.",
        )
        parser.add_argument(
            "--series-url",
            help="Skip the calendar and start from a specific Marvel series URL.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=3,
            help="Maximum calendar issues to inspect. Default: 3.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=DEFAULT_CALENDAR_TIMEOUT_MS,
            help=f"Playwright timeout in milliseconds. Default: {DEFAULT_CALENDAR_TIMEOUT_MS}.",
        )
        parser.add_argument(
            "--check-details",
            action="store_true",
            help="Read every unique issue detail page found on the series page.",
        )
        parser.add_argument(
            "--detail-limit",
            type=int,
            default=None,
            help="Optional limit for issue detail pages checked. Default: all.",
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print all issue links and detail check rows.",
        )

    def handle(self, *args, **options):
        if sync_playwright is None:
            raise CommandError(
                "Playwright is not installed. Run: "
                "pip install playwright && python -m playwright install chromium"
            )

        timeout = options["timeout"]

        if timeout < 1000:
            raise CommandError("--timeout must be at least 1000 milliseconds.")

        limit = options["limit"]

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1.")

        detail_limit = options["detail_limit"]

        if detail_limit is not None and detail_limit < 1:
            raise CommandError("--detail-limit must be at least 1 when provided.")

        issue_url = clean_text(options.get("issue_url"))
        series_url = clean_text(options.get("series_url"))

        if issue_url and series_url:
            raise CommandError("Use either --issue-url or --series-url, not both.")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel series navigation test"))
        self.stdout.write(f"Calendar timezone: {MARVEL_CALENDAR_TIME_ZONE}")
        self.stdout.write(f"Browser mode: {'headed' if options['headed'] else 'headless'}")
        self.stdout.write(f"Timeout: {timeout} ms")
        self.stdout.write(f"Issue detail check: {'on' if options['check_details'] else 'off'}")
        self.stdout.write(
            "Issue detail check limit: "
            + (str(detail_limit) if detail_limit is not None else "all")
        )
        self.stdout.write("AI calls: 0")
        self.stdout.write("Comic Vine calls: 0")

        seed_items = []

        if series_url:
            seed_items = [
                {
                    "kind": "series",
                    "series_url": series_url,
                    "seed_issue": empty_seed_issue(),
                }
            ]
        elif issue_url:
            if is_marvel_series_url(issue_url):
                seed_items = [
                    {
                        "kind": "series",
                        "series_url": issue_url,
                        "seed_issue": empty_seed_issue(),
                    }
                ]
            else:
                seed_items = [
                    {
                        "kind": "issue",
                        "series_url": "",
                        "seed_issue": {
                            "run_title": "",
                            "start_year": "",
                            "issue_number": "",
                            "published_date": None,
                            "detail_url": issue_url,
                        },
                    }
                ]
        else:
            release_date = parse_date_or_default(options.get("date"))
            calendar_url = build_calendar_url(
                start_date=release_date,
                end_date=release_date,
            )

            self.stdout.write(f"Calendar source: {calendar_url}")

            rendered_calendar = read_calendar_with_playwright(
                calendar_url=calendar_url,
                headed=options["headed"],
                timeout_ms=timeout,
            )

            calendar_issues, incomplete_count = extract_calendar_issues(
                rendered_calendar=rendered_calendar,
            )

            self.stdout.write(f"Calendar issues found: {len(calendar_issues)}")
            self.stdout.write(f"Incomplete calendar rows skipped: {incomplete_count}")

            for calendar_issue in calendar_issues[:limit]:
                seed_items.append(
                    {
                        "kind": "issue",
                        "series_url": "",
                        "seed_issue": calendar_issue,
                    }
                )

        if not seed_items:
            self.stdout.write(self.style.WARNING("No seed issues or series found."))
            return

        results = read_navigation_results(
            seed_items=seed_items,
            headed=options["headed"],
            timeout_ms=timeout,
            check_details=options["check_details"],
            detail_limit=detail_limit,
        )

        for result in results:
            self.print_result(
                result=result,
                verbose=options["verbose"],
                check_details=options["check_details"],
            )

    def print_result(self, *, result, verbose, check_details):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Seed"))

        seed_issue = result["seed_issue"]

        if result["seed_kind"] == "series":
            self.stdout.write(f"Series seed URL: {result['series_url'] or 'none'}")
        elif seed_issue.get("run_title"):
            self.stdout.write(format_calendar_issue(seed_issue))
        else:
            self.stdout.write(seed_issue["detail_url"])

        self.stdout.write(f"Seed kind: {result['seed_kind']}")
        self.stdout.write(f"Seed issue URL: {seed_issue.get('detail_url') or 'none'}")
        self.stdout.write(f"Seed issue ID: {result['seed_issue_id'] or 'none'}")
        self.stdout.write(f"Seed issue slug: {result['seed_issue_slug'] or 'none'}")
        self.stdout.write(f"Back to Series URL: {result['series_url'] or 'none'}")
        self.stdout.write(f"Series ID: {result['series_id'] or 'none'}")
        self.stdout.write(f"Series slug: {result['series_slug'] or 'none'}")
        self.stdout.write(f"Series title: {result['series_title'] or 'none'}")
        self.stdout.write(f"Series start year: {result['series_start_year'] or 'none'}")
        self.stdout.write(f"Series end/present value: {result['series_end_value'] or 'none'}")
        self.stdout.write(f"Derived run status: {result['derived_status'] or 'unknown'}")
        self.stdout.write(f"Load More clicks: {result['load_more_clicks']}")
        self.stdout.write(f"Raw series issue links found: {result['raw_series_issue_link_count']}")
        self.stdout.write(f"Unique uppercase series issue links found: {len(result['series_issues'])}")

        if check_details:
            detail_summary = result["detail_summary"]

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Issue detail check summary"))
            self.stdout.write(f"Detail pages checked: {detail_summary['checked']}")
            self.stdout.write(f"Detail read failures: {detail_summary['read_failures']}")
            self.stdout.write(f"Complete details: {detail_summary['complete']}")
            self.stdout.write(f"Incomplete details: {detail_summary['incomplete']}")
            self.stdout.write(f"Missing published date: {detail_summary['missing_published_date']}")
            self.stdout.write(f"Missing description: {detail_summary['missing_description']}")
            self.stdout.write(f"Missing Writer: {detail_summary['missing_writer']}")
            self.stdout.write(f"Total credits parsed: {detail_summary['credits']}")

        if result["errors"]:
            self.stdout.write(self.style.WARNING("Errors / warnings:"))

            for error in result["errors"]:
                self.stdout.write(f"  - {error}")

        if verbose:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Unique uppercase series issue links"))

            for issue in result["series_issues"]:
                self.stdout.write(
                    "  "
                    + f"{issue['run_title']} ({issue['start_year']}) "
                    + f"#{issue['issue_number']} "
                    + f"[id={issue['issue_id'] or 'none'}] "
                    + f"-> {issue['detail_url']}"
                )

        if verbose and check_details:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Issue detail check rows"))

            for row in result["detail_rows"]:
                missing_text = ", ".join(row["missing_fields"]) or "none"

                self.stdout.write(
                    "  "
                    + f"{row['run_title']} ({row['start_year']}) "
                    + f"#{row['issue_number']} "
                    + f"[id={row['issue_id'] or 'none'}] "
                    + f"date={row['published_date'] or 'none'} "
                    + f"missing={missing_text} "
                    + f"credits={row['credit_count']} "
                    + f"error={row['error'] or 'none'}"
                )

                if row["credits"]:
                    self.stdout.write("    Credits: " + format_credits(row["credits"]))


def read_navigation_results(*, seed_items, headed, timeout_ms, check_details, detail_limit):
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = build_browser_context(browser)

        try:
            for seed_item in seed_items:
                result = inspect_seed_item(
                    context=context,
                    seed_item=seed_item,
                    timeout_ms=timeout_ms,
                    check_details=check_details,
                    detail_limit=detail_limit,
                )
                results.append(result)
        finally:
            context.close()
            browser.close()

    return results


def inspect_seed_item(*, context, seed_item, timeout_ms, check_details, detail_limit):
    seed_issue = seed_item["seed_issue"]

    result = {
        "seed_kind": seed_item["kind"],
        "seed_issue": seed_issue,
        "seed_issue_id": "",
        "seed_issue_slug": "",
        "series_url": "",
        "series_id": "",
        "series_slug": "",
        "series_title": "",
        "series_start_year": "",
        "series_end_value": "",
        "derived_status": "",
        "series_issues": [],
        "raw_series_issue_link_count": 0,
        "load_more_clicks": 0,
        "detail_summary": empty_detail_summary(),
        "detail_rows": [],
        "errors": [],
    }

    if seed_item["kind"] == "series":
        result["series_url"] = clean_text(seed_item["series_url"])
    else:
        detail_url = clean_text(seed_issue.get("detail_url"))

        if not detail_url:
            result["errors"].append("Seed issue is missing detail_url.")
            return result

        issue_id, issue_slug = parse_marvel_issue_url(detail_url)
        result["seed_issue_id"] = issue_id
        result["seed_issue_slug"] = issue_slug

        issue_page_data = read_issue_page_for_series_link(
            context=context,
            detail_url=detail_url,
            timeout_ms=timeout_ms,
        )

        result["errors"].extend(issue_page_data["errors"])
        result["series_url"] = issue_page_data["series_url"]

    if not result["series_url"]:
        result["errors"].append("No series URL found.")
        return result

    series_id, series_slug = parse_marvel_series_url(result["series_url"])
    result["series_id"] = series_id
    result["series_slug"] = series_slug

    series_data = read_series_page(
        context=context,
        series_url=result["series_url"],
        timeout_ms=timeout_ms,
    )

    result["errors"].extend(series_data["errors"])
    result["series_title"] = series_data["series_title"]
    result["series_start_year"] = series_data["series_start_year"]
    result["series_end_value"] = series_data["series_end_value"]
    result["derived_status"] = derive_status_from_series_end_value(
        series_data["series_end_value"]
    )
    result["series_issues"] = series_data["issues"]
    result["raw_series_issue_link_count"] = series_data["raw_issue_link_count"]
    result["load_more_clicks"] = series_data["load_more_clicks"]

    if check_details:
        detail_check = check_issue_details(
            context=context,
            series_issues=result["series_issues"],
            timeout_ms=timeout_ms,
            detail_limit=detail_limit,
        )
        result["detail_summary"] = detail_check["summary"]
        result["detail_rows"] = detail_check["rows"]

    return result


def read_issue_page_for_series_link(*, context, detail_url, timeout_ms):
    page = context.new_page()

    try:
        response = page.goto(
            detail_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        status = response.status if response else None

        if status and status >= 400:
            return {
                "series_url": "",
                "errors": [f"Issue page returned HTTP {status}."],
            }

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

        series_url = extract_back_to_series_url(page)

        return {
            "series_url": series_url,
            "errors": [],
        }
    except Exception as exc:
        return {
            "series_url": "",
            "errors": [f"Issue page read failed: {exc}"],
        }
    finally:
        page.close()


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
    page = context.new_page()

    try:
        response = page.goto(
            series_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        status = response.status if response else None

        if status and status >= 400:
            return empty_series_data(errors=[f"Series page returned HTTP {status}."])

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

        load_more_clicks = click_load_more_until_exhausted(
            page=page,
            timeout_ms=timeout_ms,
        )

        text = page.locator("body").inner_text(timeout=timeout_ms)
        series_title, start_year, end_value = parse_series_title_years(text=text)
        raw_issue_link_count = count_issue_links(page)
        issues = extract_series_issues_from_page(page)

        return {
            "series_title": series_title,
            "series_start_year": start_year,
            "series_end_value": end_value,
            "issues": issues,
            "raw_issue_link_count": raw_issue_link_count,
            "load_more_clicks": load_more_clicks,
            "errors": [],
        }

    except Exception as exc:
        return empty_series_data(errors=[f"Series page read failed: {exc}"])
    finally:
        page.close()


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
        page.wait_for_timeout(750)

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

        parsed = parse_issue_link(link)

        if not parsed:
            continue

        issue_id, issue_slug = parse_marvel_issue_url(parsed["detail_url"])
        parsed["issue_id"] = issue_id
        parsed["issue_slug"] = issue_slug

        if issue_id:
            by_issue_id[issue_id] = parsed
            continue

        fallback_key = (
            parsed["detail_url"],
            parsed["run_title"],
            parsed["start_year"],
            parsed["issue_number"],
        )
        by_fallback_key[fallback_key] = parsed

    issues = list(by_issue_id.values()) + list(by_fallback_key.values())

    return sorted(
        issues,
        key=lambda issue: issue_number_sort_key(issue["issue_number"]),
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


def check_issue_details(*, context, series_issues, timeout_ms, detail_limit):
    summary = empty_detail_summary()
    rows = []

    issues_to_check = list(series_issues)

    if detail_limit is not None:
        issues_to_check = issues_to_check[:detail_limit]

    for issue in issues_to_check:
        calendar_issue = {
            "run_title": issue["run_title"],
            "start_year": issue["start_year"],
            "issue_number": issue["issue_number"],
            "published_date": None,
            "detail_url": issue["detail_url"],
        }

        detail = read_issue_detail_page(
            context=context,
            calendar_issue=calendar_issue,
            timeout_ms=timeout_ms,
        )

        missing_fields = get_detail_missing_fields(detail)

        if not detail.get("published_date"):
            missing_fields.append("published_date")

        credits = detail.get("credits") or []

        row = {
            "run_title": issue["run_title"],
            "start_year": issue["start_year"],
            "issue_number": issue["issue_number"],
            "issue_id": issue.get("issue_id"),
            "detail_url": issue["detail_url"],
            "published_date": (
                detail["published_date"].isoformat()
                if detail.get("published_date")
                else ""
            ),
            "missing_fields": missing_fields,
            "credit_count": len(credits),
            "credits": credits,
            "error": clean_text(detail.get("error")),
        }
        rows.append(row)

        summary["checked"] += 1
        summary["credits"] += len(credits)

        if row["error"]:
            summary["read_failures"] += 1

        if missing_fields:
            summary["incomplete"] += 1
        else:
            summary["complete"] += 1

        if "published_date" in missing_fields:
            summary["missing_published_date"] += 1

        if "description" in missing_fields:
            summary["missing_description"] += 1

        if "writer" in missing_fields:
            summary["missing_writer"] += 1

    return {
        "summary": summary,
        "rows": rows,
    }


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


def is_marvel_series_url(url):
    return bool(MARVEL_SERIES_URL_RE.search(clean_text(url)))


def parse_marvel_issue_url(url):
    match = MARVEL_ISSUE_URL_RE.search(clean_text(url))

    if not match:
        return "", ""

    return clean_text(match.group("issue_id")), clean_text(unquote(match.group("slug")))


def parse_marvel_series_url(url):
    match = MARVEL_SERIES_URL_RE.search(clean_text(url))

    if not match:
        return "", ""

    return clean_text(match.group("series_id")), clean_text(unquote(match.group("slug")))


def safe_wait_for_networkidle(*, page, timeout_ms):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def empty_seed_issue():
    return {
        "run_title": "",
        "start_year": "",
        "issue_number": "",
        "published_date": None,
        "detail_url": "",
    }


def empty_series_data(*, errors):
    return {
        "series_title": "",
        "series_start_year": "",
        "series_end_value": "",
        "issues": [],
        "raw_issue_link_count": 0,
        "load_more_clicks": 0,
        "errors": errors,
    }


def empty_detail_summary():
    return {
        "checked": 0,
        "read_failures": 0,
        "complete": 0,
        "incomplete": 0,
        "missing_published_date": 0,
        "missing_description": 0,
        "missing_writer": 0,
        "credits": 0,
    }


def parse_date_or_default(value):
    value = clean_text(value)

    if not value:
        return current_marvel_date()

    try:
        year, month, day = value.split("-", 2)
        return current_marvel_date().replace(
            year=int(year),
            month=int(month),
            day=int(day),
        )
    except Exception as exc:
        raise CommandError("--date must use YYYY-MM-DD format.") from exc