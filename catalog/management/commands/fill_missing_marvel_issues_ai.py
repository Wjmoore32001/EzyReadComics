import json
import os
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from openai import OpenAI

from catalog.models import ComicIssue, ComicRun


DEFAULT_MODEL = "gpt-5.5"
DEFAULT_PUBLISHER_NAME = "Marvel"


BROAD_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "issue_number": {
                        "type": "string",
                    },
                    "title": {
                        "type": ["string", "null"],
                        "description": "The confirmed issue title. Use null if not found in the broad pass.",
                    },
                    "store_date": {
                        "type": ["string", "null"],
                        "description": "On-sale/release date in YYYY-MM-DD, or null if unknown.",
                    },
                    "cover_date": {
                        "type": ["string", "null"],
                        "description": "Cover date in YYYY-MM-DD, or null if unknown. If only month/year is available, use the first day of that cover month.",
                    },
                    "is_released": {
                        "type": ["boolean", "null"],
                    },
                    "primary_source_url": {
                        "type": ["string", "null"],
                    },
                    "supporting_source_urls": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                },
                "required": [
                    "issue_number",
                    "title",
                    "store_date",
                    "cover_date",
                    "is_released",
                    "primary_source_url",
                    "supporting_source_urls",
                ],
            },
        },
    },
    "required": [
        "issues",
    ],
}


REPAIR_RESULT_SCHEMA = BROAD_RESULT_SCHEMA


