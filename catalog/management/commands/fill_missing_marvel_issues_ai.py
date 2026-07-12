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


RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "issue_number": {"type": "string"},
                    "title": {
                        "type": ["string", "null"],
                        "description": "Confirmed issue title, or null if not found.",
                    },
                    "store_date": {
                        "type": ["string", "null"],
                        "description": "On-sale/release date in YYYY-MM-DD, or null if unknown.",
                    },
                    "cover_date": {
                        "type": ["string", "null"],
                        "description": "Cover date in YYYY-MM-DD, or null if unknown. If only month/year is available, use YYYY-MM-01.",
                    },
                },
                "required": [
                    "issue_number",
                    "title",
                    "store_date",
                    "cover_date",
                ],
            },
        },
    },
    "required": ["issues"],
}


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
            help="Maximum number of runs to process. Default: 1",
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
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print every issue candidate and row-level write. Default output is compact.",
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
        verbose = options["verbose"]

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

            target_issue_numbers = build_target_issue_numbers(
                run=run,
                existing_issues=existing_issues,
            )

            if not target_issue_numbers:
                continue

            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"Checking run: {run}"))
            self.stdout.write(f"Run issue_count: {run.issue_count}")
            self.stdout.write(f"Existing attached issues: {len(existing_issues)}")
            self.stdout.write(
                f"Existing incomplete issues: {count_incomplete_existing_issues(existing_issues)}"
            )
            self.stdout.write(f"Target issues: {', '.join(target_issue_numbers)}")
            self.stdout.write("")

            broad_data = self.call_issue_search(
                client=client,
                model=model,
                search_context=search_context,
                run=run,
                target_issue_numbers=target_issue_numbers,
                repair_targets=None,
            )
            total_api_calls += 1

            if print_raw:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Raw broad JSON"))
                self.stdout.write(json.dumps(broad_data, indent=2, ensure_ascii=False))

            issue_candidates = normalize_candidate_list(broad_data.get("issues", []))
            issue_candidates = ensure_candidates_for_targets(
                candidates=issue_candidates,
                target_issue_numbers=target_issue_numbers,
            )

            repair_targets = find_repair_targets(issue_candidates)

            if repair_targets and not skip_repair_pass:
                self.stdout.write(
                    self.style.WARNING(
                        f"Targeted repair pass needed for {len(repair_targets)} issue(s)."
                    )
                )

                repair_data = self.call_issue_search(
                    client=client,
                    model=model,
                    search_context=repair_search_context,
                    run=run,
                    target_issue_numbers=target_issue_numbers,
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
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped targeted repair pass for {len(repair_targets)} issue(s)."
                    )
                )

            self.print_result(run=run, issues=issue_candidates, verbose=verbose)

            if dry_run:
                continue

            created_count, updated_count, skipped_count = self.apply_issues(
                run=run,
                candidates=issue_candidates,
                existing_issue_map=existing_issue_map,
                verbose=verbose,
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
        self.stdout.write(f"Run limit: {limit_runs}")
        self.stdout.write(f"Runs needing fill/repair: {len(runs)}")
        self.stdout.write("")

    def call_issue_search(
        self,
        *,
        client,
        model,
        search_context,
        run,
        target_issue_numbers,
        repair_targets,
    ):
        if repair_targets:
            prompt = build_repair_prompt(
                run=run,
                repair_targets=repair_targets,
            )
            prompt_name = "targeted_missing_marvel_issue_repairs"
            system_task = (
                "Find missing comic issue catalog fields from web search. "
                "Return JSON matching the schema. "
                "Use confirmed public information only."
            )
        else:
            prompt = build_broad_prompt(
                run=run,
                target_issue_numbers=target_issue_numbers,
            )
            prompt_name = "broad_missing_marvel_issues"
            system_task = (
                "Find comic issue catalog fields from web search. "
                "Return JSON matching the schema. "
                "Use confirmed public information only."
            )

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
                        "content": system_task,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": prompt_name,
                        "strict": True,
                        "schema": RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI issue search failed for {run}: {exc}") from exc

        return parse_response_json(response.output_text)

    def print_result(self, *, run, issues, verbose):
        ready_count = 0
        incomplete_count = 0
        incomplete_numbers = []

        for issue in issues:
            if candidate_has_required_fields(issue):
                ready_count += 1
            else:
                incomplete_count += 1
                incomplete_numbers.append(f"#{issue.get('issue_number') or '?'}")

        self.stdout.write("")
        self.stdout.write(
            f"Issue candidates after broad + repair passes: {len(issues)} "
            f"({ready_count} ready, {incomplete_count} incomplete)"
        )

        if incomplete_numbers:
            self.stdout.write("Incomplete: " + ", ".join(incomplete_numbers))

        if not verbose:
            return

        self.stdout.write("")

        for index, issue in enumerate(issues, start=1):
            issue_number = issue.get("issue_number") or "?"
            title = issue.get("title") or ""
            store_date = issue.get("store_date") or "unknown"
            cover_date = issue.get("cover_date") or "unknown"
            missing_fields = get_missing_candidate_fields(issue)

            self.stdout.write(f"{index}. {run.title} #{issue_number}")
            self.stdout.write(f"   Title: {title or '[blank]'}")
            self.stdout.write(f"   Store date: {store_date}")
            self.stdout.write(f"   Cover date: {cover_date}")

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
                issue_number = clean_text(candidate.get("issue_number"))
                normalized_issue_number = normalize_issue_number(issue_number)

                if not candidate_has_required_fields(candidate):
                    skipped_count += 1
                    continue

                existing_issue = existing_issue_map.get(normalized_issue_number)

                if existing_issue:
                    changed = update_existing_issue_from_candidate(existing_issue, candidate)

                    if changed:
                        existing_issue.save()
                        updated_count += 1

                        if verbose:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Updated ComicIssue: {existing_issue}"
                                )
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
                    self.stdout.write(self.style.SUCCESS(f"Created ComicIssue: {issue}"))

        return created_count, updated_count, skipped_count


