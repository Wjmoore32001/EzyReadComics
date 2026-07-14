from dataclasses import dataclass
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from catalog.marvel.browser import (
    DEFAULT_CALENDAR_TIMEOUT_MS,
    DEFAULT_DETAIL_TIMEOUT_MS,
    MARVEL_CALENDAR_TIME_ZONE,
    ensure_playwright,
    marvel_browser_context,
)
from catalog.marvel.collection_writer import (
    PreviewObject,
    catalog_run_title,
    create_or_update_volume_run,
    create_volume_issue,
    create_volume_one_shot,
    get_or_create_collection_run,
    get_or_create_one_shot,
    get_or_create_volume,
    is_preview,
)
from catalog.marvel.collections import (
    build_collection_calendar_url,
    current_marvel_date,
    empty_collection_detail,
    extract_calendar_collections,
    format_collection_row,
    parsed_collection_issue_links,
    read_collection_calendar_page,
    read_collection_detail_page,
)
from catalog.marvel.issues import (
    get_detail_value,
    get_issue_missing_fields,
    read_issue_detail_page,
)
from catalog.marvel.series import (
    read_issue_page_series_url,
    read_series_page,
)
from catalog.marvel.sync_planner import get_issue_detail_read_reason
from catalog.marvel.text import (
    clean_text,
    issue_number_sort_key,
    normalize_issue_number,
    normalize_title,
)
from catalog.marvel.writer import (
    find_existing_issue,
    find_existing_run,
    get_or_create_marvel_publisher,
    upsert_issue_from_series_issue,
    upsert_run_from_series,
)


DEFAULT_LIMIT = None

SKIP_COLLECTION_KEYWORDS = (
    "[DM ONLY]",
    "DM ONLY",
    "DIRECT MARKET ONLY",
    "VARIANT",
    "VARIANT COVER",
)


@dataclass
class RunSeriesLookup:
    run_key: tuple
    run_link: dict
    series_url: str = ""
    series: object = None
    error: str = ""


@dataclass
class CollectionDetailRecord:
    collection: dict
    detail: dict


