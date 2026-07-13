from datetime import timedelta
from urllib.parse import quote

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils.text import slugify

from catalog.management.commands.sync_marvel_release_calendar_ai import (
    apply_calendar_issue,
    clean_text,
    find_existing_issue,
    find_existing_run,
    normalize_issue_number,
    normalize_title,
    parse_issue_link,
    read_issue_detail_page,
)
from catalog.management.commands.test_marvel_collection_calendar_parse import (
    DEFAULT_CALENDAR_TIMEOUT_MS,
    DEFAULT_DETAIL_TIMEOUT_MS,
    MARVEL_CALENDAR_TIME_ZONE,
    build_browser_context,
    build_collection_calendar_url,
    current_marvel_date,
    extract_calendar_collections,
    format_collection_row,
    issue_number_sort_key,
    read_collection_calendar_with_playwright,
    read_collection_details_with_playwright,
    sync_playwright,
)
from catalog.models import (
    ComicOneShot,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
    ComicVolumeOneShot,
    ComicVolumeRun,
)


MARVEL_PUBLISHER_NAME = "Marvel"
MARVEL_SEARCH_URL = "https://www.marvel.com/search"

DEFAULT_LIMIT = None

SKIP_COLLECTION_KEYWORDS = (
    "[DM ONLY]",
    "DM ONLY",
    "DIRECT MARKET ONLY",
    "VARIANT",
    "VARIANT COVER",
)


