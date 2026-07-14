from collections import deque

from django.core.management.base import BaseCommand, CommandError

from catalog.dc.browser import (
    DEFAULT_TIMEOUT_MS,
    dc_browser_context,
    detail_skip_reason,
    read_browse_page,
    read_detail_page,
)
from catalog.dc.writer import (
    DcWriteResult,
    add_results,
    run_identity_from_detail,
    run_status_from_detail,
    write_dc_detail,
)


class Command(BaseCommand):
    help = "Sync DC.com browse/detail comic data into the catalog."

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
            help="Specific DC detail URL to sync. When set, Browse Comics is skipped.",
        )
        parser.add_argument(
            "--no-related-graphic-novels",
            action="store_false",
            dest="follow_related_graphic_novels",
            help="Do not sync graphic novels found in More From This Series.",
        )
        parser.set_defaults(follow_related_graphic_novels=True)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read DC pages and report what would change without writing catalog records.",
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=DEFAULT_TIMEOUT_MS,
            help=f"Playwright timeout in milliseconds. Default: {DEFAULT_TIMEOUT_MS}.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each synced detail page and classification.",
        )

    def handle(self, *args, **options):
        start_page = options["page"]
        page_count = options["page_count"]
        detail_url = options["detail_url"].strip()
        follow_related_graphic_novels = options["follow_related_graphic_novels"]
        dry_run = options["dry_run"]
        headed = options["headed"]
        timeout_ms = options["timeout"]
        verbose = options["verbose"]

        if start_page < 1:
            raise CommandError("--page must be at least 1.")

        if page_count < 1:
            raise CommandError("--page-count must be at least 1.")

        if timeout_ms < 1000:
            raise CommandError("--timeout must be at least 1000 milliseconds.")

        self.print_header(
            start_page=start_page,
            page_count=page_count,
            detail_url=detail_url,
            follow_related_graphic_novels=follow_related_graphic_novels,
            dry_run=dry_run,
            headed=headed,
            timeout_ms=timeout_ms,
        )

        if detail_url:
            total = self.sync_direct_detail_url(
                detail_url=detail_url,
                follow_related_graphic_novels=follow_related_graphic_novels,
                dry_run=dry_run,
                headed=headed,
                timeout_ms=timeout_ms,
                verbose=verbose,
            )
        else:
            total = self.sync_browse_pages(
                start_page=start_page,
                page_count=page_count,
                follow_related_graphic_novels=follow_related_graphic_novels,
                dry_run=dry_run,
                headed=headed,
                timeout_ms=timeout_ms,
                verbose=verbose,
            )

        self.print_totals(total)

    def sync_direct_detail_url(
        self,
        *,
        detail_url,
        follow_related_graphic_novels,
        dry_run,
        headed,
        timeout_ms,
        verbose,
    ):
        processed_detail_keys = set()

        with dc_browser_context(headed=headed) as context:
            details = self.read_seed_batch(
                context=context,
                seed_links=[{"label": "", "href": detail_url}],
                follow_related_graphic_novels=follow_related_graphic_novels,
                timeout_ms=timeout_ms,
                processed_detail_keys=processed_detail_keys,
            )

        self.stdout.write(f"Detail pages read: {len(details)}")

        return self.write_detail_batch(
            details=details,
            dry_run=dry_run,
            verbose=verbose,
        )

    def sync_browse_pages(
        self,
        *,
        start_page,
        page_count,
        follow_related_graphic_novels,
        dry_run,
        headed,
        timeout_ms,
        verbose,
    ):
        total = DcWriteResult()
        processed_detail_keys = set()

        with dc_browser_context(headed=headed) as context:
            for page_number in range(start_page, start_page + page_count):
                browse_result = read_browse_page(
                    context=context,
                    page_number=page_number,
                    timeout_ms=timeout_ms,
                )

                self.stdout.write(
                    f"Browse page {page_number}: "
                    f"{len(browse_result.detail_links)} detail URLs found "
                    f"(marker={'yes' if browse_result.browse_marker_found else 'no'})"
                )

                details = self.read_seed_batch(
                    context=context,
                    seed_links=browse_result.detail_links,
                    follow_related_graphic_novels=follow_related_graphic_novels,
                    timeout_ms=timeout_ms,
                    processed_detail_keys=processed_detail_keys,
                )

                self.stdout.write(f"Browse page {page_number}: {len(details)} detail pages read")

                page_result = self.write_detail_batch(
                    details=details,
                    dry_run=dry_run,
                    verbose=verbose,
                )
                add_results(total, page_result)

                self.stdout.write(
                    f"Browse page {page_number}: batch complete "
                    f"(runs +{page_result.runs_created}/~{page_result.runs_updated}, "
                    f"issues +{page_result.issues_created}/~{page_result.issues_updated}, "
                    f"volumes +{page_result.volumes_created}/~{page_result.volumes_updated}, "
                    f"one-shots +{page_result.one_shots_created}/~{page_result.one_shots_updated}, "
                    f"skipped {page_result.skipped})"
                )

                details.clear()

        return total

    def read_seed_batch(
        self,
        *,
        context,
        seed_links,
        follow_related_graphic_novels,
        timeout_ms,
        processed_detail_keys,
    ):
        details = []
        detail_by_url = {}
        scanned_seed_urls = set()
        discovered_urls = deque()
        discovered_keys = set()

        for seed_link in seed_links:
            seed_url = clean_text(seed_link.get("href"))

            if not seed_url:
                continue

            seed_key = normalize_url_for_compare(seed_url)

            if seed_key in scanned_seed_urls or seed_key in processed_detail_keys:
                continue

            scanned_seed_urls.add(seed_key)

            seed_detail = read_detail_page(
                context=context,
                url=seed_url,
                timeout_ms=timeout_ms,
                scan_more_from_series=True,
            )

            stored_seed = self.store_detail(
                details=details,
                detail_by_url=detail_by_url,
                processed_detail_keys=processed_detail_keys,
                detail=seed_detail,
            )

            if not stored_seed:
                continue

            series_map_links = seed_detail.more_from_series_links

            for link in series_map_links:
                if is_graphic_novel_link(link) and not follow_related_graphic_novels:
                    continue

                self.enqueue_url(
                    queue=discovered_urls,
                    queued_keys=discovered_keys,
                    processed_detail_keys=processed_detail_keys,
                    url=link.get("href"),
                )

            while discovered_urls:
                url = discovered_urls.popleft()
                key = normalize_url_for_compare(url)

                if key in processed_detail_keys or key in detail_by_url:
                    continue

                detail = read_detail_page(
                    context=context,
                    url=url,
                    timeout_ms=timeout_ms,
                    scan_more_from_series=False,
                    known_more_from_series_links=series_map_links,
                )

                self.store_detail(
                    details=details,
                    detail_by_url=detail_by_url,
                    processed_detail_keys=processed_detail_keys,
                    detail=detail,
                )

        return details

    def store_detail(self, *, details, detail_by_url, processed_detail_keys, detail):
        key = normalize_url_for_compare(detail.final_url)

        if not key:
            return False

        if key in detail_by_url or key in processed_detail_keys:
            return False

        detail_by_url[key] = detail
        processed_detail_keys.add(key)
        details.append(detail)
        return True

    def enqueue_url(self, *, queue, queued_keys, processed_detail_keys, url):
        url = clean_text(url)

        if not url:
            return

        key = normalize_url_for_compare(url)

        if key in queued_keys or key in processed_detail_keys:
            return

        queued_keys.add(key)
        queue.append(url)

    def write_detail_batch(self, *, details, dry_run, verbose):
        total = DcWriteResult()

        for detail in sort_details_for_writing(details):
            result = write_dc_detail(
                detail=detail,
                dry_run=dry_run,
            )
            add_results(total, result)

            if verbose or result.skipped:
                self.print_detail_result(detail=detail, result=result)

        return total

    def print_header(
        self,
        *,
        start_page,
        page_count,
        detail_url,
        follow_related_graphic_novels,
        dry_run,
        headed,
        timeout_ms,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("DC comics sync"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'write'}")
        self.stdout.write("Source: https://www.dc.com/comics")
        self.stdout.write(f"Start page: {start_page}")
        self.stdout.write(f"Page count: {page_count}")
        self.stdout.write(f"Specific detail URL: {detail_url or 'none'}")
        self.stdout.write(
            "Related graphic novels: "
            + ("follow" if follow_related_graphic_novels else "skip")
        )
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Timeout: {timeout_ms} ms")

        if detail_url:
            self.stdout.write("Browse behavior: skipped for direct detail URL")
            self.stdout.write("Database behavior: write one direct-detail batch after reading")
        else:
            self.stdout.write("Browse behavior: collect seed URLs from Browse Comics")
            self.stdout.write("Database behavior: write and clear each browse page batch before continuing")

        self.stdout.write("Series map behavior: scan More From This Series once per seed")
        self.stdout.write("Discovered detail behavior: read item details only, no carousel rescan")
        self.stdout.write("Volume matching: use explicit collected issue ranges only")
        self.stdout.write("Duplicate behavior: keep a small URL set to avoid repeat detail reads across pages")
        self.stdout.write("")

    def print_detail_result(self, *, detail, result):
        identity = run_identity_from_detail(detail)
        status = run_status_from_detail(detail)
        skip_reason = detail_skip_reason(detail)

        self.stdout.write("")

        if result.skipped:
            self.stdout.write(self.style.WARNING(f"SKIPPED: {detail.title or detail.final_url}"))
        else:
            self.stdout.write(detail.title or detail.final_url)

        self.stdout.write(f"  Type: {detail.item_type or 'unknown'}")
        self.stdout.write(f"  Classification: {detail.classification}")

        if skip_reason:
            self.stdout.write(f"  Skip reason: {skip_reason}")

        if identity.title:
            self.stdout.write(
                "  Run parsed: "
                f"{identity.title}"
                f"{f' ({identity.start_year})' if identity.start_year else ''}"
                f" | status={status}"
            )
        else:
            self.stdout.write("  Run parsed: none")

        self.stdout.write(f"  Series raw: {detail.series.raw or 'none'}")
        self.stdout.write(f"  Issue number: {detail.issue_key or detail.issue_number or 'none'}")
        self.stdout.write(
            "  More From This Series scan: "
            + ("yes" if detail.scanned_more_from_series else "no")
        )
        self.stdout.write(f"  Source URL: {detail.final_url}")

        if detail.candidate_issue_links:
            self.stdout.write(f"  Series issue links available: {len(detail.candidate_issue_links)}")

        if detail.related_graphic_novel_links:
            self.stdout.write(
                f"  Related graphic novel links available: {len(detail.related_graphic_novel_links)}"
            )

        self.stdout.write(
            "  Changes: "
            f"runs +{result.runs_created}/~{result.runs_updated}, "
            f"issues +{result.issues_created}/~{result.issues_updated}, "
            f"volumes +{result.volumes_created}/~{result.volumes_updated}, "
            f"one-shots +{result.one_shots_created}/~{result.one_shots_updated}, "
            f"volume links +{result.volume_issues_created}, "
            f"credits +{result.credits_added}, "
            f"run stats ~{result.run_stats_updated}, "
            f"skipped {result.skipped}"
        )

        if detail.collection_parse.issue_numbers:
            self.stdout.write(
                "  Parsed collected issues: "
                + ", ".join(detail.collection_parse.issue_numbers)
            )

        if detail.collection_parse.unmatched_issue_numbers:
            self.stdout.write(
                "  Unmatched collected issues: "
                + ", ".join(detail.collection_parse.unmatched_issue_numbers)
            )

    def print_totals(self, total):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("DC sync totals"))
        self.stdout.write(f"Runs created: {total.runs_created}")
        self.stdout.write(f"Runs updated: {total.runs_updated}")
        self.stdout.write(f"Run stats updated: {total.run_stats_updated}")
        self.stdout.write(f"Issues created: {total.issues_created}")
        self.stdout.write(f"Issues updated: {total.issues_updated}")
        self.stdout.write(f"Volumes created: {total.volumes_created}")
        self.stdout.write(f"Volumes updated: {total.volumes_updated}")
        self.stdout.write(f"One-shots created: {total.one_shots_created}")
        self.stdout.write(f"One-shots updated: {total.one_shots_updated}")
        self.stdout.write(f"Volume-run links created: {total.volume_runs_created}")
        self.stdout.write(f"Volume-run links updated: {total.volume_runs_updated}")
        self.stdout.write(f"Volume-issue links created: {total.volume_issues_created}")
        self.stdout.write(f"Credits added: {total.credits_added}")
        self.stdout.write(f"Skipped: {total.skipped}")


def sort_details_for_writing(details):
    indexed_details = list(enumerate(details))
    indexed_details.sort(key=lambda item: (detail_write_priority(item[1]), item[0]))
    return [detail for _, detail in indexed_details]


def detail_write_priority(detail):
    priorities = {
        "issue": 10,
        "collected_volume": 20,
        "standalone_graphic_novel_or_one_shot": 30,
    }
    return priorities.get(detail.classification, 90)


def is_graphic_novel_link(link):
    return "/graphic-novels/" in clean_text(link.get("href"))


def normalize_url_for_compare(value):
    value = clean_text(value).rstrip("/")

    if not value:
        return ""

    return value.casefold()


def clean_text(value):
    return str(value or "").strip()