class Command(BaseCommand):
    help = (
        "Fill or repair catalog issues for Marvel runs using OpenAI web search. "
        "Default mode creates/updates ComicIssue rows. Use --dry-run to print only."
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
            help="Only check one ComicRun ID.",
        )
        parser.add_argument(
            "--limit-runs",
            type=int,
            default=1,
            help="Maximum number of runs to make broad OpenAI calls for. Default: 1",
        )
        parser.add_argument(
            "--search-context",
            choices=["low", "medium", "high"],
            default="high",
            help="Search context for the broad issue search. Default: high",
        )
        parser.add_argument(
            "--repair-search-context",
            choices=["low", "medium", "high"],
            default="high",
            help="Search context for the targeted repair search. Default: high",
        )
        parser.add_argument(
            "--skip-repair-pass",
            action="store_true",
            help="Only run the broad search. Do not make targeted repair calls.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print issue candidates only. Do not create or update catalog rows.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print raw JSON for each OpenAI result. Does not make another API call.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise CommandError(
                "OPENAI_API_KEY is not set. Add it to your .env file before running this command."
            )

        model = options["model"]
        publisher_name = clean_text(options["publisher"]) or DEFAULT_PUBLISHER_NAME
        run_id = options.get("run_id")
        limit_runs = options["limit_runs"]
        search_context = options["search_context"]
        repair_search_context = options["repair_search_context"]
        skip_repair_pass = options["skip_repair_pass"]
        dry_run = options["dry_run"]
        print_raw = options["raw"]

        if limit_runs < 1:
            raise CommandError("--limit-runs must be at least 1.")

        runs = self.get_runs_to_check(
            publisher_name=publisher_name,
            run_id=run_id,
            limit_runs=limit_runs,
        )

        self.write_header(
            mode="dry run" if dry_run else "apply",
            model=model,
            publisher_name=publisher_name,
            search_context=search_context,
            repair_search_context=repair_search_context,
            skip_repair_pass=skip_repair_pass,
            run_id=run_id,
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

        client = OpenAI(api_key=api_key)

        total_created = 0
        total_updated = 0
        total_skipped = 0
        total_api_calls = 0

        for run in runs:
            existing_issues = list(run.issues.order_by("store_date", "issue_number"))
            existing_issue_map = {
                normalize_issue_number(issue.issue_number): issue
                for issue in existing_issues
            }

            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"Checking run: {run}"))
            self.stdout.write(f"Run issue_count: {run.issue_count}")
            self.stdout.write(f"Existing attached issues: {len(existing_issues)}")
            self.stdout.write(
                f"Existing incomplete issues: {count_incomplete_existing_issues(existing_issues)}"
            )
            self.stdout.write("")

            broad_data = self.call_broad_issue_search(
                client=client,
                model=model,
                search_context=search_context,
                run=run,
                existing_issues=existing_issues,
            )
            total_api_calls += 1

            if print_raw:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Raw broad JSON"))
                self.stdout.write(json.dumps(broad_data, indent=2, ensure_ascii=False))

            issue_candidates = normalize_candidate_list(broad_data.get("issues", []))
            repair_targets = find_repair_targets(issue_candidates)

            if repair_targets and not skip_repair_pass:
                self.stdout.write("")
                self.stdout.write(
                    self.style.WARNING(
                        f"Targeted repair pass needed for {len(repair_targets)} issue(s)."
                    )
                )

                repair_data = self.call_targeted_repair_search(
                    client=client,
                    model=model,
                    repair_search_context=repair_search_context,
                    run=run,
                    repair_targets=repair_targets,
                )
                total_api_calls += 1

                if print_raw:
                    self.stdout.write("")
                    self.stdout.write(self.style.WARNING("Raw repair JSON"))
                    self.stdout.write(json.dumps(repair_data, indent=2, ensure_ascii=False))

                issue_candidates = merge_issue_candidates(
                    base_candidates=issue_candidates,
                    repair_candidates=normalize_candidate_list(
                        repair_data.get("issues", [])
                    ),
                )
            elif repair_targets and skip_repair_pass:
                self.stdout.write("")
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped targeted repair pass for {len(repair_targets)} issue(s)."
                    )
                )

            self.print_result(run=run, issues=issue_candidates)

            if dry_run:
                continue

            created_count, updated_count, skipped_count = self.apply_issues(
                run=run,
                candidates=issue_candidates,
                existing_issue_map=existing_issue_map,
            )
            total_created += created_count
            total_updated += updated_count
            total_skipped += skipped_count

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Issue fill/repair complete."))
        self.stdout.write(f"OpenAI API calls made: {total_api_calls}")
        self.stdout.write(f"Created issues: {total_created}")
        self.stdout.write(f"Updated issues: {total_updated}")
        self.stdout.write(f"Skipped candidates: {total_skipped}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog issues were created or updated.")

    def get_runs_to_check(self, *, publisher_name, run_id, limit_runs):
        runs = (
            ComicRun.objects.select_related("publisher")
            .annotate(attached_issue_count=Count("issues", distinct=True))
            .filter(publisher__name__iexact=publisher_name)
            .exclude(issue_count__isnull=True)
            .order_by("title", "start_year", "id")
        )

        if run_id:
            runs = runs.filter(id=run_id)

        runs_to_check = []

        for run in runs:
            existing_issues = list(run.issues.all())

            has_missing_issue_count = (
                run.issue_count is not None
                and run.attached_issue_count < run.issue_count
            )
            has_incomplete_issues = any(
                existing_issue_needs_repair(issue)
                for issue in existing_issues
            )

            if not has_missing_issue_count and not has_incomplete_issues:
                continue

            runs_to_check.append(run)

            if len(runs_to_check) >= limit_runs:
                break

        return runs_to_check

    def write_header(
        self,
        *,
        mode,
        model,
        publisher_name,
        search_context,
        repair_search_context,
        skip_repair_pass,
        run_id,
        limit_runs,
        runs,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Fill/repair missing Marvel issues with AI"))
        self.stdout.write(f"Mode: {mode}")
        self.stdout.write("Source: OpenAI Responses API web search")
        self.stdout.write("Comic Vine API calls: none")
        self.stdout.write(
            f"Catalog writes: {'none' if mode == 'dry run' else 'create/update ComicIssue rows only'}"
        )
        self.stdout.write("Creates runs: no")
        self.stdout.write("Creates volumes: no")
        self.stdout.write("Creates credits/images: no")
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Publisher: {publisher_name}")
        self.stdout.write(f"Broad search context: {search_context}")
        self.stdout.write(f"Repair search context: {repair_search_context}")
        self.stdout.write(f"Targeted repair pass: {'off' if skip_repair_pass else 'on'}")
        self.stdout.write(f"Run ID filter: {run_id or 'none'}")
        self.stdout.write(f"Run API-call limit: {limit_runs}")
        self.stdout.write(f"Runs needing fill/repair: {len(runs)}")
        self.stdout.write("")

    def call_broad_issue_search(self, *, client, model, search_context, run, existing_issues):
        try:
            response = client.responses.create(
                model=model,
                reasoning={"effort": "low"},
                tools=[
                    {
                        "type": "web_search",
                        "search_context_size": search_context,
                        "filters": {
                            "blocked_domains": [
                                "reddit.com",
                                "quora.com",
                            ],
                        },
                    }
                ],
                tool_choice="required",
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are helping populate a comic catalog. "
                            "Return compact source-grounded JSON only. "
                            "Do not write explanations. "
                            "Do not invent issue titles, dates, issue numbers, cover dates, or release dates. "
                            "Find broad issue data first. "
                            "Prefer Marvel.com, GCD/comics.org, League of Comic Geeks, PRH, ComicReleases, and reliable comics release/checklist sources."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_broad_prompt(
                            run=run,
                            existing_issues=existing_issues,
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "broad_missing_marvel_issues",
                        "strict": True,
                        "schema": BROAD_RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI broad issue search failed for {run}: {exc}") from exc

        return parse_response_json(response.output_text)

    def call_targeted_repair_search(
        self,
        *,
        client,
        model,
        repair_search_context,
        run,
        repair_targets,
    ):
        try:
            response = client.responses.create(
                model=model,
                reasoning={"effort": "low"},
                tools=[
                    {
                        "type": "web_search",
                        "search_context_size": repair_search_context,
                        "filters": {
                            "blocked_domains": [
                                "reddit.com",
                                "quora.com",
                            ],
                        },
                    }
                ],
                tool_choice="required",
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are repairing missing displayed comic issue metadata. "
                            "Return compact source-grounded JSON only. "
                            "Do not write explanations. "
                            "Use exact issue-number searches. "
                            "Do not invent titles, dates, issue numbers, cover dates, or release dates. "
                            "Search specifically for the requested missing displayed fields. "
                            "Prefer Marvel.com, GCD/comics.org, League of Comic Geeks, PRH, ComicReleases, and reliable issue-detail pages."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_repair_prompt(
                            run=run,
                            repair_targets=repair_targets,
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "targeted_missing_marvel_issue_repairs",
                        "strict": True,
                        "schema": REPAIR_RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI targeted repair search failed for {run}: {exc}") from exc

        return parse_response_json(response.output_text)

    def print_result(self, *, run, issues):
        self.stdout.write("")
        self.stdout.write(f"Issue candidates after broad + repair passes: {len(issues)}")
        self.stdout.write("")

        if not issues:
            self.stdout.write(self.style.WARNING("No issue candidates returned."))
            return

        for index, issue in enumerate(issues, start=1):
            issue_number = issue.get("issue_number") or "?"
            title = issue.get("title") or ""
            store_date = issue.get("store_date") or "unknown"
            cover_date = issue.get("cover_date") or "unknown"
            is_released = issue.get("is_released")

            missing_fields = get_missing_candidate_fields(issue)

            self.stdout.write(f"{index}. {run.title} #{issue_number}")
            self.stdout.write(f"   Title: {title or '[blank]'}")
            self.stdout.write(f"   Store date: {store_date}")
            self.stdout.write(f"   Cover date: {cover_date}")
            self.stdout.write(
                f"   Released: {'unknown' if is_released is None else ('yes' if is_released else 'no')}"
            )

            if missing_fields:
                self.stdout.write("   Still missing: " + ", ".join(missing_fields))
            else:
                self.stdout.write("   Ready to write: yes")

            primary_source_url = issue.get("primary_source_url")

            if primary_source_url:
                self.stdout.write(f"   Primary source: {primary_source_url}")

            for source_url in (issue.get("supporting_source_urls") or [])[:2]:
                self.stdout.write(f"   Supporting source: {source_url}")

            self.stdout.write("")

    def apply_issues(self, *, run, candidates, existing_issue_map):
        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for candidate in candidates:
                issue_number = clean_text(candidate.get("issue_number"))
                normalized_issue_number = normalize_issue_number(issue_number)

                if not candidate_has_required_fields(candidate):
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped incomplete issue candidate: {run} #{issue_number or '[blank]'}"
                        )
                    )
                    continue

                existing_issue = existing_issue_map.get(normalized_issue_number)

                if existing_issue:
                    changed = update_existing_issue_from_candidate(existing_issue, candidate)

                    if changed:
                        existing_issue.save()
                        updated_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Updated ComicIssue: {existing_issue}"
                            )
                        )
                    else:
                        skipped_count += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipped existing complete issue: {existing_issue}"
                            )
                        )

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

                self.stdout.write(self.style.SUCCESS(f"Created ComicIssue: {issue}"))

        return created_count, updated_count, skipped_count