class Command(BaseCommand):
    help = (
        "Sync Marvel collected volumes from the official Marvel.com collection calendar. "
        "Creates volumes, runs, issues, one-shots, and collection relationship rows. "
        "No AI calls. No Comic Vine calls."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help="Maximum kept collections to process. Default: unlimited.",
        )
        parser.add_argument(
            "--calendar-timeout",
            type=int,
            default=DEFAULT_CALENDAR_TIMEOUT_MS,
            help=f"Calendar page timeout in milliseconds. Default: {DEFAULT_CALENDAR_TIMEOUT_MS}.",
        )
        parser.add_argument(
            "--detail-timeout",
            type=int,
            default=DEFAULT_DETAIL_TIMEOUT_MS,
            help=f"Collection/issue detail timeout in milliseconds. Default: {DEFAULT_DETAIL_TIMEOUT_MS}.",
        )
        parser.add_argument(
            "--skip-details",
            action="store_true",
            help="Do not search/read missing issue detail pages.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview actions without writing catalog data. Default is apply mode.",
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print row-level actions.",
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
        dry_run = options["dry_run"]
        skip_details = options["skip_details"]
        headed = options["headed"]
        verbose = options["verbose"]

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1 when provided.")

        if calendar_timeout < 1000:
            raise CommandError("--calendar-timeout must be at least 1000 milliseconds.")

        if detail_timeout < 1000:
            raise CommandError("--detail-timeout must be at least 1000 milliseconds.")

        start_date = current_marvel_date()
        end_date = start_date + timedelta(days=6)
        calendar_url = build_collection_calendar_url(
            start_date=start_date,
            end_date=end_date,
        )

        totals = new_totals()

        self.print_header(
            calendar_url=calendar_url,
            start_date=start_date,
            end_date=end_date,
            dry_run=dry_run,
            limit=limit,
            skip_details=skip_details,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
        )

        rendered_calendar = read_collection_calendar_with_playwright(
            calendar_url=calendar_url,
            headed=headed,
            timeout_ms=calendar_timeout,
        )
        totals["calendar_reads"] += 1

        collections = extract_calendar_collections(rendered_calendar)
        totals["calendar_rows"] = len(collections)

        kept_collections, skipped_collections = split_skipped_collections(collections)
        totals["skipped_collections"] = len(skipped_collections)

        if limit is not None and len(kept_collections) > limit:
            totals["limit_skipped"] = len(kept_collections) - limit
            kept_collections = kept_collections[:limit]

        if verbose and skipped_collections:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Skipped DM/variant collection rows"))

            for collection in skipped_collections:
                self.stdout.write(format_collection_row(collection))

        details = read_collection_details_with_playwright(
            collections=kept_collections,
            headed=headed,
            timeout_ms=detail_timeout,
        )
        totals["collection_detail_reads"] += len(kept_collections)

        for collection in kept_collections:
            close_old_connections()

            detail = details.get(collection["detail_url"]) or empty_detail()

            result = sync_collection(
                collection=collection,
                detail=detail,
                detail_timeout=detail_timeout,
                skip_details=skip_details,
                dry_run=dry_run,
                headed=headed,
            )
            merge_totals(totals, result)

            if verbose:
                self.print_result(
                    collection=collection,
                    result=result,
                    dry_run=dry_run,
                )

        self.print_summary(totals=totals, dry_run=dry_run)

    def print_header(
        self,
        *,
        calendar_url,
        start_date,
        end_date,
        dry_run,
        limit,
        skip_details,
        headed,
        calendar_timeout,
        detail_timeout,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel collection calendar sync"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write(f"Source: {calendar_url}")
        self.stdout.write(f"Date range: {start_date.isoformat()} to {end_date.isoformat()}")
        self.stdout.write(f"Calendar timezone: {MARVEL_CALENDAR_TIME_ZONE}")
        self.stdout.write("Calendar tab: collection")
        self.stdout.write("Variants parameter: false")
        self.stdout.write("Reader: Playwright Chromium")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Calendar timeout: {calendar_timeout} ms")
        self.stdout.write(f"Detail timeout: {detail_timeout} ms")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Comic Vine calls: 0")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write(
            "Collection process limit: "
            + (str(limit) if limit is not None else "unlimited")
        )
        self.stdout.write(f"Issue detail lookup: {'off' if skip_details else 'on'}")
        self.stdout.write("Skip collection keywords: " + ", ".join(SKIP_COLLECTION_KEYWORDS))

    def print_result(self, *, collection, result, dry_run):
        prefix = "Would" if dry_run else "Did"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(format_collection_row(collection)))

        if result["skipped"]:
            self.stdout.write(f"  Skipped: {result['skipped']}")
            return

        self.stdout.write(f"  {prefix} create volume: {result['volumes_created']}")
        self.stdout.write(f"  {prefix} update volume: {result['volumes_updated']}")
        self.stdout.write(f"  {prefix} create runs: {result['runs_created']}")
        self.stdout.write(f"  {prefix} create volume-run links: {result['volume_runs_created']}")
        self.stdout.write(f"  {prefix} update volume-run links: {result['volume_runs_updated']}")
        self.stdout.write(f"  Issue URLs found: {result['issue_urls_found']}")
        self.stdout.write(f"  Issue URLs missing: {result['issue_urls_missing']}")
        self.stdout.write(f"  {prefix} create issues: {result['issues_created']}")
        self.stdout.write(f"  {prefix} update issues: {result['issues_updated']}")
        self.stdout.write(f"  {prefix} create volume-issue links: {result['volume_issues_created']}")
        self.stdout.write(f"  {prefix} create one-shots: {result['one_shots_created']}")
        self.stdout.write(f"  {prefix} create volume-one-shot links: {result['volume_one_shots_created']}")
        self.stdout.write(f"  Credits added: {result['credits_added']}")

    def print_summary(self, *, totals, dry_run):
        prefix_created = "Would create" if dry_run else "Created"
        prefix_updated = "Would update" if dry_run else "Updated"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel collection calendar sync complete."))
        self.stdout.write(f"Calendar browser reads: {totals['calendar_reads']}")
        self.stdout.write(f"Collection detail browser reads: {totals['collection_detail_reads']}")
        self.stdout.write(f"Issue search browser reads: {totals['issue_search_reads']}")
        self.stdout.write(f"Issue detail browser reads: {totals['issue_detail_reads']}")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Comic Vine calls: 0")
        self.stdout.write(f"Collection rows found: {totals['calendar_rows']}")
        self.stdout.write(f"Skipped DM/variant collection rows: {totals['skipped_collections']}")
        self.stdout.write(f"Skipped by limit: {totals['limit_skipped']}")
        self.stdout.write(f"Collections processed: {totals['collections_processed']}")
        self.stdout.write(f"Collections skipped: {totals['collections_skipped']}")
        self.stdout.write(f"{prefix_created} volumes: {totals['volumes_created']}")
        self.stdout.write(f"{prefix_updated} volumes: {totals['volumes_updated']}")
        self.stdout.write(f"{prefix_created} runs: {totals['runs_created']}")
        self.stdout.write(f"{prefix_created} volume-run links: {totals['volume_runs_created']}")
        self.stdout.write(f"{prefix_updated} volume-run links: {totals['volume_runs_updated']}")
        self.stdout.write(f"Issue URLs found: {totals['issue_urls_found']}")
        self.stdout.write(f"Issue URLs missing: {totals['issue_urls_missing']}")
        self.stdout.write(f"{prefix_created} issues: {totals['issues_created']}")
        self.stdout.write(f"{prefix_updated} issues: {totals['issues_updated']}")
        self.stdout.write(f"{prefix_created} volume-issue links: {totals['volume_issues_created']}")
        self.stdout.write(f"{prefix_created} one-shots: {totals['one_shots_created']}")
        self.stdout.write(f"{prefix_created} volume-one-shot links: {totals['volume_one_shots_created']}")
        self.stdout.write(f"Credits added: {totals['credits_added']}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog data was created or updated.")


