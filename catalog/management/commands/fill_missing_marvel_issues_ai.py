import json
import os
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Prefetch
from openai import OpenAI

from catalog.models import ComicIssue, ComicRun

from ._local_comicvine_helpers import (
    canonical_issue_number,
    clean_text,
    copy_complete_comicvine_issues_to_catalog_run,
    find_possible_comicvine_volume_matches,
    format_comicvine_match_line,
    is_released_from_store_date,
    normalize_issue_number,
    parse_date,
    pure_integer_issue_number,
    title_needs_repair,
)


DEFAULT_MODEL = "gpt-5.5"
DEFAULT_PUBLISHER_NAME = "Marvel"


ISSUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "issue_number": {"type": "string"},
        "title": {"type": ["string", "null"]},
        "store_date": {"type": ["string", "null"]},
        "cover_date": {"type": ["string", "null"]},
    },
    "required": [
        "issue_number",
        "title",
        "store_date",
        "cover_date",
    ],
}


BROAD_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "issues": {
            "type": "array",
            "items": ISSUE_SCHEMA,
        },
    },
    "required": ["issues"],
}


REPAIR_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verified_issue_count": {"type": ["integer", "null"]},
        "issues": {
            "type": "array",
            "items": ISSUE_SCHEMA,
        },
    },
    "required": [
        "verified_issue_count",
        "issues",
    ],
}