def build_broad_prompt(*, run, existing_issues):
    existing_issue_lines = []

    for issue in existing_issues:
        existing_issue_lines.append(
            f"- #{issue.issue_number}"
            f"{f' — title {issue.title}' if issue.title else ' — title missing'}"
            f"{f' — store {issue.store_date.isoformat()}' if issue.store_date else ' — store date missing'}"
            f"{f' — cover {issue.cover_date.isoformat()}' if issue.cover_date else ' — cover date missing'}"
        )

    existing_issues_text = "\n".join(existing_issue_lines) or "- No existing issues."

    today = date.today().isoformat()

    return f"""
Find displayed issue metadata for this exact Marvel catalog run.

Today is {today}.

Catalog run:
- Title: {run.title}
- Start year: {run.start_year or 'unknown'}
- Publisher: {run.publisher.name}
- Catalog issue_count: {run.issue_count}
- Catalog first_issue_date: {run.first_issue_date.isoformat() if run.first_issue_date else 'unknown'}
- Catalog last_issue_date: {run.last_issue_date.isoformat() if run.last_issue_date else 'unknown'}

Existing catalog issues:
{existing_issues_text}

Broad pass task:
- Return missing issues that are not in the existing issue list.
- Also return existing issues if any displayed field is missing or weak.
- Displayed issue fields are issue title, store date, and cover date.
- Search broadly across Marvel.com, GCD/comics.org, League of Comic Geeks, PRH, ComicReleases, and reliable release/checklist pages.
- Do not stop at the first source if title is blank.
- Use on-sale/release date as store_date.
- If cover date is shown only as month/year, convert it to YYYY-MM-01.
- Include released issues and officially announced future issues.
- If future announced but not released yet, set is_released false.
- If already on sale/released as of today, set is_released true.
- Do not return collected editions, trades, omnibuses, facsimiles, reprints, variants, posters, art books, toys, or prose books.
- Do not return issues from another run with the same character/title but a different start year.
- Do not guess.

Return compact structured data only.
Keep supporting_source_urls to 2 or fewer URLs.
Use YYYY-MM-DD for dates.
Use null for unknown dates or unknown release status.
Use null for title if not found in the broad pass.
""".strip()