def sync_collection(*, collection, detail, detail_timeout, skip_details, dry_run, headed):
    totals = new_totals()
    totals["collections_processed"] = 1

    if detail.get("error"):
        totals["collections_skipped"] = 1
        totals["skipped"] = detail["error"]
        return totals

    run_links = normalize_run_links(detail.get("run_links") or [])
    one_shots = clean_one_shot_candidates(detail.get("one_shots") or [])

    if not run_links:
        totals["collections_skipped"] = 1
        totals["skipped"] = "no parsed run links for ComicVolume.run"
        return totals

    publisher = get_marvel_publisher(dry_run=dry_run)

    primary_run = get_or_create_run(
        publisher=publisher,
        run_title=run_links[0]["catalog_run_title"],
        start_year=run_links[0]["start_year"],
        dry_run=dry_run,
        totals=totals,
    )

    volume = get_or_create_volume(
        publisher=publisher,
        primary_run=primary_run,
        collection=collection,
        detail=detail,
        run_link=run_links[0],
        one_shots=one_shots,
        dry_run=dry_run,
        totals=totals,
    )

    item_order = 1

    for run_link in run_links:
        run = get_or_create_run(
            publisher=publisher,
            run_title=run_link["catalog_run_title"],
            start_year=run_link["start_year"],
            dry_run=dry_run,
            totals=totals,
        )

        create_or_update_volume_run(
            volume=volume,
            run=run,
            run_link=run_link,
            item_order=item_order,
            dry_run=dry_run,
            totals=totals,
        )

        for issue_number in sorted(run_link["issue_numbers"], key=issue_number_sort_key):
            issue = None

            if not is_preview(run):
                issue = find_existing_issue(run=run, issue_number=issue_number)

            if issue is None and not skip_details:
                issue = create_missing_issue_from_marvel(
                    run_link=run_link,
                    issue_number=issue_number,
                    detail_timeout=detail_timeout,
                    dry_run=dry_run,
                    headed=headed,
                    totals=totals,
                )

            create_volume_issue(
                volume=volume,
                issue=issue,
                issue_order=item_order,
                dry_run=dry_run,
                totals=totals,
            )
            item_order += 1

    for one_shot_data in one_shots:
        one_shot = get_or_create_one_shot(
            publisher=publisher,
            one_shot_data=one_shot_data,
            dry_run=dry_run,
            totals=totals,
        )

        create_volume_one_shot(
            volume=volume,
            one_shot=one_shot,
            item_order=item_order,
            dry_run=dry_run,
            totals=totals,
        )
        item_order += 1

    return totals


