import json
import os
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify
from openai import OpenAI

from catalog.models import ComicPublisher, ComicRun


DEFAULT_MODEL = "gpt-5.5"
DEFAULT_PUBLISHER_NAME = "Marvel"


RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "start_year": {"type": ["string", "null"]},
                    "status": {"type": ["string", "null"]},
                    "issue_count": {"type": ["integer", "null"]},
                    "first_issue_date": {"type": ["string", "null"]},
                    "last_issue_date": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                },
                "required": [
                    "title",
                    "start_year",
                    "status",
                    "issue_count",
                    "first_issue_date",
                    "last_issue_date",
                    "description",
                ],
            },
        },
    },
    "required": ["candidates"],
}


class Command(BaseCommand):
    help = (
        "Find current or upcoming Marvel comic runs missing from catalog using OpenAI web search. "
        "Default mode creates missing ComicRun rows. Use --dry-run to print only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Maximum number of missing run candidates to ask AI for. Default: 1",
        )
        parser.add_argument(
            "--model",
            default=os.getenv("OPENAI_MARVEL_PROBE_MODEL", DEFAULT_MODEL),
            help=f"OpenAI model to use. Default: {DEFAULT_MODEL}",
        )
        parser.add_argument(
            "--publisher",
            default=DEFAULT_PUBLISHER_NAME,
            help=f"Publisher name to use for catalog rows. Default: {DEFAULT_PUBLISHER_NAME}",
        )
        parser.add_argument(
            "--search-context",
            choices=["low", "medium", "high"],
            default="high",
            help="Search context for the broad run search. Default: high",
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
            help="Print candidates only. Do not create catalog rows.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print raw JSON. Does not make another API call.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print every run candidate and row-level write. Default output is compact.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise CommandError(
                "OPENAI_API_KEY is not set. Add it to your .env file before running this command."
            )

        limit = options["limit"]

        if limit < 1:
            raise CommandError("--limit must be at least 1.")

        model = options["model"]
        publisher_name = clean_text(options["publisher"]) or DEFAULT_PUBLISHER_NAME
        search_context = options["search_context"]
        repair_search_context = options["repair_search_context"]
        skip_repair_pass = options["skip_repair_pass"]
        dry_run = options["dry_run"]
        print_raw = options["raw"]
        verbose = options["verbose"]

        existing_runs = list_existing_runs(publisher_name=publisher_name)
        existing_run_keys = {
            run_key(run.title, run.start_year)
            for run in existing_runs
        }

        self.write_header(
            mode="dry run" if dry_run else "apply",
            model=model,
            publisher_name=publisher_name,
            search_context=search_context,
            repair_search_context=repair_search_context,
            skip_repair_pass=skip_repair_pass,
            limit=limit,
            existing_runs=existing_runs,
        )

        client = OpenAI(api_key=api_key)

        broad_data = self.call_run_search(
            client=client,
            model=model,
            search_context=search_context,
            publisher_name=publisher_name,
            existing_runs=existing_runs,
            limit=limit,
            repair_targets=None,
        )
        api_calls = 1

        if print_raw:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Raw broad JSON"))
            self.stdout.write(json.dumps(broad_data, indent=2, ensure_ascii=False))

        candidates = normalize_candidate_list(broad_data.get("candidates", []))
        repair_targets = find_repair_targets(candidates)

        if repair_targets and not skip_repair_pass:
            self.stdout.write(
                self.style.WARNING(
                    f"Targeted run repair pass needed for {len(repair_targets)} candidate(s)."
                )
            )

            repair_data = self.call_run_search(
                client=client,
                model=model,
                search_context=repair_search_context,
                publisher_name=publisher_name,
                existing_runs=existing_runs,
                limit=limit,
                repair_targets=repair_targets,
            )
            api_calls += 1

            if print_raw:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Raw repair JSON"))
                self.stdout.write(json.dumps(repair_data, indent=2, ensure_ascii=False))

            candidates = merge_run_candidates(
                base_candidates=candidates,
                repair_candidates=normalize_candidate_list(
                    repair_data.get("candidates", [])
                ),
            )
        elif repair_targets and skip_repair_pass:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped targeted run repair pass for {len(repair_targets)} candidate(s)."
                )
            )

        self.print_result(candidates=candidates, verbose=verbose)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("Dry run only. No catalog rows were created.")
            self.stdout.write(f"OpenAI API calls made: {api_calls}")
            return

        created_count, skipped_count = self.apply_candidates(
            candidates=candidates,
            publisher_name=publisher_name,
            existing_run_keys=existing_run_keys,
            verbose=verbose,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Apply complete."))
        self.stdout.write(f"OpenAI API calls made: {api_calls}")
        self.stdout.write(f"Created runs: {created_count}")
        self.stdout.write(f"Skipped candidates: {skipped_count}")

    def write_header(
        self,
        *,
        mode,
        model,
        publisher_name,
        search_context,
        repair_search_context,
        skip_repair_pass,
        limit,
        existing_runs,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Find missing Marvel runs with AI"))
        self.stdout.write(f"Mode: {mode}")
        self.stdout.write("Source: OpenAI Responses API web search")
        self.stdout.write(
            f"Catalog writes: {'none' if mode == 'dry run' else 'create missing ComicRun rows only'}"
        )
        self.stdout.write("Creates issues: no")
        self.stdout.write("Creates volumes: no")
        self.stdout.write("Creates credits/images: no")
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Publisher: {publisher_name}")
        self.stdout.write(f"Broad search context: {search_context}")
        self.stdout.write(f"Repair search context: {repair_search_context}")
        self.stdout.write(f"Targeted repair pass: {'off' if skip_repair_pass else 'on'}")
        self.stdout.write(f"Candidate limit: {limit}")
        self.stdout.write(f"Existing catalog runs excluded: {len(existing_runs)}")
        self.stdout.write("")

    def call_run_search(
        self,
        *,
        client,
        model,
        search_context,
        publisher_name,
        existing_runs,
        limit,
        repair_targets,
    ):
        if repair_targets:
            prompt = build_repair_prompt(
                publisher_name=publisher_name,
                existing_runs=existing_runs,
                repair_targets=repair_targets,
            )
            prompt_name = "targeted_missing_marvel_run_repairs"
            system_task = (
                "Find missing comic run catalog fields from web search. "
                "Return JSON matching the schema. "
                "Use confirmed public information only."
            )
        else:
            prompt = build_broad_prompt(
                publisher_name=publisher_name,
                existing_runs=existing_runs,
                limit=limit,
            )
            prompt_name = "broad_missing_marvel_runs"
            system_task = (
                "Find current or upcoming comic run catalog fields from web search. "
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
            raise CommandError(f"OpenAI run search failed: {exc}") from exc

        return parse_response_json(response.output_text)

    def print_result(self, *, candidates, verbose):
        ready_count = 0
        incomplete_count = 0
        incomplete_titles = []

        for candidate in candidates:
            if candidate_has_required_fields(candidate):
                ready_count += 1
            else:
                incomplete_count += 1
                incomplete_titles.append(candidate.get("title") or "[blank title]")

        self.stdout.write("")
        self.stdout.write(
            f"Run candidates after broad + repair passes: {len(candidates)} "
            f"({ready_count} ready, {incomplete_count} incomplete)"
        )

        if incomplete_titles:
            self.stdout.write("Incomplete: " + ", ".join(incomplete_titles))

        if not verbose:
            return

        self.stdout.write("")

        for index, candidate in enumerate(candidates, start=1):
            missing_fields = get_missing_candidate_fields(candidate)

            self.stdout.write(
                f"{index}. {candidate.get('title') or '[blank title]'} "
                f"({candidate.get('start_year') or 'unknown year'})"
            )
            self.stdout.write(f"   Status: {candidate.get('status') or 'unknown'}")
            self.stdout.write(
                f"   Issue count: "
                f"{candidate.get('issue_count') if candidate.get('issue_count') is not None else 'unknown'}"
            )
            self.stdout.write(f"   First issue date: {candidate.get('first_issue_date') or 'unknown'}")
            self.stdout.write(f"   Last issue date: {candidate.get('last_issue_date') or 'unknown'}")
            self.stdout.write(f"   Description: {candidate.get('description') or '[blank]'}")

            if missing_fields:
                self.stdout.write("   Still missing: " + ", ".join(missing_fields))
            else:
                self.stdout.write("   Ready to write: yes")

            self.stdout.write("")

    def apply_candidates(
        self,
        *,
        candidates,
        publisher_name,
        existing_run_keys,
        verbose,
    ):
        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            publisher = get_or_create_publisher(publisher_name)

            for candidate in candidates:
                title = clean_text(candidate.get("title"))
                start_year = clean_text(candidate.get("start_year"))
                candidate_key = run_key(title, start_year)

                if not candidate_has_required_fields(candidate):
                    skipped_count += 1
                    continue

                if candidate_key in existing_run_keys:
                    skipped_count += 1
                    continue

                run = ComicRun.objects.create(
                    publisher=publisher,
                    title=title,
                    start_year=start_year,
                    first_issue_date=parse_date(candidate.get("first_issue_date")),
                    last_issue_date=parse_date(candidate.get("last_issue_date")),
                    status=map_catalog_status(candidate.get("status")),
                    issue_count=candidate.get("issue_count"),
                    description=clean_text(candidate.get("description")),
                )

                existing_run_keys.add(candidate_key)
                created_count += 1

                if verbose:
                    self.stdout.write(self.style.SUCCESS(f"Created ComicRun: {run}"))

        return created_count, skipped_count


def build_broad_prompt(*, publisher_name, existing_runs, limit):
    existing_runs_text = build_existing_runs_text(existing_runs)
    today = date.today().isoformat()

    return f"""
Find up to {limit} current or upcoming {publisher_name} numbered comic runs that are not already in the catalog.

Today:
{today}

Existing catalog runs to exclude:
{existing_runs_text}

Required fields:
- title
- start_year
- status
- issue_count
- first_issue_date
- last_issue_date
- description

Rules:
- Search the open web broadly.
- Do not restrict the search to specific websites.
- Only use results that clearly match the publisher, run title, and start year.
- status must be upcoming if issue #1 has a future on-sale date.
- status must be ongoing if issue #1 is already on sale and the run is not completed.
- issue_count is the count of released plus officially solicited issues for the current run.
- first_issue_date is the issue #1 on-sale date.
- last_issue_date is the latest released or officially solicited issue on-sale date.
- description must be a short plain catalog description under 180 characters.
- Exclude collected editions, trades, omnibuses, hardcovers, facsimiles, reprints, variants, posters, art books, toys, prose books, one-shots, and completed older runs.
- Exclude finite limited series unless a reliable source explicitly treats it as an ongoing run.
- Use YYYY-MM-DD for dates.
- Use null for fields still unknown.

Return compact JSON only.
""".strip()


def build_repair_prompt(*, publisher_name, existing_runs, repair_targets):
    existing_runs_text = build_existing_runs_text(existing_runs)
    today = date.today().isoformat()

    target_lines = []

    for target in repair_targets:
        missing_fields = ", ".join(target["missing_fields"])
        target_lines.append(
            f"- title={target.get('title') or 'null'}; "
            f"start_year={target.get('start_year') or 'null'}; "
            f"status={target.get('status') or 'null'}; "
            f"issue_count={target.get('issue_count') if target.get('issue_count') is not None else 'null'}; "
            f"first_issue_date={target.get('first_issue_date') or 'null'}; "
            f"last_issue_date={target.get('last_issue_date') or 'null'}; "
            f"description={target.get('description') or 'null'}; "
            f"missing={missing_fields}"
        )

    target_text = "\n".join(target_lines)

    return f"""
Find missing fields for these incomplete {publisher_name} run candidates.

Today:
{today}

Existing catalog runs to exclude:
{existing_runs_text}

Targets:
{target_text}

Required fields:
- title
- start_year
- status
- issue_count
- first_issue_date
- last_issue_date
- description

Rules:
- Search the open web broadly.
- Do not restrict the search to specific websites.
- Only use results that clearly match the publisher, run title, and start year.
- Preserve known values unless a better confirmed value is found.
- status must be upcoming if issue #1 has a future on-sale date.
- status must be ongoing if issue #1 is already on sale and the run is not completed.
- issue_count is the count of released plus officially solicited issues for the current run.
- first_issue_date is the issue #1 on-sale date.
- last_issue_date is the latest released or officially solicited issue on-sale date.
- description must be a short plain catalog description under 180 characters.
- Exclude collected editions, trades, omnibuses, hardcovers, facsimiles, reprints, variants, posters, art books, toys, prose books, one-shots, and completed older runs.
- Exclude finite limited series unless a reliable source explicitly treats it as an ongoing run.
- Use YYYY-MM-DD for dates.
- Use null for fields still unknown.

Return compact JSON only.
""".strip()


def build_existing_runs_text(existing_runs):
    lines = []

    for run in existing_runs:
        lines.append(f"- {run.title} ({run.start_year or 'unknown year'})")

    return "\n".join(lines) or "- No existing catalog runs."


def parse_response_json(output_text):
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Could not parse model output as JSON: {exc}") from exc


def normalize_candidate_list(candidates):
    normalized = {}

    for index, candidate in enumerate(candidates):
        normalized_candidate = normalize_candidate(candidate)
        key = run_key(
            normalized_candidate.get("title"),
            normalized_candidate.get("start_year"),
        )

        if not key:
            key = f"unknown-{index}"

        normalized[key] = normalized_candidate

    return list(normalized.values())


def normalize_candidate(candidate):
    return {
        "title": clean_text(candidate.get("title")),
        "start_year": clean_text(candidate.get("start_year")),
        "status": clean_text(candidate.get("status")),
        "issue_count": candidate.get("issue_count"),
        "first_issue_date": clean_text(candidate.get("first_issue_date")),
        "last_issue_date": clean_text(candidate.get("last_issue_date")),
        "description": clean_text(candidate.get("description")),
    }


def merge_run_candidates(*, base_candidates, repair_candidates):
    merged = {
        run_key(candidate.get("title"), candidate.get("start_year")) or f"unknown-{index}": dict(candidate)
        for index, candidate in enumerate(base_candidates)
    }

    for repair in repair_candidates:
        key = run_key(repair.get("title"), repair.get("start_year"))

        if not key:
            continue

        base = merged.get(key, {})
        merged[key] = merge_candidate(base, repair)

    return list(merged.values())


def merge_candidate(base, repair):
    merged = dict(base)

    for field_name in [
        "title",
        "start_year",
        "status",
        "first_issue_date",
        "last_issue_date",
        "description",
    ]:
        repair_value = repair.get(field_name)

        if clean_text(repair_value):
            merged[field_name] = clean_text(repair_value)

    if repair.get("issue_count") is not None:
        merged["issue_count"] = repair.get("issue_count")

    return normalize_candidate(merged)


def find_repair_targets(candidates):
    targets = []

    for candidate in candidates:
        missing_fields = get_missing_candidate_fields(candidate)

        if missing_fields:
            target = dict(candidate)
            target["missing_fields"] = missing_fields
            targets.append(target)

    return targets


def get_missing_candidate_fields(candidate):
    missing_fields = []

    for field_name in [
        "title",
        "start_year",
        "status",
        "first_issue_date",
        "last_issue_date",
        "description",
    ]:
        if not clean_text(candidate.get(field_name)):
            missing_fields.append(field_name)

    if candidate.get("issue_count") is None:
        missing_fields.append("issue_count")

    if candidate.get("issue_count") is not None and candidate.get("issue_count") <= 0:
        missing_fields.append("issue_count")

    if parse_date(candidate.get("first_issue_date")) is None:
        if "first_issue_date" not in missing_fields:
            missing_fields.append("first_issue_date")

    if parse_date(candidate.get("last_issue_date")) is None:
        if "last_issue_date" not in missing_fields:
            missing_fields.append("last_issue_date")

    status = clean_text(candidate.get("status")).lower()

    if status not in ["ongoing", "upcoming"]:
        if "status" not in missing_fields:
            missing_fields.append("status")

    return missing_fields


def candidate_has_required_fields(candidate):
    return not get_missing_candidate_fields(candidate)


def list_existing_runs(*, publisher_name):
    return list(
        ComicRun.objects.select_related("publisher")
        .filter(publisher__name__iexact=publisher_name)
        .order_by("title", "start_year", "id")
    )


def get_or_create_publisher(name):
    existing = ComicPublisher.objects.filter(name__iexact=name).first()

    if existing:
        return existing

    base_slug = slugify(name) or "publisher"
    slug = base_slug
    suffix = 2

    while ComicPublisher.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    return ComicPublisher.objects.create(name=name, slug=slug)


def map_catalog_status(value):
    status = clean_text(value).lower()

    if status == "upcoming":
        return ComicRun.STATUS_UPCOMING

    if status == "ongoing":
        return ComicRun.STATUS_ONGOING

    return ComicRun.STATUS_UNKNOWN


def parse_date(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def run_key(title, start_year):
    normalized_title = normalize_title(title)
    normalized_year = clean_text(start_year)

    if not normalized_title:
        return ""

    return f"{normalized_title}::{normalized_year}"


def normalize_title(value):
    title = clean_text(value).casefold()
    title = re.sub(r"^the\s+", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return " ".join(title.split())


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()