def build_broad_prompt(*, run, target_issue_numbers):
    target_text = ", ".join(f"#{number}" for number in target_issue_numbers)

    return f"""
Find displayed issue metadata for this exact comic run.

Run:
- Publisher: {run.publisher.name}
- Title: {run.title}
- Start year: {run.start_year or 'unknown'}

Target issue numbers:
{target_text}

Required fields:
- issue_number
- title
- store_date
- cover_date

Rules:
- Search the open web broadly.
- Do not restrict the search to specific websites.
- Return exactly one object for each target issue number.
- Only use results that clearly match the publisher, run title, start year, and issue number.
- title is the individual issue title.
- store_date is the on-sale or release date.
- cover_date is the cover date.
- If cover_date is only shown as month and year, convert it to YYYY-MM-01.
- Exclude collected editions, trades, omnibuses, facsimiles, reprints, variants, posters, art books, toys, and prose books.
- Use YYYY-MM-DD for dates.
- Use null for fields still unknown.

Return compact JSON only.
""".strip()


def build_repair_prompt(*, run, repair_targets):
    target_lines = []

    for target in repair_targets:
        missing_fields = ", ".join(target["missing_fields"])
        title = target.get("title") or "null"
        store_date = target.get("store_date") or "null"
        cover_date = target.get("cover_date") or "null"

        target_lines.append(
            f"- #{target['issue_number']}: "
            f"title={title}; store_date={store_date}; cover_date={cover_date}; missing={missing_fields}"
        )

    target_text = "\n".join(target_lines)

    return f"""
Find missing displayed issue fields for this exact comic run.

Run:
- Publisher: {run.publisher.name}
- Title: {run.title}
- Start year: {run.start_year or 'unknown'}

Targets:
{target_text}

Required fields:
- issue_number
- title
- store_date
- cover_date

Rules:
- Search the open web broadly.
- Do not restrict the search to specific websites.
- Return exactly one object for each target issue number.
- Only use results that clearly match the publisher, run title, start year, and issue number.
- Preserve known values unless a better confirmed value is found.
- title is the individual issue title.
- store_date is the on-sale or release date.
- cover_date is the cover date.
- If cover_date is only shown as month and year, convert it to YYYY-MM-01.
- Exclude collected editions, trades, omnibuses, facsimiles, reprints, variants, posters, art books, toys, and prose books.
- Use YYYY-MM-DD for dates.
- Use null for fields still unknown.

Return compact JSON only.
""".strip()


