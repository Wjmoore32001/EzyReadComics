from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Max, Min

from catalog.marvel.browser import (
    DEFAULT_DETAIL_TIMEOUT_MS,
    ensure_playwright,
    marvel_browser_context,
)
from catalog.marvel.issues import (
    get_detail_value,
    get_issue_missing_fields,
    read_issue_detail_page,
)
from catalog.marvel.series import read_series_page
from catalog.marvel.sync_planner import IssueDetailPlan, build_series_sync_plan
from catalog.marvel.text import clean_text
from catalog.marvel.urls import parse_marvel_series_url
from catalog.marvel.writer import (
    WriteResult,
    find_existing_issue,
    find_existing_run,
    upsert_issue_from_series_issue,
    upsert_run_from_series,
)


class Command(BaseCommand):
    help = (
        "Sync one Marvel run directly from its Marvel.com series URL. "
        "The command creates or updates the run, loads the full series issue list, "
        "and fills missing or incomplete issue details and credits."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "series_url",
            nargs="?",
            help=(
                "Marvel series URL. If omitted, the command prompts for a URL so it can be pasted."
            ),
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=DEFAULT_DETAIL_TIMEOUT_MS,
            help=(
                "Maximum Playwright wait time in milliseconds per series or issue page. "
                f"Default: {DEFAULT_DETAIL_TIMEOUT_MS}."
            ),
        )
        parser.add_argument(
            "--rescan-existing",
            action="store_true",
            help=(
                "Reread every issue detail page, including issues whose official details are already complete."
            ),
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Open Chromium visibly instead of headless.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created or updated without changing catalog data.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print issue-level detail and write results.",
        )

    def handle(self, *args, **options):
        series_url = resolve_series_url(options.get("series_url"))
        parsed_url = parse_marvel_series_url(series_url)

        if parsed_url is None:
            raise CommandError(
                "Enter a Marvel series URL in the form "
                "https://www.marvel.com/comics/series/<id>/<slug>."
            )

        timeout_ms = options["timeout"]

        if timeout_ms < 1000:
            raise CommandError("--timeout must be at least 1000 milliseconds.")

        dry_run = options["dry_run"]
        headed = options["headed"]
        verbose = options["verbose"]
        rescan_existing = options["rescan_existing"]

        ensure_playwright()
        close_old_connections()

        self.write_header(
            series_url=series_url,
            marvel_series_id=parsed_url.marvel_id,
            timeout_ms=timeout_ms,
            dry_run=dry_run,
            headed=headed,
            rescan_existing=rescan_existing,
        )

        with marvel_browser_context(headed=headed) as context:
            series = read_series_page(
                context=context,
                series_url=series_url,
                timeout_ms=timeout_ms,
            )

        validate_series(series)
        close_old_connections()

        existing_run = find_existing_run(
            title=series.title,
            start_year=series.start_year,
            marvel_series_id=series.marvel_series_id,
        )
        series_plan = build_series_sync_plan(series)

        if rescan_existing:
            series_plan.issue_detail_plans = build_forced_issue_detail_plans(
                series=series,
                existing_run=existing_run,
            )

        self.write_series_found(
            series=series,
            existing_run=existing_run,
            detail_plans=series_plan.issue_detail_plans,
        )

        run, run_result = upsert_run_from_series(
            series=series,
            dry_run=dry_run,
        )
        totals = WriteResult()
        add_write_result(totals, run_result)

        detail_stats = new_detail_stats()
        skipped_reports = []
        reason_counts = Counter(
            issue_plan.reason
            for issue_plan in series_plan.issue_detail_plans
        )

        if series_plan.issue_detail_plans:
            self.stdout.write("")
            self.stdout.write(
                f"Reading {len(series_plan.issue_detail_plans)} issue detail page(s)..."
            )

            with marvel_browser_context(headed=headed) as context:
                for index, issue_plan in enumerate(
                    series_plan.issue_detail_plans,
                    start=1,
                ):
                    detail = read_issue_detail_page(
                        context=context,
                        issue=issue_plan.series_issue,
                        timeout_ms=timeout_ms,
                    )
                    update_detail_stats(detail_stats, detail)

                    if should_skip_new_issue_write(
                        issue_plan=issue_plan,
                        detail=detail,
                    ):
                        skipped_reports.append(
                            build_skip_report(
                                issue_plan=issue_plan,
                                detail=detail,
                            )
                        )
                        detail_stats["issue_writes_skipped"] += 1

                        if verbose:
                            self.write_skipped_issue(
                                index=index,
                                total=len(series_plan.issue_detail_plans),
                                issue_plan=issue_plan,
                                detail=detail,
                            )
                        else:
                            self.write_progress(
                                index=index,
                                total=len(series_plan.issue_detail_plans),
                            )
                        continue

                    close_old_connections()
                    _, issue_result = upsert_issue_from_series_issue(
                        run=run,
                        series_issue=issue_plan.series_issue,
                        detail=detail,
                        dry_run=dry_run,
                    )
                    add_write_result(totals, issue_result)

                    if verbose:
                        self.write_issue_result(
                            index=index,
                            total=len(series_plan.issue_detail_plans),
                            issue_plan=issue_plan,
                            detail=detail,
                            issue_result=issue_result,
                            dry_run=dry_run,
                        )
                    else:
                        self.write_progress(
                            index=index,
                            total=len(series_plan.issue_detail_plans),
                        )
        else:
            self.stdout.write("")
            self.stdout.write("No issue detail reads are needed for this run.")

        run_dates_updated = False

        if not dry_run and run is not None:
            close_old_connections()
            run_dates_updated = refresh_run_dates(run)

        close_old_connections()
        self.write_summary(
            series=series,
            existing_run=existing_run,
            totals=totals,
            detail_stats=detail_stats,
            reason_counts=reason_counts,
            skipped_reports=skipped_reports,
            run_dates_updated=run_dates_updated,
            dry_run=dry_run,
        )

    def write_header(
        self,
        *,
        series_url,
        marvel_series_id,
        timeout_ms,
        dry_run,
        headed,
        rescan_existing,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel series sync"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write(f"Source: {series_url}")
        self.stdout.write(f"Marvel series ID: {marvel_series_id}")
        self.stdout.write("Reader: Playwright Chromium")
        self.stdout.write(f"Browser mode: {'headed' if headed else 'headless'}")
        self.stdout.write(f"Page timeout: {timeout_ms} ms")
        self.stdout.write(
            "Existing complete issue details: "
            + ("rescan" if rescan_existing else "skip")
        )

    def write_series_found(self, *, series, existing_run, detail_plans):
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Found series: {series.title} ({series.start_year})"
            )
        )
        self.stdout.write(f"Series status: {series.status}")
        self.stdout.write(f"Series URL: {series.url}")
        self.stdout.write(f"Load More clicks: {series.load_more_clicks}")
        self.stdout.write(f"Issue links found: {len(series.issues)}")

        if existing_run is None:
            self.stdout.write("Database run: not found; a new run will be created")
        else:
            self.stdout.write(
                f"Database run: matched ID {existing_run.id} ({existing_run})"
            )

        self.stdout.write(f"Issue detail pages planned: {len(detail_plans)}")

    def write_progress(self, *, index, total):
        if index == total or index == 1 or index % 10 == 0:
            self.stdout.write(f"Issue detail progress: {index}/{total}")

    def write_issue_result(
        self,
        *,
        index,
        total,
        issue_plan,
        detail,
        issue_result,
        dry_run,
    ):
        issue_text = format_series_issue(issue_plan.series_issue)
        missing_fields = get_issue_missing_fields(detail)
        action_word = "Would" if dry_run else "Did"

        self.stdout.write("")
        self.stdout.write(f"[{index}/{total}] {issue_text}")
        self.stdout.write(f"  Reason: {issue_plan.reason}")
        self.stdout.write(
            "  Detail status: "
            + ("complete" if not missing_fields else "incomplete")
        )

        if missing_fields:
            self.stdout.write("  Missing: " + ", ".join(missing_fields))

        if get_detail_value(detail, "error"):
            self.stdout.write(
                "  Detail error: " + clean_text(get_detail_value(detail, "error"))
            )

        if issue_result.issue_created:
            self.stdout.write(f"  {action_word} create issue")

        if issue_result.issue_updated:
            self.stdout.write(f"  {action_word} update issue")

        if issue_result.credits_added:
            self.stdout.write(f"  Credits added: {issue_result.credits_added}")

        if not any(
            [
                issue_result.issue_created,
                issue_result.issue_updated,
                issue_result.credits_added,
            ]
        ):
            self.stdout.write("  No database changes needed")

    def write_skipped_issue(self, *, index, total, issue_plan, detail):
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"[{index}/{total}] Skipped {format_series_issue(issue_plan.series_issue)}"
            )
        )
        self.stdout.write(f"  Planned reason: {issue_plan.reason}")
        self.stdout.write(
            "  Reason: new issue was not created because its detail page failed "
            "or did not provide a published date"
        )
        self.stdout.write(
            f"  Detail error: {clean_text(get_detail_value(detail, 'error')) or 'none'}"
        )

    def write_summary(
        self,
        *,
        series,
        existing_run,
        totals,
        detail_stats,
        reason_counts,
        skipped_reports,
        run_dates_updated,
        dry_run,
    ):
        created_label = "Would create" if dry_run else "Created"
        updated_label = "Would update" if dry_run else "Updated"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Marvel series sync complete."))
        self.stdout.write(f"Series: {series.title} ({series.start_year})")
        self.stdout.write(
            "Database match before sync: "
            + (f"run ID {existing_run.id}" if existing_run is not None else "none")
        )
        self.stdout.write(f"Series issue links found: {len(series.issues)}")
        self.stdout.write(
            f"Issue detail pages read: {detail_stats['detail_pages_read']}"
        )
        self.stdout.write(
            f"Issue detail read failures: {detail_stats['detail_read_failures']}"
        )
        self.stdout.write(
            f"Issues with complete details: {detail_stats['complete_details']}"
        )
        self.stdout.write(
            f"Issues with incomplete details: {detail_stats['incomplete_details']}"
        )
        self.stdout.write(
            f"Issues missing description: {detail_stats['missing_description']}"
        )
        self.stdout.write(
            f"Issues missing Writer: {detail_stats['missing_writer']}"
        )
        self.stdout.write(
            f"New issue writes skipped: {detail_stats['issue_writes_skipped']}"
        )
        self.stdout.write(f"{created_label} runs: {totals.run_created}")
        self.stdout.write(f"{updated_label} runs: {totals.run_updated}")
        self.stdout.write(f"{created_label} issues: {totals.issue_created}")
        self.stdout.write(f"{updated_label} issues: {totals.issue_updated}")
        self.stdout.write(f"Credits added: {totals.credits_added}")

        if not dry_run:
            self.stdout.write(
                "Run first/latest issue dates: "
                + ("updated" if run_dates_updated else "already current")
            )

        if reason_counts:
            self.stdout.write(
                "Detail read reasons: "
                + ", ".join(
                    f"{reason}: {count}"
                    for reason, count in sorted(reason_counts.items())
                )
            )

        if skipped_reports:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Skipped issue writes:"))

            for report in skipped_reports:
                self.stdout.write(f"- {report['item']}")
                self.stdout.write(f"  Reason: {report['reason']}")
                self.stdout.write(f"  URL: {report['url'] or 'none'}")

                if report["detail_error"]:
                    self.stdout.write(
                        f"  Detail error: {report['detail_error']}"
                    )

                if report["missing_fields"]:
                    self.stdout.write(
                        f"  Missing fields: {report['missing_fields']}"
                    )

        if dry_run:
            self.stdout.write("Dry run only. No catalog data was created or updated.")