def normalize_run_links(run_links):
    normalized = []

    for run_link in run_links:
        item = dict(run_link)
        item["source_run_title"] = clean_text(run_link.get("run_title"))
        item["catalog_run_title"] = catalog_run_title(item["source_run_title"])
        normalized.append(item)

    return normalized


def catalog_run_title(title):
    title = clean_text(title)

    if normalize_title(title) == "amazing spider man":
        return "THE AMAZING SPIDER-MAN"

    return title


def get_marvel_publisher(*, dry_run):
    existing = ComicPublisher.objects.filter(name__iexact=MARVEL_PUBLISHER_NAME).first()

    if existing:
        return existing

    if dry_run:
        return PreviewObject(name=MARVEL_PUBLISHER_NAME, slug="marvel")

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


def get_or_create_run(*, publisher, run_title, start_year, dry_run, totals):
    existing = find_existing_run(title=run_title, start_year=start_year)

    if existing:
        update_spider_man_run_title(existing, run_title, dry_run=dry_run)
        return existing

    totals["runs_created"] += 1

    if dry_run:
        return PreviewObject(title=run_title, start_year=start_year)

    return ComicRun.objects.create(
        publisher=publisher,
        title=run_title,
        start_year=start_year,
        status=ComicRun.STATUS_UNKNOWN,
    )


def update_spider_man_run_title(run, desired_title, *, dry_run):
    if dry_run:
        return

    if normalize_title(run.title) != "amazing spider man":
        return

    if normalize_title(desired_title) != "the amazing spider man":
        return

    duplicate = (
        ComicRun.objects.filter(
            title__iexact=desired_title,
            start_year=run.start_year,
        )
        .exclude(id=run.id)
        .exists()
    )

    if duplicate:
        return

    run.title = desired_title
    run.save(update_fields=["title", "updated_at"])


def get_or_create_volume(*, publisher, primary_run, collection, detail, run_link, one_shots, dry_run, totals):
    existing = find_existing_volume(
        publisher=publisher,
        title=collection["title"],
        release_date=collection.get("published_date"),
    )

    first_issue = first_issue_number(run_link["issue_numbers"])
    last_issue = last_issue_number(run_link["issue_numbers"])
    issue_count = collected_item_count(detail=detail, one_shots=one_shots)
    description = clean_text(detail.get("description"))

    if existing:
        changed = volume_needs_update(
            volume=existing,
            primary_run=primary_run,
            release_date=collection.get("published_date"),
            first_issue=first_issue,
            last_issue=last_issue,
            issue_count=issue_count,
            description=description,
        )

        if changed:
            totals["volumes_updated"] += 1

            if not dry_run:
                existing.run = primary_run
                existing.release_date = collection.get("published_date")
                existing.first_issue_number = first_issue
                existing.last_issue_number = last_issue
                existing.issue_count = issue_count

                if description and not existing.description:
                    existing.description = description

                existing.save()

        return existing

    totals["volumes_created"] += 1

    if dry_run:
        return PreviewObject(title=collection["title"])

    return ComicVolume.objects.create(
        publisher=publisher,
        run=primary_run,
        title=collection["title"],
        volume_number=extract_volume_number(collection["title"]),
        first_issue_number=first_issue,
        last_issue_number=last_issue,
        release_date=collection.get("published_date"),
        issue_count=issue_count,
        description=description,
    )


def collected_item_count(*, detail, one_shots):
    issue_total = 0

    for run_link in detail.get("run_links", []) or []:
        issue_total += len(run_link.get("issue_numbers") or [])

    return issue_total + len(one_shots)


def find_existing_volume(*, publisher, title, release_date):
    if is_preview(publisher):
        return None

    queryset = ComicVolume.objects.filter(
        publisher=publisher,
        title__iexact=title,
    )

    if release_date:
        match = queryset.filter(release_date=release_date).order_by("id").first()

        if match:
            return match

    return queryset.order_by("id").first()