class Command(BaseCommand):
    help = (
        "Sync Marvel collected volumes from the official Marvel.com collection calendar. "
        "Uses shared Marvel calendar/detail/series readers. No AI calls. No Comic Vine calls. No Marvel search."
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
            help=f"Collection/series/issue detail timeout in milliseconds. Default: {DEFAULT_DETAIL_TIMEOUT_MS}.",
        )
        parser.add_argument(
            "--skip-details",
            action="store_true",
            help="Do not read missing/incomplete issue detail pages.",
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
        ensure_playwright()

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

        read_result = read_calendar_and_collection_details(
            calendar_url=calendar_url,
            limit=limit,
            headed=headed,
            calendar_timeout=calendar_timeout,
            detail_timeout=detail_timeout,
        )

        collections = read_result["collections"]
        kept_collections = read_result["kept_collections"]
        skipped_collections = read_result["skipped_collections"]
        records = read_result["records"]

        totals["calendar_reads"] = 1
        totals["collection_detail_reads"] = len(kept_collections)
        totals["calendar_rows"] = len(collections)
        totals["skipped_collections"] = len(skipped_collections)
        totals["limit_skipped"] = read_result["limit_skipped"]

        if verbose and skipped_collections:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Skipped DM/variant collection rows"))

            for collection in skipped_collections:
                self.stdout.write(format_collection_row(collection))

        close_old_connections()

        series_lookups = build_series_lookups(
            records=records,
            headed=headed,
            timeout_ms=detail_timeout,
        )
        totals["series_page_reads"] = count_series_reads(series_lookups)
        totals["series_url_missing"] = count_missing_series_urls(series_lookups)
        totals["series_read_failures"] = count_series_failures(series_lookups)

        issue_detail_plans = []

        if not skip_details:
            issue_detail_plans = build_issue_detail_plans(
                records=records,
                series_lookups=series_lookups,
            )

        totals["planned_issue_detail_reads"] = len(issue_detail_plans)

        detail_map = {}

        if issue_detail_plans:
            detail_map = read_issue_details(
                issue_detail_plans=issue_detail_plans,
                headed=headed,
                timeout_ms=detail_timeout,
            )

        totals["issue_detail_reads"] = len(detail_map)

        for detail in detail_map.values():
            if get_detail_value(detail, "error"):
                totals["issue_detail_failures"] += 1

            missing_fields = get_issue_missing_fields(detail)

            if "description" in missing_fields:
                totals["missing_description"] += 1

            if "writer" in missing_fields:
                totals["missing_writer"] += 1

        for record in records:
            close_old_connections()

            result = sync_collection(
                record=record,
                series_lookups=series_lookups,
                detail_map=detail_map,
                skip_details=skip_details,
                dry_run=dry_run,
            )
            merge_totals(totals, result)

            if verbose:
                self.print_result(
                    record=record,
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
        self.stdout.write(f"Detail/series timeout: {detail_timeout} ms")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Comic Vine calls: 0")
        self.stdout.write("Marvel search calls: 0")
        self.stdout.write("Publisher: Marvel")
        self.stdout.write(
            "Collection process limit: "
            + (str(limit) if limit is not None else "unlimited")
        )
        self.stdout.write(f"Issue detail lookup: {'off' if skip_details else 'on'}")
        self.stdout.write("Skip collection keywords: " + ", ".join(SKIP_COLLECTION_KEYWORDS))

    def print_result(self, *, record, result, dry_run):
        prefix = "Would" if dry_run else "Did"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(format_collection_row(record.collection)))

        if result["skipped"]:
            self.stdout.write(f"  Skipped: {result['skipped']}")
            return

        self.stdout.write(f"  Collection confidence: {record.detail.get('confidence') or 'none'}")
        self.stdout.write(f"  Parsed run links: {len(record.detail.get('run_links') or [])}")
        self.stdout.write(f"  Parsed one-shots: {len(record.detail.get('one_shots') or [])}")
        self.stdout.write(f"  Series page reads: {result['series_page_reads']}")
        self.stdout.write(f"  Series URLs missing: {result['series_url_missing']}")
        self.stdout.write(f"  Series read failures: {result['series_read_failures']}")
        self.stdout.write(f"  Issue URLs found: {result['issue_urls_found']}")
        self.stdout.write(f"  Issue URLs missing: {result['issue_urls_missing']}")
        self.stdout.write(f"  Issue detail reads: {result['issue_detail_reads']}")
        self.stdout.write(f"  {prefix} create volume: {result['volumes_created']}")
        self.stdout.write(f"  {prefix} update volume: {result['volumes_updated']}")
        self.stdout.write(f"  {prefix} create runs: {result['runs_created']}")
        self.stdout.write(f"  {prefix} update runs: {result['runs_updated']}")
        self.stdout.write(f"  {prefix} create volume-run links: {result['volume_runs_created']}")
        self.stdout.write(f"  {prefix} update volume-run links: {result['volume_runs_updated']}")
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
        self.stdout.write(f"Series page reads: {totals['series_page_reads']}")
        self.stdout.write(f"Issue detail browser reads: {totals['issue_detail_reads']}")
        self.stdout.write(f"Issue detail failures: {totals['issue_detail_failures']}")
        self.stdout.write("AI calls: 0")
        self.stdout.write("Comic Vine calls: 0")
        self.stdout.write("Marvel search calls: 0")
        self.stdout.write(f"Collection rows found: {totals['calendar_rows']}")
        self.stdout.write(f"Skipped DM/variant collection rows: {totals['skipped_collections']}")
        self.stdout.write(f"Skipped by limit: {totals['limit_skipped']}")
        self.stdout.write(f"Collections processed: {totals['collections_processed']}")
        self.stdout.write(f"Collections skipped: {totals['collections_skipped']}")
        self.stdout.write(f"Series URLs missing: {totals['series_url_missing']}")
        self.stdout.write(f"Series read failures: {totals['series_read_failures']}")
        self.stdout.write(f"Planned issue detail reads: {totals['planned_issue_detail_reads']}")
        self.stdout.write(f"Issues missing description: {totals['missing_description']}")
        self.stdout.write(f"Issues missing Writer: {totals['missing_writer']}")
        self.stdout.write(f"Issue URLs found: {totals['issue_urls_found']}")
        self.stdout.write(f"Issue URLs missing: {totals['issue_urls_missing']}")
        self.stdout.write(f"{prefix_created} volumes: {totals['volumes_created']}")
        self.stdout.write(f"{prefix_updated} volumes: {totals['volumes_updated']}")
        self.stdout.write(f"{prefix_created} runs: {totals['runs_created']}")
        self.stdout.write(f"{prefix_updated} runs: {totals['runs_updated']}")
        self.stdout.write(f"{prefix_created} volume-run links: {totals['volume_runs_created']}")
        self.stdout.write(f"{prefix_updated} volume-run links: {totals['volume_runs_updated']}")
        self.stdout.write(f"{prefix_created} issues: {totals['issues_created']}")
        self.stdout.write(f"{prefix_updated} issues: {totals['issues_updated']}")
        self.stdout.write(f"{prefix_created} volume-issue links: {totals['volume_issues_created']}")
        self.stdout.write(f"{prefix_created} one-shots: {totals['one_shots_created']}")
        self.stdout.write(f"{prefix_created} volume-one-shot links: {totals['volume_one_shots_created']}")
        self.stdout.write(f"Credits added: {totals['credits_added']}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog data was created or updated.")


def read_calendar_and_collection_details(
    *,
    calendar_url,
    limit,
    headed,
    calendar_timeout,
    detail_timeout,
):
    with marvel_browser_context(headed=headed) as context:
        rendered_calendar = read_collection_calendar_page(
            context=context,
            calendar_url=calendar_url,
            timeout_ms=calendar_timeout,
        )
        collections = extract_calendar_collections(rendered_calendar)
        kept_collections, skipped_collections = split_skipped_collections(collections)

        limit_skipped = 0

        if limit is not None and len(kept_collections) > limit:
            limit_skipped = len(kept_collections) - limit
            kept_collections = kept_collections[:limit]

        records = []

        for collection in kept_collections:
            detail = read_collection_detail_page(
                context=context,
                collection=collection,
                timeout_ms=detail_timeout,
            )
            records.append(
                CollectionDetailRecord(
                    collection=collection,
                    detail=detail,
                )
            )

    return {
        "rendered_calendar": rendered_calendar,
        "collections": collections,
        "kept_collections": kept_collections,
        "skipped_collections": skipped_collections,
        "records": records,
        "limit_skipped": limit_skipped,
    }


def build_series_lookups(*, records, headed, timeout_ms):
    run_refs = collect_unique_run_refs(records)
    known_series_urls = load_known_series_urls(run_refs)
    issue_seed_urls = collect_issue_seed_urls(records)

    lookups = {}

    with marvel_browser_context(headed=headed) as context:
        for run_key, run_link in run_refs.items():
            series_url = known_series_urls.get(run_key) or ""
            error = ""

            if not series_url:
                seed_issue_url = issue_seed_urls.get(run_key)

                if seed_issue_url:
                    series_url = read_issue_page_series_url(
                        context=context,
                        issue_url=seed_issue_url,
                        timeout_ms=timeout_ms,
                    )

            if not series_url:
                lookups[run_key] = RunSeriesLookup(
                    run_key=run_key,
                    run_link=run_link,
                    series_url="",
                    series=None,
                    error="no local Marvel series URL and no collection issue URL seed",
                )
                continue

            series = read_series_page(
                context=context,
                series_url=series_url,
                timeout_ms=timeout_ms,
            )

            if series.errors:
                error = "; ".join(series.errors)

            lookups[run_key] = RunSeriesLookup(
                run_key=run_key,
                run_link=run_link,
                series_url=series_url,
                series=series,
                error=error,
            )

    return lookups


def collect_unique_run_refs(records):
    refs = {}

    for record in records:
        for run_link in normalized_run_links(record.detail.get("run_links") or []):
            refs.setdefault(run_key_from_run_link(run_link), run_link)

    return refs


def load_known_series_urls(run_refs):
    close_old_connections()
    urls = {}

    for run_key, run_link in run_refs.items():
        existing_run = find_existing_run(
            title=run_link["catalog_run_title"],
            start_year=run_link["start_year"],
        )

        if existing_run and clean_text(existing_run.official_source_url):
            urls[run_key] = clean_text(existing_run.official_source_url)

    close_old_connections()
    return urls


def collect_issue_seed_urls(records):
    seeds = {}

    for record in records:
        parsed_links = parsed_collection_issue_links(record.detail)

        for run_link in normalized_run_links(record.detail.get("run_links") or []):
            run_key = run_key_from_run_link(run_link)

            if run_key in seeds:
                continue

            for issue_number in run_link.get("issue_numbers") or []:
                matched = find_matching_collection_issue_link(
                    parsed_links=parsed_links,
                    run_link=run_link,
                    issue_number=issue_number,
                )

                if matched:
                    seeds[run_key] = matched["href"]
                    break

    return seeds


def build_issue_detail_plans(*, records, series_lookups):
    plans = {}
    close_old_connections()

    for record in records:
        for run_link in normalized_run_links(record.detail.get("run_links") or []):
            lookup = series_lookups.get(run_key_from_run_link(run_link))
            series = lookup.series if lookup else None

            if not series:
                continue

            existing_run = find_existing_run(
                title=series.title,
                start_year=series.start_year,
                marvel_series_id=series.marvel_series_id,
            )
            issue_lookup = series_issue_lookup(series)

            for issue_number in run_link.get("issue_numbers") or []:
                series_issue = issue_lookup.get(normalize_issue_number(issue_number))

                if not series_issue:
                    continue

                existing_issue = find_existing_issue(
                    run=existing_run,
                    issue_number=series_issue.issue_number,
                    marvel_issue_id=get_object_value(series_issue, "marvel_issue_id"),
                )
                reason = get_issue_detail_read_reason(
                    existing_issue=existing_issue,
                    series_issue=series_issue,
                )

                if not reason:
                    continue

                plans.setdefault(
                    series_issue_key(series_issue),
                    {
                        "series_issue": series_issue,
                        "reason": reason,
                    },
                )

    close_old_connections()
    return list(plans.values())


def read_issue_details(*, issue_detail_plans, headed, timeout_ms):
    detail_map = {}

    with marvel_browser_context(headed=headed) as context:
        for plan in issue_detail_plans:
            series_issue = plan["series_issue"]
            detail = read_issue_detail_page(
                context=context,
                issue=series_issue,
                timeout_ms=timeout_ms,
            )
            detail_map[series_issue_key(series_issue)] = detail

    return detail_map


def sync_collection(*, record, series_lookups, detail_map, skip_details, dry_run):
    totals = new_totals()
    totals["collections_processed"] = 1

    collection = record.collection
    detail = record.detail or empty_collection_detail()

    if detail.get("error"):
        totals["collections_skipped"] = 1
        totals["skipped"] = detail["error"]
        return totals

    run_links = normalized_run_links(detail.get("run_links") or [])
    one_shots = clean_one_shot_candidates(detail.get("one_shots") or [])

    if not run_links:
        totals["collections_skipped"] = 1
        totals["skipped"] = "no parsed run links for ComicVolume.run"
        return totals

    publisher = get_or_create_marvel_publisher()

    primary_run = resolve_or_create_run(
        publisher=publisher,
        run_link=run_links[0],
        series_lookups=series_lookups,
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
        lookup = series_lookups.get(run_key_from_run_link(run_link))
        series = lookup.series if lookup else None

        if lookup:
            if lookup.series_url:
                totals["series_page_reads"] += 1
            if lookup.error:
                totals["series_read_failures"] += 1
            if not lookup.series_url:
                totals["series_url_missing"] += 1

        run = resolve_or_create_run(
            publisher=publisher,
            run_link=run_link,
            series_lookups=series_lookups,
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

        issue_lookup = series_issue_lookup(series) if series else {}

        for issue_number in sorted(run_link["issue_numbers"], key=issue_number_sort_key):
            series_issue = issue_lookup.get(normalize_issue_number(issue_number))
            issue = None

            if series_issue:
                totals["issue_urls_found"] += 1
                issue = resolve_or_create_issue(
                    run=run,
                    series_issue=series_issue,
                    detail_map=detail_map,
                    skip_details=skip_details,
                    dry_run=dry_run,
                    totals=totals,
                )
            else:
                totals["issue_urls_missing"] += 1

                if not is_preview(run):
                    issue = find_existing_issue(
                        run=run,
                        issue_number=issue_number,
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


def resolve_or_create_run(*, publisher, run_link, series_lookups, dry_run, totals):
    lookup = series_lookups.get(run_key_from_run_link(run_link))
    series = lookup.series if lookup else None

    if series:
        run, result = upsert_run_from_series(
            series=series,
            dry_run=dry_run,
        )
        totals["runs_created"] += result.run_created
        totals["runs_updated"] += result.run_updated

        if dry_run and run is None and result.run_created:
            return PreviewObject(
                title=series.title,
                start_year=series.start_year,
            )

        if run:
            return run

    return get_or_create_collection_run(
        publisher=publisher,
        run_title=run_link["catalog_run_title"],
        start_year=run_link["start_year"],
        dry_run=dry_run,
        totals=totals,
    )


def resolve_or_create_issue(*, run, series_issue, detail_map, skip_details, dry_run, totals):
    existing_issue = None

    if not is_preview(run):
        existing_issue = find_existing_issue(
            run=run,
            issue_number=series_issue.issue_number,
            marvel_issue_id=get_object_value(series_issue, "marvel_issue_id"),
        )

    detail = detail_map.get(series_issue_key(series_issue))

    if detail is None:
        return existing_issue

    totals["issue_detail_reads"] += 1

    if get_detail_value(detail, "error"):
        totals["issue_detail_failures"] += 1

        if existing_issue:
            return existing_issue

        return None

    if not get_detail_value(detail, "published_date") and existing_issue is None:
        return None

    issue, result = upsert_issue_from_series_issue(
        run=None if is_preview(run) else run,
        series_issue=series_issue,
        detail=detail,
        dry_run=dry_run,
    )
    totals["issues_created"] += result.issue_created
    totals["issues_updated"] += result.issue_updated
    totals["credits_added"] += result.credits_added

    if dry_run and issue is None and result.issue_created:
        return PreviewObject(issue_number=series_issue.issue_number)

    return issue or existing_issue


def normalized_run_links(run_links):
    normalized = []

    for run_link in run_links:
        item = dict(run_link)
        item["source_run_title"] = clean_text(run_link.get("run_title"))
        item["catalog_run_title"] = catalog_run_title(item["source_run_title"])
        normalized.append(item)

    return normalized


def run_key_from_run_link(run_link):
    return (
        normalize_title(run_link["catalog_run_title"]),
        clean_text(run_link["start_year"]),
    )


def series_issue_lookup(series):
    if not series:
        return {}

    return {
        normalize_issue_number(issue.issue_number): issue
        for issue in series.issues
    }


def find_matching_collection_issue_link(*, parsed_links, run_link, issue_number):
    for parsed_link in parsed_links:
        if clean_text(parsed_link.get("start_year")) != clean_text(run_link["start_year"]):
            continue

        if normalize_issue_number(parsed_link.get("issue_number")) != normalize_issue_number(issue_number):
            continue

        if not title_matches(parsed_link.get("run_title"), run_link["catalog_run_title"], run_link["source_run_title"]):
            continue

        return parsed_link

    return None


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


def clean_one_shot_candidates(one_shots):
    cleaned = []

    for one_shot in one_shots:
        reason = clean_text(one_shot.get("reason"))

        if reason.startswith("title looks like"):
            continue

        cleaned.append(one_shot)

    return cleaned


def series_issue_key(series_issue):
    marvel_issue_id = clean_text(get_object_value(series_issue, "marvel_issue_id"))

    if marvel_issue_id:
        return ("id", marvel_issue_id)

    detail_url = clean_text(get_object_value(series_issue, "detail_url"))

    if detail_url:
        return ("url", detail_url)

    return (
        "number",
        normalize_title(get_object_value(series_issue, "run_title")),
        clean_text(get_object_value(series_issue, "start_year")),
        normalize_issue_number(get_object_value(series_issue, "issue_number")),
    )


def get_object_value(value, name):
    if isinstance(value, dict):
        return value.get(name)

    return getattr(value, name, None)


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


def count_series_reads(series_lookups):
    return len(
        [
            lookup
            for lookup in series_lookups.values()
            if lookup.series_url
        ]
    )


def count_missing_series_urls(series_lookups):
    return len(
        [
            lookup
            for lookup in series_lookups.values()
            if not lookup.series_url
        ]
    )


def count_series_failures(series_lookups):
    return len(
        [
            lookup
            for lookup in series_lookups.values()
            if lookup.error and lookup.series_url
        ]
    )


def new_totals():
    return {
        "calendar_reads": 0,
        "collection_detail_reads": 0,
        "series_page_reads": 0,
        "issue_detail_reads": 0,
        "issue_detail_failures": 0,
        "calendar_rows": 0,
        "skipped_collections": 0,
        "limit_skipped": 0,
        "collections_processed": 0,
        "collections_skipped": 0,
        "series_url_missing": 0,
        "series_read_failures": 0,
        "planned_issue_detail_reads": 0,
        "missing_description": 0,
        "missing_writer": 0,
        "volumes_created": 0,
        "volumes_updated": 0,
        "runs_created": 0,
        "runs_updated": 0,
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