def resolve_series_url(value):
    series_url = clean_text(value)

    if series_url:
        return series_url

    try:
        return clean_text(input("Paste Marvel series URL: "))
    except EOFError as exc:
        raise CommandError(
            "A Marvel series URL is required as an argument when interactive input is unavailable."
        ) from exc


def validate_series(series):
    if series.errors:
        raise CommandError("Marvel series page could not be read: " + "; ".join(series.errors))

    if not clean_text(series.title):
        raise CommandError("Marvel series page did not provide a usable series title.")

    if not clean_text(series.start_year):
        raise CommandError("Marvel series page did not provide a usable start year.")

    if not series.issues:
        raise CommandError(
            "Marvel series page did not expose any usable issue links. No database changes were made."
        )


def build_forced_issue_detail_plans(*, series, existing_run):
    plans = []

    for series_issue in series.issues:
        existing_issue = find_existing_issue(
            run=existing_run,
            issue_number=series_issue.issue_number,
            marvel_issue_id=series_issue.marvel_issue_id,
        )
        plans.append(
            IssueDetailPlan(
                series_issue=series_issue,
                existing_issue=existing_issue,
                reason="forced rescan",
            )
        )

    return plans


def should_skip_new_issue_write(*, issue_plan, detail):
    if issue_plan.existing_issue is not None:
        return False

    if get_detail_value(detail, "error"):
        return True

    if not get_detail_value(detail, "published_date"):
        return True

    return False