def volume_needs_update(*, volume, primary_run, release_date, first_issue, last_issue, issue_count, description):
    if not is_preview(primary_run) and volume.run_id != primary_run.id:
        return True

    if release_date and volume.release_date != release_date:
        return True

    if volume.first_issue_number != first_issue:
        return True

    if volume.last_issue_number != last_issue:
        return True

    if issue_count is not None and volume.issue_count != issue_count:
        return True

    if description and not volume.description:
        return True

    return False


def create_or_update_volume_run(*, volume, run, run_link, item_order, dry_run, totals):
    if is_preview(volume) or is_preview(run):
        totals["volume_runs_created"] += 1
        return

    issue_numbers_text = compact_issue_numbers(run_link["issue_numbers"])
    first_issue = first_issue_number(run_link["issue_numbers"])
    last_issue = last_issue_number(run_link["issue_numbers"])

    existing = ComicVolumeRun.objects.filter(volume=volume, run=run).first()

    if existing:
        changed = (
            existing.issue_numbers_text != issue_numbers_text
            or existing.first_issue_number != first_issue
            or existing.last_issue_number != last_issue
            or existing.item_order != item_order
        )

        if changed:
            totals["volume_runs_updated"] += 1

            if not dry_run:
                existing.issue_numbers_text = issue_numbers_text
                existing.first_issue_number = first_issue
                existing.last_issue_number = last_issue
                existing.item_order = item_order
                existing.save()

        return

    totals["volume_runs_created"] += 1

    if dry_run:
        return

    ComicVolumeRun.objects.create(
        volume=volume,
        run=run,
        first_issue_number=first_issue,
        last_issue_number=last_issue,
        issue_numbers_text=issue_numbers_text,
        item_order=item_order,
    )


def create_missing_issue_from_marvel(*, run_link, issue_number, detail_timeout, dry_run, headed, totals):
    issue_url = find_issue_url(
        headed=headed,
        source_run_title=run_link["source_run_title"],
        catalog_run_title=run_link["catalog_run_title"],
        start_year=run_link["start_year"],
        issue_number=issue_number,
        timeout_ms=detail_timeout,
    )
    totals["issue_search_reads"] += 1

    if not issue_url:
        totals["issue_urls_missing"] += 1
        return None

    totals["issue_urls_found"] += 1

    calendar_issue = {
        "run_title": run_link["catalog_run_title"],
        "start_year": run_link["start_year"],
        "issue_number": issue_number,
        "published_date": None,
        "detail_url": issue_url,
    }

    detail = read_issue_detail_without_orm_context(
        headed=headed,
        calendar_issue=calendar_issue,
        timeout_ms=detail_timeout,
    )
    totals["issue_detail_reads"] += 1

    if not detail.get("published_date"):
        totals["issue_urls_missing"] += 1
        return None

    calendar_issue["published_date"] = detail["published_date"]

    close_old_connections()

    result = apply_calendar_issue(
        calendar_issue=calendar_issue,
        detail=detail,
        dry_run=dry_run,
    )
    totals["runs_created"] += result["run_created"]
    totals["issues_created"] += result["issue_created"]
    totals["issues_updated"] += result["issue_updated"]
    totals["credits_added"] += result["credits_added"]

    if dry_run:
        return PreviewObject(issue_number=issue_number)

    close_old_connections()

    run = find_existing_run(
        title=run_link["catalog_run_title"],
        start_year=run_link["start_year"],
    )
    return find_existing_issue(run=run, issue_number=issue_number)


def read_issue_detail_without_orm_context(*, headed, calendar_issue, timeout_ms):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = build_browser_context(browser)

        try:
            return read_issue_detail_page(
                context=context,
                calendar_issue=calendar_issue,
                timeout_ms=timeout_ms,
            )
        finally:
            context.close()
            browser.close()