class Command(BaseCommand):
    help = (
        "Fill or repair catalog issues for Marvel runs using local Comic Vine data first, "
        "then OpenAI web search only if needed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            default=os.getenv("OPENAI_MARVEL_PROBE_MODEL", DEFAULT_MODEL),
            help=f"OpenAI model to use. Default: {DEFAULT_MODEL}",
        )
        parser.add_argument(
            "--publisher",
            default=DEFAULT_PUBLISHER_NAME,
            help=f"Publisher name to scan. Default: {DEFAULT_PUBLISHER_NAME}",
        )
        parser.add_argument(
            "--run-id",
            type=int,
            help="Only check one catalog ComicRun ID.",
        )
        parser.add_argument(
            "--issue-numbers",
            help="Comma-separated issue numbers to target, such as 3,4,5. Requires --run-id.",
        )
        parser.add_argument(
            "--limit-runs",
            type=int,
            default=1,
            help="Maximum number of runs to process. Default: 1",
        )
        parser.add_argument(
            "--search-context",
            choices=["low", "medium", "high"],
            default="medium",
            help="Web-search context used for every OpenAI check. Default: medium",
        )
        parser.add_argument(
            "--skip-comicvine-match",
            action="store_true",
            help="Skip the local Comic Vine match prompt and go straight to OpenAI if needed.",
        )
        parser.add_argument(
            "--comicvine-match-limit",
            type=int,
            default=8,
            help="Maximum local Comic Vine volume matches to show. Default: 8",
        )
        parser.add_argument(
            "--skip-repair-pass",
            action="store_true",
            help="Do not make the batch issue-count verification and repair call.",
        )
        parser.add_argument(
            "--include-upcoming",
            action="store_true",
            help="Allow searches for future upcoming runs.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not create or update catalog data.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print raw JSON responses. Does not make additional API calls.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print every issue candidate and database action.",
        )

    def handle(self, *args, **options):
        publisher_name = clean_text(options["publisher"]) or DEFAULT_PUBLISHER_NAME
        run_id = options.get("run_id")
        forced_issue_numbers = parse_issue_numbers_argument(options.get("issue_numbers"))
        limit_runs = options["limit_runs"]
        comicvine_match_limit = options["comicvine_match_limit"]

        if forced_issue_numbers and not run_id:
            raise CommandError("--issue-numbers requires --run-id.")

        if limit_runs < 1:
            raise CommandError("--limit-runs must be at least 1.")

        if comicvine_match_limit < 1:
            raise CommandError("--comicvine-match-limit must be at least 1.")

        runs = self.get_runs_to_check(
            publisher_name=publisher_name,
            run_id=run_id,
            limit_runs=limit_runs,
            forced_issue_numbers=forced_issue_numbers,
            include_upcoming=options["include_upcoming"],
            dry_run=options["dry_run"],
        )

        self.write_header(
            dry_run=options["dry_run"],
            model=options["model"],
            publisher_name=publisher_name,
            search_context=options["search_context"],
            skip_comicvine_match=options["skip_comicvine_match"],
            comicvine_match_limit=comicvine_match_limit,
            skip_repair_pass=options["skip_repair_pass"],
            include_upcoming=options["include_upcoming"],
            run_id=run_id,
            forced_issue_numbers=forced_issue_numbers,
            limit_runs=limit_runs,
            runs=runs,
        )

        if not runs:
            self.stdout.write(
                self.style.SUCCESS(
                    "No runs need issue filling or repair. No OpenAI calls were made."
                )
            )
            return

        totals = {
            "ai_created": 0,
            "ai_updated": 0,
            "ai_skipped": 0,
            "api_calls": 0,
            "issue_count_corrections": 0,
            "local_created": 0,
            "local_updated": 0,
        }

        client = None

        for run in runs:
            existing_issues = get_existing_issues(run)
            target_issue_numbers = build_effective_target_issue_numbers(
                run=run,
                existing_issues=existing_issues,
                forced_issue_numbers=forced_issue_numbers,
            )

            if not target_issue_numbers:
                continue

            self.print_run_check(
                run=run,
                existing_issues=existing_issues,
                target_issue_numbers=target_issue_numbers,
            )

            if not options["skip_comicvine_match"]:
                local_result = self.handle_local_comicvine_before_api(
                    run=run,
                    publisher_name=publisher_name,
                    comicvine_match_limit=comicvine_match_limit,
                    dry_run=options["dry_run"],
                    verbose=options["verbose"],
                )

                totals["local_created"] += local_result["created"]
                totals["local_updated"] += local_result["updated"]

                existing_issues = get_existing_issues(run)
                target_issue_numbers = build_effective_target_issue_numbers(
                    run=run,
                    existing_issues=existing_issues,
                    forced_issue_numbers=forced_issue_numbers,
                )

                if not target_issue_numbers:
                    self.stdout.write("")
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Local Comic Vine data filled all target issues. "
                            "No OpenAI calls were made for this run."
                        )
                    )
                    continue

                if local_result["selected"]:
                    self.stdout.write("")
                    self.stdout.write(
                        "Targets still needing OpenAI after local Comic Vine check: "
                        + ", ".join(target_issue_numbers)
                    )

            client = self.get_openai_client(
                api_key=os.getenv("OPENAI_API_KEY"),
                existing_client=client,
            )

            issue_candidates, verified_issue_count, api_calls = self.run_openai_issue_fill(
                client=client,
                model=options["model"],
                search_context=options["search_context"],
                run=run,
                existing_issues=existing_issues,
                target_issue_numbers=target_issue_numbers,
                skip_repair_pass=options["skip_repair_pass"],
                print_raw=options["raw"],
                dry_run=options["dry_run"],
            )

            totals["api_calls"] += api_calls

            if verified_issue_count is not None:
                changed = self.reconcile_run_issue_count(
                    run=run,
                    verified_issue_count=verified_issue_count,
                    dry_run=options["dry_run"],
                )

                if changed:
                    totals["issue_count_corrections"] += 1

                issue_candidates = filter_candidates_by_issue_count(
                    candidates=issue_candidates,
                    verified_issue_count=verified_issue_count,
                )

            self.print_result(
                run=run,
                issues=issue_candidates,
                verified_issue_count=verified_issue_count,
                verbose=options["verbose"],
            )

            if options["dry_run"]:
                continue

            created_count, updated_count, skipped_count = self.apply_issues(
                run=run,
                candidates=issue_candidates,
                existing_issue_map=build_existing_issue_map(get_existing_issues(run)),
                verbose=options["verbose"],
            )

            totals["ai_created"] += created_count
            totals["ai_updated"] += updated_count
            totals["ai_skipped"] += skipped_count

        self.print_summary(totals=totals, dry_run=options["dry_run"])

    def get_openai_client(self, *, api_key, existing_client):
        if existing_client is not None:
            return existing_client

        if not api_key:
            raise CommandError(
                "OPENAI_API_KEY is not set. Local Comic Vine did not fill everything, "
                "so OpenAI search is required."
            )

        return OpenAI(api_key=api_key)

    def get_runs_to_check(
        self,
        *,
        publisher_name,
        run_id,
        limit_runs,
        forced_issue_numbers,
        include_upcoming,
        dry_run,
    ):
        issue_queryset = ComicIssue.objects.only(
            "id",
            "run_id",
            "issue_number",
            "title",
            "store_date",
            "cover_date",
            "is_released",
        )

        runs = (
            ComicRun.objects.select_related("publisher")
            .prefetch_related(
                Prefetch(
                    "issues",
                    queryset=issue_queryset,
                )
            )
            .annotate(attached_issue_count=Count("issues", distinct=True))
            .filter(publisher__name__iexact=publisher_name)
            .exclude(issue_count__isnull=True)
            .order_by("title", "start_year", "id")
        )

        if run_id:
            runs = runs.filter(id=run_id)

        runs_to_check = []

        for run in runs:
            should_skip_upcoming = normalize_run_status_before_issue_fill(
                run=run,
                dry_run=dry_run,
            )

            if should_skip_upcoming and not include_upcoming:
                continue

            if forced_issue_numbers:
                runs_to_check.append(run)
                break

            existing_issues = list(run.issues.all())

            has_missing_issues = (
                run.issue_count is not None
                and run.attached_issue_count < run.issue_count
            )
            has_incomplete_issues = any(
                existing_issue_needs_repair(issue)
                for issue in existing_issues
            )

            if not has_missing_issues and not has_incomplete_issues:
                continue

            runs_to_check.append(run)

            if len(runs_to_check) >= limit_runs:
                break

        return runs_to_check

    def write_header(
        self,
        *,
        dry_run,
        model,
        publisher_name,
        search_context,
        skip_comicvine_match,
        comicvine_match_limit,
        skip_repair_pass,
        include_upcoming,
        run_id,
        forced_issue_numbers,
        limit_runs,
        runs,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Fill/repair missing Marvel issues"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write("Source order: local Comic Vine first, OpenAI only if still needed")
        self.stdout.write(
            "Catalog writes: "
            f"{'none' if dry_run else 'ComicRun issue_count and ComicIssue rows'}"
        )
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Publisher: {publisher_name}")
        self.stdout.write(f"Search context for all OpenAI checks: {search_context}")
        self.stdout.write(
            "Local Comic Vine pre-check: "
            f"{'off' if skip_comicvine_match else 'on'}"
        )
        self.stdout.write(f"Local Comic Vine match display limit: {comicvine_match_limit}")
        self.stdout.write(
            "Batch count verification and repair: "
            f"{'off' if skip_repair_pass else 'on'}"
        )
        self.stdout.write("Maximum OpenAI API calls per run after local check: 2")
        self.stdout.write(
            "Include future upcoming runs: "
            f"{'yes' if include_upcoming else 'no'}"
        )
        self.stdout.write(f"Run ID filter: {run_id or 'none'}")
        self.stdout.write(
            "Issue number filter: "
            f"{', '.join(forced_issue_numbers) if forced_issue_numbers else 'none'}"
        )
        self.stdout.write(f"Run limit: {limit_runs}")
        self.stdout.write(f"Runs needing fill/repair: {len(runs)}")
        self.stdout.write("")

    def print_run_check(self, *, run, existing_issues, target_issue_numbers):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"Checking run: {run}"))
        self.stdout.write(f"Catalog issue_count: {run.issue_count}")
        self.stdout.write(f"Existing attached issues: {len(existing_issues)}")
        self.stdout.write(
            "Existing incomplete issues: "
            f"{count_incomplete_existing_issues(existing_issues)}"
        )
        self.stdout.write("Target issues: " + ", ".join(target_issue_numbers))
        self.stdout.write("")

    def handle_local_comicvine_before_api(
        self,
        *,
        run,
        publisher_name,
        comicvine_match_limit,
        dry_run,
        verbose,
    ):
        empty_result = {
            "selected": False,
            "created": 0,
            "updated": 0,
        }

        matches = find_possible_comicvine_volume_matches(
            title=run.title,
            start_year=run.start_year,
            publisher_name=publisher_name,
            limit=comicvine_match_limit,
        )

        if not matches:
            self.stdout.write(
                self.style.WARNING(
                    f"No likely local Comic Vine volume matches for {run.title} "
                    f"({run.start_year or 'unknown year'})."
                )
            )
            return empty_result

        self.stdout.write(
            self.style.WARNING(
                f"Possible local Comic Vine matches for {run.title} "
                f"({run.start_year or 'unknown year'}):"
            )
        )

        for index, match in enumerate(matches, start=1):
            self.stdout.write(format_comicvine_match_line(index=index, match=match))

        if dry_run:
            self.stdout.write("Dry run: local Comic Vine issues were not copied.")
            return empty_result

        selected_volume = self.get_selected_comicvine_volume(matches)

        if selected_volume is None:
            self.stdout.write("Skipped local Comic Vine issue copy. Continuing to OpenAI search.")
            return empty_result

        result = copy_complete_comicvine_issues_to_catalog_run(
            catalog_run=run,
            comicvine_volume=selected_volume,
            verbose=verbose,
            raise_issue_count=True,
        )

        self.print_local_copy_result(
            selected_volume=selected_volume,
            result=result,
        )

        return {
            "selected": True,
            "created": result["created"],
            "updated": result["updated"],
        }

    def get_selected_comicvine_volume(self, matches):
        self.stdout.write("0. Skip local Comic Vine issue copy")
        choice = input("Select Comic Vine volume to copy issues from before OpenAI search: ").strip()

        if choice in ["", "0"]:
            return None

        try:
            selected_index = int(choice)
        except ValueError:
            self.stdout.write(self.style.WARNING("Invalid selection."))
            return None

        if selected_index < 1 or selected_index > len(matches):
            self.stdout.write(self.style.WARNING("Invalid selection."))
            return None

        return matches[selected_index - 1]["volume"]

    def print_local_copy_result(self, *, selected_volume, result):
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Local Comic Vine issue copy complete from {selected_volume.name} "
                f"[comicvine_id={selected_volume.comicvine_id}]"
            )
        )
        self.stdout.write("API calls made for local issue copy: 0")
        self.stdout.write(f"Source issues checked: {result['checked']}")
        self.stdout.write(f"Created catalog issues: {result['created']}")
        self.stdout.write(f"Updated catalog issues: {result['updated']}")
        self.stdout.write(f"Already complete catalog issues: {result['unchanged']}")
        self.stdout.write(f"Skipped source issues: {result['skipped']}")

        if result["issue_count_updated"]:
            self.stdout.write(
                self.style.WARNING(
                    "Catalog issue_count raised from "
                    f"{result['old_issue_count']} to {result['new_issue_count']} "
                    "based on selected local Comic Vine issue rows."
                )
            )

        if result["skipped_reasons"]:
            self.stdout.write("Skipped reason counts:")

            for reason, count in sorted(result["skipped_reasons"].items()):
                self.stdout.write(f"- {reason}: {count}")

        for message in result["messages"]:
            self.stdout.write(message)

    def run_openai_issue_fill(
        self,
        *,
        client,
        model,
        search_context,
        run,
        existing_issues,
        target_issue_numbers,
        skip_repair_pass,
        print_raw,
        dry_run,
    ):
        broad_data = self.call_broad_issue_search(
            client=client,
            model=model,
            search_context=search_context,
            run=run,
            target_issue_numbers=target_issue_numbers,
        )
        api_calls = 1

        if print_raw:
            self.stdout.write(self.style.WARNING("Raw broad JSON"))
            self.stdout.write(json.dumps(broad_data, indent=2, ensure_ascii=False))
            self.stdout.write("")

        issue_candidates = ensure_candidates_for_targets(
            candidates=normalize_candidate_list(broad_data.get("issues", [])),
            target_issue_numbers=target_issue_numbers,
        )

        repair_targets = find_repair_targets(issue_candidates)
        verified_issue_count = None

        if repair_targets and skip_repair_pass:
            self.stdout.write(
                self.style.WARNING(
                    "Skipped batch issue-count verification and repair for "
                    f"{len(repair_targets)} incomplete issue(s)."
                )
            )
            return issue_candidates, verified_issue_count, api_calls

        if repair_targets:
            self.stdout.write(
                self.style.WARNING(
                    "One batch issue-count verification and repair call needed for "
                    f"{len(repair_targets)} incomplete issue(s)."
                )
            )

            repair_data = self.call_batch_repair_search(
                client=client,
                model=model,
                search_context=search_context,
                run=run,
                existing_issues=existing_issues,
                repair_targets=repair_targets,
            )
            api_calls += 1

            if print_raw:
                self.stdout.write(self.style.WARNING("Raw batch repair JSON"))
                self.stdout.write(json.dumps(repair_data, indent=2, ensure_ascii=False))
                self.stdout.write("")

            verified_issue_count = parse_verified_issue_count(
                repair_data.get("verified_issue_count")
            )
            issue_candidates = merge_issue_candidates(
                base_candidates=issue_candidates,
                repair_candidates=normalize_candidate_list(repair_data.get("issues", [])),
            )

        return issue_candidates, verified_issue_count, api_calls

    def call_broad_issue_search(
        self,
        *,
        client,
        model,
        search_context,
        run,
        target_issue_numbers,
    ):
        try:
            response = client.responses.create(
                model=model,
                reasoning={"effort": "low"},
                tools=[
                    {
                        "type": "web_search",
                        "search_context_size": search_context,
                    }
                ],
                tool_choice="required",
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Find confirmed comic issue metadata. "
                            "Return compact JSON matching the schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_broad_prompt(
                            run=run,
                            target_issue_numbers=target_issue_numbers,
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "marvel_issue_search",
                        "strict": True,
                        "schema": BROAD_RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI issue search failed for {run}: {exc}") from exc

        return parse_response_json(response.output_text)

    def call_batch_repair_search(
        self,
        *,
        client,
        model,
        search_context,
        run,
        existing_issues,
        repair_targets,
    ):
        try:
            response = client.responses.create(
                model=model,
                reasoning={"effort": "low"},
                tools=[
                    {
                        "type": "web_search",
                        "search_context_size": search_context,
                    }
                ],
                tool_choice="required",
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Verify a comic run issue count and fill missing issue metadata. "
                            "Return compact JSON matching the schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_repair_prompt(
                            run=run,
                            existing_issues=existing_issues,
                            repair_targets=repair_targets,
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "marvel_issue_count_and_repair",
                        "strict": True,
                        "schema": REPAIR_RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI batch repair failed for {run}: {exc}") from exc

        return parse_response_json(response.output_text)

    def reconcile_run_issue_count(self, *, run, verified_issue_count, dry_run):
        old_issue_count = run.issue_count

        if old_issue_count == verified_issue_count:
            self.stdout.write(f"Verified issue_count: {verified_issue_count}")
            return False

        attached_issue_count = run.issues.count()

        self.stdout.write(
            self.style.WARNING(
                f"Issue-count correction: {old_issue_count} -> {verified_issue_count}"
            )
        )

        if verified_issue_count < attached_issue_count:
            self.stdout.write(
                self.style.WARNING(
                    f"Catalog already contains {attached_issue_count} attached issue rows. "
                    "Existing rows are not deleted."
                )
            )

        run.issue_count = verified_issue_count

        if not dry_run:
            run.save(update_fields=["issue_count", "updated_at"])

        return True

    def print_result(self, *, run, issues, verified_issue_count, verbose):
        ready_count = sum(1 for issue in issues if candidate_has_required_fields(issue))
        incomplete_numbers = [
            f"#{issue.get('issue_number') or '?'}"
            for issue in issues
            if not candidate_has_required_fields(issue)
        ]

        self.stdout.write("")

        if verified_issue_count is not None:
            self.stdout.write(f"Verified run issue_count: {verified_issue_count}")

        self.stdout.write(
            "Issue candidates after OpenAI search and repair: "
            f"{len(issues)} ({ready_count} ready, {len(incomplete_numbers)} incomplete)"
        )

        if incomplete_numbers:
            self.stdout.write("Incomplete: " + ", ".join(incomplete_numbers))

        if not verbose:
            return

        self.stdout.write("")

        for index, issue in enumerate(issues, start=1):
            issue_number = issue.get("issue_number") or "?"
            missing_fields = get_missing_candidate_fields(issue)

            self.stdout.write(f"{index}. {run.title} #{issue_number}")
            self.stdout.write(f"   Title: {issue.get('title') or '[blank]'}")
            self.stdout.write(f"   Store date: {issue.get('store_date') or 'unknown'}")
            self.stdout.write(f"   Cover date: {issue.get('cover_date') or 'unknown'}")

            if missing_fields:
                self.stdout.write("   Still missing: " + ", ".join(missing_fields))
            else:
                self.stdout.write("   Ready to write: yes")

            self.stdout.write("")

    def apply_issues(self, *, run, candidates, existing_issue_map, verbose):
        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for candidate in candidates:
                issue_number = canonical_issue_number(candidate.get("issue_number"))
                normalized_issue_number = normalize_issue_number(issue_number)

                if not candidate_has_required_fields(candidate):
                    skipped_count += 1
                    continue

                existing_issue = existing_issue_map.get(normalized_issue_number)

                if existing_issue:
                    changed = update_existing_issue_from_candidate(
                        issue=existing_issue,
                        candidate=candidate,
                    )

                    if changed:
                        existing_issue.save()
                        updated_count += 1

                        if verbose:
                            self.stdout.write(
                                self.style.SUCCESS(f"Updated ComicIssue: {existing_issue}")
                            )
                    else:
                        skipped_count += 1

                    continue

                issue = ComicIssue.objects.create(
                    run=run,
                    issue_number=issue_number,
                    title=clean_text(candidate.get("title")),
                    store_date=parse_date(candidate.get("store_date")),
                    cover_date=parse_date(candidate.get("cover_date")),
                    is_released=calculate_is_released(candidate),
                    description="",
                )

                existing_issue_map[normalized_issue_number] = issue
                created_count += 1

                if verbose:
                    self.stdout.write(
                        self.style.SUCCESS(f"Created ComicIssue: {issue}")
                    )

        return created_count, updated_count, skipped_count

    def print_summary(self, *, totals, dry_run):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Issue fill/repair complete."))
        self.stdout.write(f"OpenAI API calls made: {totals['api_calls']}")
        self.stdout.write(f"Local Comic Vine issues created: {totals['local_created']}")
        self.stdout.write(f"Local Comic Vine issues updated: {totals['local_updated']}")
        self.stdout.write(f"Run issue-count corrections: {totals['issue_count_corrections']}")
        self.stdout.write(f"AI-created issues: {totals['ai_created']}")
        self.stdout.write(f"AI-updated issues: {totals['ai_updated']}")
        self.stdout.write(f"Skipped AI candidates: {totals['ai_skipped']}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog data was created or updated.")


def get_existing_issues(run):
    return list(
        run.issues.order_by(
            "store_date",
            "issue_number",
            "id",
        )
    )


def build_existing_issue_map(existing_issues):
    return {
        normalize_issue_number(issue.issue_number): issue
        for issue in existing_issues
    }


def build_effective_target_issue_numbers(*, run, existing_issues, forced_issue_numbers):
    if forced_issue_numbers:
        return build_forced_target_issue_numbers(
            forced_issue_numbers=forced_issue_numbers,
            existing_issues=existing_issues,
        )

    return build_target_issue_numbers(
        run=run,
        existing_issues=existing_issues,
    )


def build_forced_target_issue_numbers(*, forced_issue_numbers, existing_issues):
    existing_issue_map = build_existing_issue_map(existing_issues)
    target_issue_numbers = []

    for issue_number in forced_issue_numbers:
        existing_issue = existing_issue_map.get(normalize_issue_number(issue_number))

        if existing_issue is None or existing_issue_needs_repair(existing_issue):
            target_issue_numbers.append(issue_number)

    return sort_issue_numbers(unique_issue_numbers(target_issue_numbers))


def build_broad_prompt(*, run, target_issue_numbers):
    target_text = ", ".join(
        canonical_issue_number(number)
        for number in target_issue_numbers
    )

    return f"""
Comic run: {run.publisher.name} — {run.title} ({run.start_year or "unknown"})
Issue numbers: {target_text}

Find each issue's individual title, on-sale date, and cover date.

Rules:
- Match this publisher, run, year, and issue number.
- Return one object per requested issue number.
- Dates must use YYYY-MM-DD.
- If cover date is only month/year, use that month's first day.
""".strip()


def build_repair_prompt(*, run, existing_issues, repair_targets):
    existing_numbers = ", ".join(
        canonical_issue_number(issue.issue_number)
        for issue in existing_issues
    ) or "none"

    target_text = "\n".join(
        format_repair_target(target)
        for target in repair_targets
    )

    return f"""
Current date: {date.today().isoformat()}
Comic run: {run.publisher.name} — {run.title} ({run.start_year or "unknown"})
Catalog issue_count: {run.issue_count}
Existing catalog issue numbers: {existing_numbers}

Incomplete issue candidates:
{target_text}

First verify the released or officially solicited numbered issue count for this exact run and return it as verified_issue_count.

Then return metadata only for listed candidates that actually exist within verified_issue_count.

Rules:
- Keep known values unless a better confirmed value is found.
- Do not return candidates above verified_issue_count.
- Dates must use YYYY-MM-DD.
- If cover date is only month/year, use that month's first day.
""".strip()


def format_repair_target(target):
    issue_number = canonical_issue_number(target["issue_number"])
    missing_fields = ",".join(target["missing_fields"])

    return (
        f"{issue_number}: "
        f"title={target.get('title') or 'null'}; "
        f"store_date={target.get('store_date') or 'null'}; "
        f"cover_date={target.get('cover_date') or 'null'}; "
        f"find={missing_fields}"
    )


def normalize_run_status_before_issue_fill(*, run, dry_run):
    today = date.today()
    upcoming_status = getattr(ComicRun, "STATUS_UPCOMING", "upcoming")
    ongoing_status = getattr(ComicRun, "STATUS_ONGOING", "ongoing")
    attached_issue_count = getattr(run, "attached_issue_count", None)

    if attached_issue_count is None:
        attached_issue_count = run.issues.count()

    if (
        run.first_issue_date is not None
        and run.first_issue_date > today
        and attached_issue_count == 0
    ):
        if run.status != upcoming_status:
            run.status = upcoming_status

            if not dry_run:
                run.save(update_fields=["status", "updated_at"])

        return True

    if run.status == upcoming_status:
        if run.first_issue_date is None or run.first_issue_date > today:
            return True

        run.status = ongoing_status

        if not dry_run:
            run.save(update_fields=["status", "updated_at"])

    return False


def build_target_issue_numbers(*, run, existing_issues):
    existing_issue_numbers = {
        normalize_issue_number(issue.issue_number)
        for issue in existing_issues
    }

    issue_numbers = []

    if run.issue_count:
        for number in range(1, run.issue_count + 1):
            issue_number = str(number)

            if normalize_issue_number(issue_number) not in existing_issue_numbers:
                issue_numbers.append(issue_number)

    for issue in existing_issues:
        issue_number = canonical_issue_number(issue.issue_number)

        if issue_number and existing_issue_needs_repair(issue):
            issue_numbers.append(issue_number)

    return sort_issue_numbers(unique_issue_numbers(issue_numbers))


def ensure_candidates_for_targets(*, candidates, target_issue_numbers):
    candidate_map = {
        normalize_issue_number(candidate["issue_number"]): dict(candidate)
        for candidate in candidates
    }

    for issue_number in target_issue_numbers:
        canonical_number = canonical_issue_number(issue_number)
        normalized_number = normalize_issue_number(canonical_number)

        if normalized_number not in candidate_map:
            candidate_map[normalized_number] = {
                "issue_number": canonical_number,
                "title": "",
                "store_date": "",
                "cover_date": "",
            }

    return sort_candidates(candidate_map.values())


def filter_candidates_by_issue_count(*, candidates, verified_issue_count):
    filtered = []

    for candidate in candidates:
        numeric_issue_number = pure_integer_issue_number(candidate.get("issue_number"))

        if numeric_issue_number is not None and numeric_issue_number > verified_issue_count:
            continue

        filtered.append(candidate)

    return sort_candidates(filtered)


def parse_response_json(output_text):
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Could not parse model output as JSON: {exc}") from exc


def parse_verified_issue_count(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        count = int(value)
    except (TypeError, ValueError):
        return None

    if count < 1:
        return None

    return count


def normalize_candidate_list(candidates):
    normalized = {}

    for candidate in candidates:
        normalized_candidate = normalize_candidate(candidate)
        normalized_issue_number = normalize_issue_number(
            normalized_candidate["issue_number"]
        )

        if not normalized_issue_number:
            continue

        normalized[normalized_issue_number] = normalized_candidate

    return sort_candidates(normalized.values())


def normalize_candidate(candidate):
    return {
        "issue_number": canonical_issue_number(candidate.get("issue_number")),
        "title": clean_text(candidate.get("title")),
        "store_date": clean_text(candidate.get("store_date")),
        "cover_date": clean_text(candidate.get("cover_date")),
    }


def merge_issue_candidates(*, base_candidates, repair_candidates):
    merged = {
        normalize_issue_number(candidate["issue_number"]): dict(candidate)
        for candidate in base_candidates
    }

    for repair in repair_candidates:
        normalized_issue_number = normalize_issue_number(repair["issue_number"])

        if not normalized_issue_number:
            continue

        merged[normalized_issue_number] = merge_candidate(
            merged.get(normalized_issue_number, {}),
            repair,
        )

    return sort_candidates(merged.values())


def merge_candidate(base, repair):
    merged = dict(base)
    repair_issue_number = canonical_issue_number(repair.get("issue_number"))

    if repair_issue_number:
        merged["issue_number"] = repair_issue_number

    for field_name in ["title", "store_date", "cover_date"]:
        repair_value = clean_text(repair.get(field_name))

        if repair_value:
            merged[field_name] = repair_value

    return normalize_candidate(merged)


def find_repair_targets(issue_candidates):
    targets = []

    for candidate in issue_candidates:
        missing_fields = get_missing_candidate_fields(candidate)

        if not missing_fields:
            continue

        targets.append(
            {
                "issue_number": canonical_issue_number(candidate["issue_number"]),
                "title": candidate.get("title"),
                "store_date": candidate.get("store_date"),
                "cover_date": candidate.get("cover_date"),
                "missing_fields": missing_fields,
            }
        )

    return targets


def get_missing_candidate_fields(candidate):
    missing_fields = []

    if not canonical_issue_number(candidate.get("issue_number")):
        missing_fields.append("issue_number")

    if not clean_text(candidate.get("title")):
        missing_fields.append("title")

    if parse_date(candidate.get("store_date")) is None:
        missing_fields.append("store_date")

    if parse_date(candidate.get("cover_date")) is None:
        missing_fields.append("cover_date")

    return missing_fields


def candidate_has_required_fields(candidate):
    return not get_missing_candidate_fields(candidate)


def existing_issue_needs_repair(issue):
    if issue.issue_number != canonical_issue_number(issue.issue_number):
        return True

    if title_needs_repair(issue.title):
        return True

    if issue.store_date is None:
        return True

    if issue.cover_date is None:
        return True

    return False


def count_incomplete_existing_issues(issues):
    return sum(
        1
        for issue in issues
        if existing_issue_needs_repair(issue)
    )


def update_existing_issue_from_candidate(*, issue, candidate):
    changed = False
    candidate_issue_number = canonical_issue_number(candidate.get("issue_number"))

    if candidate_issue_number and issue.issue_number != candidate_issue_number:
        duplicate_exists = (
            ComicIssue.objects.filter(
                run=issue.run,
                issue_number=candidate_issue_number,
            )
            .exclude(id=issue.id)
            .exists()
        )

        if not duplicate_exists:
            issue.issue_number = candidate_issue_number
            changed = True

    candidate_title = clean_text(candidate.get("title"))

    if candidate_title and issue.title != candidate_title:
        issue.title = candidate_title
        changed = True

    candidate_store_date = parse_date(candidate.get("store_date"))

    if issue.store_date is None and candidate_store_date is not None:
        issue.store_date = candidate_store_date
        changed = True

    candidate_cover_date = parse_date(candidate.get("cover_date"))

    if issue.cover_date is None and candidate_cover_date is not None:
        issue.cover_date = candidate_cover_date
        changed = True

    calculated_is_released = calculate_is_released(candidate)

    if issue.is_released != calculated_is_released:
        issue.is_released = calculated_is_released
        changed = True

    return changed


def calculate_is_released(candidate):
    return is_released_from_store_date(
        parse_date(candidate.get("store_date"))
    )


def parse_issue_numbers_argument(value):
    if not value:
        return []

    issue_numbers = []

    for part in re.split(r"[,\s]+", value):
        issue_number = canonical_issue_number(part)

        if issue_number:
            issue_numbers.append(issue_number)

    return sort_issue_numbers(unique_issue_numbers(issue_numbers))


def unique_issue_numbers(numbers):
    seen = set()
    unique = []

    for number in numbers:
        canonical_number = canonical_issue_number(number)
        normalized_number = normalize_issue_number(canonical_number)

        if not canonical_number or normalized_number in seen:
            continue

        seen.add(normalized_number)
        unique.append(canonical_number)

    return unique


def sort_issue_numbers(numbers):
    return sorted(numbers, key=issue_number_sort_key)


def sort_candidates(candidates):
    return sorted(
        candidates,
        key=lambda candidate: issue_number_sort_key(candidate["issue_number"]),
    )


def issue_number_sort_key(value):
    value = canonical_issue_number(value)
    match = re.match(r"^(\d+)(.*)$", value)

    if not match:
        return 999999, value

    return int(match.group(1)), match.group(2)