def build_repair_prompt(*, run, repair_targets):
    target_lines = []

    for target in repair_targets:
        missing_fields = ", ".join(target["missing_fields"])
        target_lines.append(
            f"- {run.title} ({run.start_year or 'unknown'}) #{target['issue_number']}: missing {missing_fields}"
        )

    target_text = "\n".join(target_lines)

    today = date.today().isoformat()

    return f"""
Search specifically for missing displayed fields on these exact Marvel comic issues.

Today is {today}.

Run:
- Title: {run.title}
- Start year: {run.start_year or 'unknown'}
- Publisher: {run.publisher.name}

Targets:
{target_text}

Targeted repair rules:
- Search each issue individually by exact issue number.
- Displayed issue fields are issue title, store date, and cover date.
- For a missing title, search exact issue title sources before returning null.
- Use queries like:
  - "{run.title} #<issue_number> title"
  - "{run.title} #<issue_number> cover date"
  - "{run.title} #<issue_number> League of Comic Geeks"
  - "{run.title} #<issue_number> GCD"
  - "{run.title} #<issue_number> Marvel.com"
- For a missing cover date, search issue-detail/database pages, not only release checklists.
- Good cover-date sources include GCD/comics.org, League of Comic Geeks, Marvel issue pages when available, and other issue-detail database pages.
- Checklist/solicitation pages may confirm store_date, but they are not enough by themselves if cover_date is missing.
- If cover date is shown only as month/year, convert it to YYYY-MM-01.
- Use on-sale/release date as store_date.
- If already on sale/released as of today, set is_released true.
- If future announced but not released yet, set is_released false.
- Do not guess.
- Do not return issues from another run.

Return compact structured data only.
Keep supporting_source_urls to 2 or fewer URLs.
Use YYYY-MM-DD for dates.
Use null for fields that are still unknown after searching.
""".strip()