def find_issue_url(*, headed, source_run_title, catalog_run_title, start_year, issue_number, timeout_ms):
    queries = issue_search_queries(
        source_run_title=source_run_title,
        catalog_run_title=catalog_run_title,
        start_year=start_year,
        issue_number=issue_number,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = build_browser_context(browser)

        try:
            for query in queries:
                url = search_marvel_issue_url(
                    context=context,
                    query=query,
                    source_run_title=source_run_title,
                    catalog_run_title=catalog_run_title,
                    start_year=start_year,
                    issue_number=issue_number,
                    timeout_ms=timeout_ms,
                )

                if url:
                    return url
        finally:
            context.close()
            browser.close()

    return ""


def issue_search_queries(*, source_run_title, catalog_run_title, start_year, issue_number):
    source_run_title = clean_text(source_run_title)
    catalog_run_title = clean_text(catalog_run_title)

    titles = []

    if source_run_title:
        titles.append(source_run_title)

    if (
        normalize_title(source_run_title) == "amazing spider man"
        and catalog_run_title
        and catalog_run_title not in titles
    ):
        titles.append(catalog_run_title)

    queries = []

    for title in titles:
        queries.extend(
            [
                f"{title} ({start_year}) #{issue_number}",
                f"{title} {start_year} #{issue_number}",
                f"{title} #{issue_number}",
            ]
        )

    return queries


def search_marvel_issue_url(
    *,
    context,
    query,
    source_run_title,
    catalog_run_title,
    start_year,
    issue_number,
    timeout_ms,
):
    page = context.new_page()

    try:
        page.goto(
            f"{MARVEL_SEARCH_URL}?query={quote(query)}",
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )

        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass

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

        for link in links:
            parsed = parse_issue_link(link)

            if issue_matches(
                parsed=parsed,
                source_run_title=source_run_title,
                catalog_run_title=catalog_run_title,
                start_year=start_year,
                issue_number=issue_number,
            ):
                return parsed["detail_url"]

        return ""
    finally:
        page.close()


def issue_matches(*, parsed, source_run_title, catalog_run_title, start_year, issue_number):
    if not parsed:
        return False

    parsed_title = parsed.get("run_title")

    return (
        title_matches(parsed_title, catalog_run_title, source_run_title)
        and clean_text(parsed.get("start_year")) == clean_text(start_year)
        and normalize_issue_number(parsed.get("issue_number")) == normalize_issue_number(issue_number)
    )


def title_matches(candidate, *targets):
    candidate_normalized = normalize_title(candidate)

    for target in targets:
        target_normalized = normalize_title(target)

        if candidate_normalized == target_normalized:
            return True

        if spider_man_title_match(candidate_normalized, target_normalized):
            return True

    return False


def spider_man_title_match(left, right):
    if "spider man" not in left or "spider man" not in right:
        return False

    return strip_leading_the(left) == strip_leading_the(right)


def strip_leading_the(value):
    value = clean_text(value)

    if value.startswith("the "):
        return value[4:]

    return value


def create_volume_issue(*, volume, issue, issue_order, dry_run, totals):
    if issue is None:
        return

    if is_preview(volume) or is_preview(issue):
        totals["volume_issues_created"] += 1
        return

    existing = ComicVolumeIssue.objects.filter(volume=volume, issue=issue).first()

    if existing:
        if not dry_run and existing.issue_order != issue_order:
            existing.issue_order = issue_order
            existing.save(update_fields=["issue_order"])
        return

    totals["volume_issues_created"] += 1

    if dry_run:
        return

    ComicVolumeIssue.objects.create(
        volume=volume,
        issue=issue,
        issue_order=issue_order,
    )


def get_or_create_one_shot(*, publisher, one_shot_data, dry_run, totals):
    if is_preview(publisher):
        totals["one_shots_created"] += 1
        return PreviewObject(title=one_shot_data["title"])

    existing = ComicOneShot.objects.filter(
        publisher=publisher,
        title__iexact=one_shot_data["title"],
        start_year=one_shot_data["start_year"],
    ).order_by("id").first()

    if existing:
        return existing

    totals["one_shots_created"] += 1

    if dry_run:
        return PreviewObject(title=one_shot_data["title"])

    return ComicOneShot.objects.create(
        publisher=publisher,
        title=one_shot_data["title"],
        start_year=one_shot_data["start_year"],
    )


def create_volume_one_shot(*, volume, one_shot, item_order, dry_run, totals):
    if is_preview(volume) or is_preview(one_shot):
        totals["volume_one_shots_created"] += 1
        return

    existing = ComicVolumeOneShot.objects.filter(
        volume=volume,
        one_shot=one_shot,
    ).first()

    if existing:
        if not dry_run and existing.item_order != item_order:
            existing.item_order = item_order
            existing.save(update_fields=["item_order"])
        return

    totals["volume_one_shots_created"] += 1

    if dry_run:
        return

    ComicVolumeOneShot.objects.create(
        volume=volume,
        one_shot=one_shot,
        item_order=item_order,
    )


def split_skipped_collections(collections):
    kept = []
    skipped = []

    for collection in collections:
        if collection_should_be_skipped(collection):
            skipped.append(collection)
        else:
            kept.append(collection)

    return kept, skipped


def collection_should_be_skipped(collection):
    text = f"{collection.get('title', '')} {collection.get('detail_url', '')}".upper()
    return any(keyword in text for keyword in SKIP_COLLECTION_KEYWORDS)


def clean_one_shot_candidates(one_shots):
    cleaned = []

    for one_shot in one_shots:
        reason = clean_text(one_shot.get("reason"))

        if reason.startswith("title looks like"):
            continue

        cleaned.append(one_shot)

    return cleaned


def compact_issue_numbers(issue_numbers):
    values = sorted(issue_numbers, key=issue_number_sort_key)
    numeric = []

    for value in values:
        if not str(value).isdigit():
            return ",".join(clean_text(item) for item in values)

        numeric.append(int(value))

    if not numeric:
        return ""

    parts = []
    start = numeric[0]
    previous = numeric[0]

    for value in numeric[1:]:
        if value == previous + 1:
            previous = value
            continue

        parts.append(format_range(start, previous))
        start = value
        previous = value

    parts.append(format_range(start, previous))
    return ",".join(parts)


def format_range(start, end):
    if start == end:
        return str(start)

    return f"{start}-{end}"


def first_issue_number(issue_numbers):
    if not issue_numbers:
        return ""

    return clean_text(sorted(issue_numbers, key=issue_number_sort_key)[0])


def last_issue_number(issue_numbers):
    if not issue_numbers:
        return ""

    return clean_text(sorted(issue_numbers, key=issue_number_sort_key)[-1])


def extract_volume_number(title):
    title = clean_text(title)
    marker = "VOL."

    if marker not in title.upper():
        return ""

    after_marker = title.upper().split(marker, 1)[1].strip()
    value = after_marker.split(" ", 1)[0].strip(" :,-")

    return value if value.isdigit() else ""


def empty_detail():
    return {
        "error": "missing parsed collection detail",
        "run_links": [],
        "one_shots": [],
        "description": "",
    }


def new_totals():
    return {
        "calendar_reads": 0,
        "collection_detail_reads": 0,
        "issue_search_reads": 0,
        "issue_detail_reads": 0,
        "calendar_rows": 0,
        "skipped_collections": 0,
        "limit_skipped": 0,
        "collections_processed": 0,
        "collections_skipped": 0,
        "volumes_created": 0,
        "volumes_updated": 0,
        "runs_created": 0,
        "volume_runs_created": 0,
        "volume_runs_updated": 0,
        "issue_urls_found": 0,
        "issue_urls_missing": 0,
        "issues_created": 0,
        "issues_updated": 0,
        "volume_issues_created": 0,
        "one_shots_created": 0,
        "volume_one_shots_created": 0,
        "credits_added": 0,
        "skipped": "",
    }


def merge_totals(target, source):
    for key, value in source.items():
        if isinstance(value, int):
            target[key] += value


class PreviewObject:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.id = None
        self.pk = None


def is_preview(value):
    return isinstance(value, PreviewObject)