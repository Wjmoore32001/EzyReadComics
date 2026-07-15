from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

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
    help = (
        "Fast sync DC.com browse/detail comic data into the catalog. "
        "This command reads only the visible browse/detail seed URLs and does not scan More From This Series."
    )

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
        close_old_connections()

        start_page = options["page"]
        page_count = options["page_count"]
        detail_url = options["detail_url"].strip()
        dry_run = options["dry_run"]
        headed = options["headed"]
        timeout_ms = options["timeout"]
        verbose = options["verbose"]
        self.skipped_details = []

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
            dry_run=dry_run,
            headed=headed,
            timeout_ms=timeout_ms,
        )

        if detail_url:
            total = self.sync_direct_detail_url(
                detail_url=detail_url,
                dry_run=dry_run,
                headed=headed,
                timeout_ms=timeout_ms,
                verbose=verbose,
            )
        else:
            total = self.sync_browse_pages(
                start_page=start_page,
                page_count=page_count,
                dry_run=dry_run,
                headed=headed,
                timeout_ms=timeout_ms,
                verbose=verbose,
            )

        self.print_skipped_details()
        self.print_totals(total)
        close_old_connections()

    def sync_direct_detail_url(self, *, detail_url, dry_run, headed, timeout_ms, verbose):
        detail = self.read_seed_detail(
            detail_url=detail_url,
            headed=headed,
            timeout_ms=timeout_ms,
        )
        self.stdout.write("Detail pages read: 1")
        close_old_connections()

        total = self.write_detail_batch(
            details=[detail],
            dry_run=dry_run,
            verbose=verbose,
        )
        close_old_connections()
        return total

    def sync_browse_pages(self, *, start_page, page_count, dry_run, headed, timeout_ms, verbose):
        total = DcWriteResult()
        processed_detail_keys = set()

        for page_number in range(start_page, start_page + page_count):
            close_old_connections()

            browse_result = self.read_browse_page_seed_links(
                page_number=page_number,
                headed=headed,
                timeout_ms=timeout_ms,
            )
            seed_links = browse_result.detail_links
            seed_count = len(seed_links)

            self.stdout.write(
                f"Browse page {page_number}: "
                f"{seed_count} detail URLs found "
                f"(marker={'yes' if browse_result.browse_marker_found else 'no'})"
            )

            if browse_result.error:
                self.stdout.write(
                    self.style.WARNING(
                        f"Browse page {page_number}: {browse_result.error}"
                    )
                )

            page_result = DcWriteResult()
            page_details_read = 0
            page_duplicate_skipped = 0

            for seed_index, seed_link in enumerate(seed_links, start=1):
                seed_url = clean_text(seed_link.get("href"))

                if not seed_url:
                    continue

                seed_key = normalize_url_for_compare(seed_url)

                if seed_key in processed_detail_keys:
                    page_duplicate_skipped += 1
                    continue

                processed_detail_keys.add(seed_key)
                detail = self.read_seed_detail(
                    detail_url=seed_url,
                    headed=headed,
                    timeout_ms=timeout_ms,
                )
                page_details_read += 1

                close_old_connections()
                seed_result = self.write_detail_batch(
                    details=[detail],
                    dry_run=dry_run,
                    verbose=verbose,
                )
                close_old_connections()

                add_results(page_result, seed_result)

                self.stdout.write(
                    f"Browse page {page_number} [{seed_index}/{seed_count}]: "
                    f"{detail.title or detail.final_url} complete "
                    f"(runs +{seed_result.runs_created}/~{seed_result.runs_updated}, "
                    f"issues +{seed_result.issues_created}/~{seed_result.issues_updated}, "
                    f"volumes +{seed_result.volumes_created}/~{seed_result.volumes_updated}, "
                    f"one-shots +{seed_result.one_shots_created}/~{seed_result.one_shots_updated}, "
                    f"skipped {seed_result.skipped})"
                )

            add_results(total, page_result)

            self.stdout.write(
                f"Browse page {page_number}: page complete "
                f"({page_details_read} seed detail pages read, "
                f"duplicates skipped {page_duplicate_skipped}, "
                f"runs +{page_result.runs_created}/~{page_result.runs_updated}, "
                f"issues +{page_result.issues_created}/~{page_result.issues_updated}, "
                f"volumes +{page_result.volumes_created}/~{page_result.volumes_updated}, "
                f"one-shots +{page_result.one_shots_created}/~{page_result.one_shots_updated}, "
                f"skipped {page_result.skipped})"
            )

        return total

    def read_browse_page_seed_links(self, *, page_number, headed, timeout_ms):
        with dc_browser_context(headed=headed) as context:
            return read_browse_page(
                context=context,
                page_number=page_number,
                timeout_ms=timeout_ms,
            )

    def read_seed_detail(self, *, detail_url, headed, timeout_ms):
        with dc_browser_context(headed=headed) as context:
            return read_detail_page(
                context=context,
                url=detail_url,
                timeout_ms=timeout_ms,
                scan_more_from_series=False,
                known_more_from_series_links=[],
            )

    def write_detail_batch(self, *, details, dry_run, verbose):
        total = DcWriteResult()
        close_old_connections()

        for detail in sort_details_for_writing(details):
            try:
                close_old_connections()
                result = write_dc_detail(
                    detail=detail,
                    dry_run=dry_run,
                )
            except Exception as exc:
                result = DcWriteResult()
                result.skipped = 1
                self.mark_detail_write_error(detail=detail, error=exc)
                close_old_connections()

            add_results(total, result)

            if result.skipped:
                self.record_skipped_detail(detail=detail, result=result)

            if verbose or result.skipped:
                self.print_detail_result(detail=detail, result=result)

        close_old_connections()
        return total

    def mark_detail_write_error(self, *, detail, error):
        message = clean_text(error)

        if not message:
            message = error.__class__.__name__

        if hasattr(detail, "read_error"):
            detail.read_error = f"Write failed: {message}"

    def print_header(
        self,
        *,
        start_page,
        page_count,
        detail_url,
        dry_run,
        headed,
        timeout_ms,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("DC comics fast sync"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'write'}")
        self.stdout.write("Source: https://www.dc.com/comics")
        self.stdout.write(f"Start page: {start_page}")
        self.stdout.write(f"Page count: {page_count}")
        self.stdout.write(f"Specific detail URL: {detail_url or 'none'}")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Timeout: {timeout_ms} ms")

        if detail_url:
            self.stdout.write("Browse behavior: skipped for direct detail URL")
        else:
            self.stdout.write("Browse behavior: collect seed URLs from Browse Comics")

        self.stdout.write("Series expansion: off")
        self.stdout.write("More From This Series scan: off")
        self.stdout.write("Write cadence: per seed detail page")
        self.stdout.write("Duplicate behavior: keep a small URL set to avoid repeat seed reads across pages")
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
        self.stdout.write("  More From This Series scan: no")
        self.stdout.write(f"  Source URL: {detail.final_url}")

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

    def record_skipped_detail(self, *, detail, result):
        identity = run_identity_from_detail(detail)
        skip_reason = detail_skip_reason(detail) or "Write skipped this detail page."

        if identity.title:
            run_text = identity.title

            if identity.start_year:
                run_text = f"{run_text} ({identity.start_year})"
        else:
            run_text = "none"

        self.skipped_details.append(
            {
                "title": detail.title or detail.final_url,
                "type": detail.item_type or "unknown",
                "classification": detail.classification or "unknown",
                "reason": skip_reason,
                "run": run_text,
                "issue": detail.issue_key or detail.issue_number or "none",
                "url": detail.final_url,
            }
        )

    def print_skipped_details(self):
        skipped_details = getattr(self, "skipped_details", [])

        if not skipped_details:
            return

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Skipped DC detail pages"))

        for index, item in enumerate(skipped_details, start=1):
            self.stdout.write(f"{index}. {item['title']}")
            self.stdout.write(f"   Type: {item['type']}")
            self.stdout.write(f"   Classification: {item['classification']}")
            self.stdout.write(f"   Reason: {item['reason']}")
            self.stdout.write(f"   Run: {item['run']}")
            self.stdout.write(f"   Issue number: {item['issue']}")
            self.stdout.write(f"   Source URL: {item['url']}")

    def print_totals(self, total):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("DC fast sync totals"))
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


def normalize_url_for_compare(value):
    value = clean_text(value).rstrip("/")

    if not value:
        return ""

    return value.casefold()


def clean_text(value):
    return str(value or "").strip()