def parse_response_json(output_text):
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Could not parse model output as JSON: {exc}") from exc


def normalize_candidate_list(candidates):
    normalized = {}

    for candidate in candidates:
        issue_number = clean_text(candidate.get("issue_number"))
        normalized_issue_number = normalize_issue_number(issue_number)

        if not normalized_issue_number:
            continue

        normalized[normalized_issue_number] = normalize_candidate(candidate)

    return list(normalized.values())


def normalize_candidate(candidate):
    return {
        "issue_number": clean_text(candidate.get("issue_number")),
        "title": clean_text(candidate.get("title")),
        "store_date": clean_text(candidate.get("store_date")),
        "cover_date": clean_text(candidate.get("cover_date")),
        "is_released": candidate.get("is_released"),
        "primary_source_url": clean_text(candidate.get("primary_source_url")),
        "supporting_source_urls": [
            clean_text(url)
            for url in candidate.get("supporting_source_urls", [])
            if clean_text(url)
        ][:2],
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

        base = merged.get(normalized_issue_number, {})
        merged[normalized_issue_number] = merge_candidate(base, repair)

    return list(merged.values())


def merge_candidate(base, repair):
    merged = dict(base)

    for field_name in [
        "issue_number",
        "title",
        "store_date",
        "cover_date",
        "primary_source_url",
    ]:
        repair_value = repair.get(field_name)

        if clean_text(repair_value):
            merged[field_name] = clean_text(repair_value)

    if repair.get("is_released") is not None:
        merged["is_released"] = repair.get("is_released")

    supporting_urls = []

    for source_url in merged.get("supporting_source_urls", []):
        if source_url and source_url not in supporting_urls:
            supporting_urls.append(source_url)

    for source_url in repair.get("supporting_source_urls", []):
        if source_url and source_url not in supporting_urls:
            supporting_urls.append(source_url)

    merged["supporting_source_urls"] = supporting_urls[:2]

    return normalize_candidate(merged)


def find_repair_targets(issue_candidates):
    targets = []

    for candidate in issue_candidates:
        missing_fields = get_missing_candidate_fields(candidate)

        if missing_fields:
            targets.append(
                {
                    "issue_number": candidate["issue_number"],
                    "missing_fields": missing_fields,
                }
            )

    return targets


def get_missing_candidate_fields(candidate):
    missing_fields = []

    if not clean_text(candidate.get("issue_number")):
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
    if title_needs_repair(issue.title):
        return True

    if issue.store_date is None:
        return True

    if issue.cover_date is None:
        return True

    return False


def title_needs_repair(title):
    title = clean_text(title)

    if not title:
        return True

    return title.casefold() == "untitled"


def count_incomplete_existing_issues(issues):
    return sum(1 for issue in issues if existing_issue_needs_repair(issue))


def update_existing_issue_from_candidate(issue, candidate):
    changed = False

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

    candidate_is_released = candidate.get("is_released")

    if candidate_is_released is None:
        candidate_is_released = calculate_is_released(candidate)

    if candidate_is_released is not None and issue.is_released != bool(candidate_is_released):
        issue.is_released = bool(candidate_is_released)
        changed = True

    return changed


def calculate_is_released(candidate):
    given_value = candidate.get("is_released")

    if given_value is not None:
        return bool(given_value)

    store_date = parse_date(candidate.get("store_date"))

    if store_date is None:
        return False

    return store_date <= date.today()


def parse_date(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalize_issue_number(value):
    value = clean_text(value).casefold()
    value = re.sub(r"[^a-z0-9.]+", "", value)
    return value


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()