def build_target_issue_numbers(*, run, existing_issues):
    existing_issue_numbers = {
        normalize_issue_number(issue.issue_number)
        for issue in existing_issues
    }

    numbers = []

    if run.issue_count:
        for number in range(1, run.issue_count + 1):
            issue_number = str(number)

            if normalize_issue_number(issue_number) not in existing_issue_numbers:
                numbers.append(issue_number)

    for issue in existing_issues:
        issue_number = clean_text(issue.issue_number)

        if issue_number and existing_issue_needs_repair(issue):
            numbers.append(issue_number)

    return sort_issue_numbers(unique_issue_numbers(numbers))


def ensure_candidates_for_targets(*, candidates, target_issue_numbers):
    candidate_map = {
        normalize_issue_number(candidate["issue_number"]): dict(candidate)
        for candidate in candidates
    }

    for issue_number in target_issue_numbers:
        normalized_issue_number = normalize_issue_number(issue_number)

        if normalized_issue_number not in candidate_map:
            candidate_map[normalized_issue_number] = {
                "issue_number": issue_number,
                "title": "",
                "store_date": "",
                "cover_date": "",
            }

    return sort_candidates(candidate_map.values())


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

    return sort_candidates(normalized.values())


def normalize_candidate(candidate):
    return {
        "issue_number": clean_text(candidate.get("issue_number")),
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

        base = merged.get(normalized_issue_number, {})
        merged[normalized_issue_number] = merge_candidate(base, repair)

    return sort_candidates(merged.values())


def merge_candidate(base, repair):
    merged = dict(base)

    for field_name in [
        "issue_number",
        "title",
        "store_date",
        "cover_date",
    ]:
        repair_value = repair.get(field_name)

        if clean_text(repair_value):
            merged[field_name] = clean_text(repair_value)

    return normalize_candidate(merged)


def find_repair_targets(issue_candidates):
    targets = []

    for candidate in issue_candidates:
        missing_fields = get_missing_candidate_fields(candidate)

        if missing_fields:
            targets.append(
                {
                    "issue_number": candidate["issue_number"],
                    "title": candidate.get("title"),
                    "store_date": candidate.get("store_date"),
                    "cover_date": candidate.get("cover_date"),
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

    calculated_is_released = calculate_is_released(candidate)

    if issue.is_released != calculated_is_released:
        issue.is_released = calculated_is_released
        changed = True

    return changed


def calculate_is_released(candidate):
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


def unique_issue_numbers(numbers):
    seen = set()
    unique = []

    for number in numbers:
        cleaned_number = clean_text(number)
        normalized_number = normalize_issue_number(cleaned_number)

        if not cleaned_number or normalized_number in seen:
            continue

        seen.add(normalized_number)
        unique.append(cleaned_number)

    return unique


def sort_issue_numbers(numbers):
    return sorted(numbers, key=issue_number_sort_key)


def sort_candidates(candidates):
    return sorted(
        candidates,
        key=lambda candidate: issue_number_sort_key(candidate["issue_number"]),
    )


def issue_number_sort_key(value):
    value = clean_text(value)
    match = re.match(r"^(\d+)(.*)$", value)

    if not match:
        return (999999, value)

    number = int(match.group(1))
    suffix = match.group(2)

    return (number, suffix)


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()