def build_skip_report(*, issue_plan, detail):
    return {
        "item": format_series_issue(issue_plan.series_issue),
        "reason": (
            "new issue was not created because its detail page failed "
            "or did not provide a published date"
        ),
        "url": clean_text(issue_plan.series_issue.detail_url),
        "detail_error": clean_text(get_detail_value(detail, "error")),
        "missing_fields": ", ".join(get_issue_missing_fields(detail)),
    }


def new_detail_stats():
    return {
        "detail_pages_read": 0,
        "detail_read_failures": 0,
        "complete_details": 0,
        "incomplete_details": 0,
        "missing_description": 0,
        "missing_writer": 0,
        "issue_writes_skipped": 0,
    }


def update_detail_stats(stats, detail):
    stats["detail_pages_read"] += 1

    if get_detail_value(detail, "error"):
        stats["detail_read_failures"] += 1

    missing_fields = get_issue_missing_fields(detail)

    if missing_fields:
        stats["incomplete_details"] += 1
    else:
        stats["complete_details"] += 1

    if "description" in missing_fields:
        stats["missing_description"] += 1

    if "writer" in missing_fields:
        stats["missing_writer"] += 1


def add_write_result(total, result):
    if result is None:
        return

    total.run_created += result.run_created
    total.run_updated += result.run_updated
    total.issue_created += result.issue_created
    total.issue_updated += result.issue_updated
    total.credits_added += result.credits_added


def refresh_run_dates(run):
    dates = run.issues.aggregate(
        first_issue_date=Min("published_date"),
        last_issue_date=Max("published_date"),
    )
    first_issue_date = dates["first_issue_date"]
    last_issue_date = dates["last_issue_date"]
    changed = False

    if run.first_issue_date != first_issue_date:
        run.first_issue_date = first_issue_date
        changed = True

    if run.last_issue_date != last_issue_date:
        run.last_issue_date = last_issue_date
        changed = True

    if changed:
        run.save()

    return changed


def format_series_issue(series_issue):
    return (
        f"{clean_text(series_issue.run_title)} "
        f"({clean_text(series_issue.start_year)}) "
        f"#{clean_text(series_issue.issue_number)}"
    )

