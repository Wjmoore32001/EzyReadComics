from django.core.management.base import BaseCommand, CommandError

from catalog.dc.browser import (
    DEFAULT_TIMEOUT_MS,
    dc_browser_context,
    read_browse_page,
    read_detail_page,
)
from catalog.dc.writer import DcWriteResult, add_results, write_dc_detail


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
            help="Specific DC detail URL to sync. If omitted, detail URLs come from browse pages.",
        )
        parser.add_argument(
            "--detail-limit",
            type=int,
            default=20,
            help="Number of browse-collected detail URLs to sync. Use 0 to skip browse-derived details. Default: 20.",
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
        detail_limit = options["detail_limit"]
        follow_related_graphic_novels = options["follow_related_graphic_novels"]
        dry_run = options["dry_run"]
        headed = options["headed"]
        timeout_ms = options["timeout"]
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
            dry_run=dry_run,
            headed=headed,
            timeout_ms=timeout_ms,
        )

        total = DcWriteResult()
        seen_urls = set()

        with dc_browser_context(headed=headed) as context:
            browse_results = []

            for page_number in range(start_page, start_page + page_count):
                browse_result = read_browse_page(
                    context=context,
                    page_number=page_number,
                    timeout_ms=timeout_ms,
                )
                browse_results.append(browse_result)

                self.stdout.write(
                    f"Browse page {page_number}: "
                    f"{len(browse_result.detail_links)} detail URLs found "
                    f"(marker={'yes' if browse_result.browse_marker_found else 'no'})"
                )

            detail_urls = collect_detail_urls(
                detail_url=detail_url,
                detail_limit=detail_limit,
                browse_results=browse_results,
            )

            for url in detail_urls:
                if url.casefold() in seen_urls:
                    continue

                seen_urls.add(url.casefold())
                result = self.sync_detail_url(
                    context=context,
                    url=url,
                    timeout_ms=timeout_ms,
                    dry_run=dry_run,
                    verbose=verbose,
                )
                add_results(total, result)

                if not follow_related_graphic_novels:
                    continue

                detail = read_detail_page(
                    context=context,
                    url=url,
                    timeout_ms=timeout_ms,
                )

                for related_link in detail.related_graphic_novel_links:
                    related_url = (related_link.get("href") or "").strip()

                    if not related_url or related_url.casefold() in seen_urls:
                        continue

                    seen_urls.add(related_url.casefold())
                    related_result = self.sync_detail_url(
                        context=context,
                        url=related_url,
                        timeout_ms=timeout_ms,
                        dry_run=dry_run,
                        verbose=verbose,
                    )
                    add_results(total, related_result)

        self.print_totals(total)

    def sync_detail_url(self, *, context, url, timeout_ms, dry_run, verbose):
        detail = read_detail_page(
            context=context,
            url=url,
            timeout_ms=timeout_ms,
        )
        result = write_dc_detail(
            detail=detail,
            dry_run=dry_run,
        )

        if verbose:
            self.print_detail_result(detail=detail, result=result)

        return result

    def print_header(
        self,
        *,
        start_page,
        page_count,
        detail_url,
        detail_limit,
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
        self.stdout.write(f"Detail limit: {detail_limit}")
        self.stdout.write(
            "Related graphic novels: "
            + ("follow" if follow_related_graphic_novels else "skip")
        )
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Timeout: {timeout_ms} ms")
        self.stdout.write("Browse behavior: collect URLs only from Browse Comics")
        self.stdout.write("Detail behavior: source of truth")
        self.stdout.write("")

    def print_detail_result(self, *, detail, result):
        self.stdout.write("")
        self.stdout.write(detail.title or detail.final_url)
        self.stdout.write(f"  Type: {detail.item_type or 'unknown'}")
        self.stdout.write(f"  Classification: {detail.classification}")
        self.stdout.write(f"  Series: {detail.series.raw or 'none'}")
        self.stdout.write(f"  Issue number: {detail.issue_key or detail.issue_number or 'none'}")
        self.stdout.write(f"  Source URL: {detail.final_url}")
        self.stdout.write(
            "  Changes: "
            f"runs +{result.runs_created}/~{result.runs_updated}, "
            f"issues +{result.issues_created}/~{result.issues_updated}, "
            f"volumes +{result.volumes_created}/~{result.volumes_updated}, "
            f"one-shots +{result.one_shots_created}/~{result.one_shots_updated}, "
            f"volume links +{result.volume_issues_created}, "
            f"credits +{result.credits_added}, "
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


def collect_detail_urls(*, detail_url, detail_limit, browse_results):
    if detail_url:
        return [detail_url]

    if detail_limit == 0:
        return []

    urls = []
    seen = set()

    for result in browse_results:
        for link in result.detail_links:
            href = (link.get("href") or "").strip()

            if not href:
                continue

            key = href.casefold()

            if key in seen:
                continue

            seen.add(key)
            urls.append(href)

            if len(urls) >= detail_limit:
                return urls

    return urls