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

BROAD_RESULT_SCHEMA = {
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
                    "primary_source_url": {"type": ["string", "null"]},
                    "supporting_source_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "title",
                    "start_year",
                    "status",
                    "issue_count",
                    "first_issue_date",
                    "last_issue_date",
                    "description",
                    "primary_source_url",
                    "supporting_source_urls",
                ],
            },
        },
    },
    "required": ["candidates"],
}


REPAIR_RESULT_SCHEMA = BROAD_RESULT_SCHEMA


class Command(BaseCommand):
    help = (
        "Find current Marvel comic runs missing from catalog using OpenAI web search. "
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

        existing_runs = list_existing_runs(publisher_name=publisher_name)
        existing_normalized_titles = {
            normalize_title(run.title)
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

        broad_data = self.call_broad_run_search(
            client=client,
            model=model,
            search_context=search_context,
            publisher_name=publisher_name,
            limit=limit,
            existing_runs=existing_runs,
        )

        api_calls = 1

        if print_raw:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Raw broad JSON"))
            self.stdout.write(json.dumps(broad_data, indent=2, ensure_ascii=False))

        candidates = normalize_candidate_list(broad_data.get("candidates", []))
        repair_targets = find_run_repair_targets(candidates)

        if repair_targets and not skip_repair_pass:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Targeted run repair pass needed for {len(repair_targets)} candidate(s)."
                )
            )

            repair_data = self.call_targeted_run_repair_search(
                client=client,
                model=model,
                repair_search_context=repair_search_context,
                publisher_name=publisher_name,
                repair_targets=repair_targets,
                existing_runs=existing_runs,
            )

            api_calls += 1

            if print_raw:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Raw repair JSON"))
                self.stdout.write(json.dumps(repair_data, indent=2, ensure_ascii=False))

            candidates = merge_run_candidates(
                base_candidates=candidates,
                repair_candidates=normalize_candidate_list(repair_data.get("candidates", [])),
            )
        elif repair_targets and skip_repair_pass:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped targeted run repair pass for {len(repair_targets)} candidate(s)."
                )
            )

        self.print_result(candidates=candidates)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("Dry run only. No catalog rows were created.")
        else:
            created_count, skipped_count = self.apply_candidates(
                candidates=candidates,
                publisher_name=publisher_name,
                existing_normalized_titles=existing_normalized_titles,
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
        self.stdout.write("Comic Vine API calls: none")
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

    def call_broad_run_search(
        self,
        *,
        client,
        model,
        search_context,
        publisher_name,
        limit,
        existing_runs,
    ):
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
                            "Do not invent comic runs, dates, issue counts, or descriptions. "
                            "Find broad run data first. "
                            "Prefer Marvel.com, PRH, GCD/comics.org, ComicReleases, League of Comic Geeks, and reliable comics release sources."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_broad_prompt(
                            publisher_name=publisher_name,
                            limit=limit,
                            existing_runs=existing_runs,
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "broad_missing_marvel_runs",
                        "strict": True,
                        "schema": BROAD_RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI broad run search failed: {exc}") from exc

        return parse_response_json(response.output_text)

    def call_targeted_run_repair_search(
        self,
        *,
        client,
        model,
        repair_search_context,
        publisher_name,
        repair_targets,
        existing_runs,
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
                            "You are repairing missing fields in comic run metadata. "
                            "Return compact source-grounded JSON only. "
                            "Do not write explanations. "
                            "Search specifically for the requested missing run fields. "
                            "Do not invent titles, years, dates, issue counts, statuses, or descriptions. "
                            "Prefer Marvel.com, PRH, GCD/comics.org, ComicReleases, League of Comic Geeks, and reliable comics release sources."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_repair_prompt(
                            publisher_name=publisher_name,
                            repair_targets=repair_targets,
                            existing_runs=existing_runs,
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "targeted_missing_marvel_run_repairs",
                        "strict": True,
                        "schema": REPAIR_RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI targeted run repair failed: {exc}") from exc

        return parse_response_json(response.output_text)

    def print_result(self, *, candidates):
        self.stdout.write("")
        self.stdout.write(f"Candidates after broad + repair passes: {len(candidates)}")
        self.stdout.write("")

        if not candidates:
            self.stdout.write(self.style.WARNING("No missing run candidates returned."))
            return

        for index, candidate in enumerate(candidates, start=1):
            missing_fields = get_missing_run_fields(candidate)

            self.stdout.write(f"{index}. {candidate.get('title') or '[blank title]'} ({candidate.get('start_year') or 'unknown year'})")
            self.stdout.write(f"   Status: {candidate.get('status') or 'unknown'}")
            self.stdout.write(f"   Issue count: {candidate.get('issue_count') if candidate.get('issue_count') is not None else 'unknown'}")
            self.stdout.write(f"   First issue date: {candidate.get('first_issue_date') or 'unknown'}")
            self.stdout.write(f"   Last issue date: {candidate.get('last_issue_date') or 'unknown'}")
            self.stdout.write(f"   Description: {candidate.get('description') or '[blank]'}")

            if missing_fields:
                self.stdout.write("   Still missing: " + ", ".join(missing_fields))
            else:
                self.stdout.write("   Ready to write: yes")

            primary_source_url = candidate.get("primary_source_url")

            if primary_source_url:
                self.stdout.write(f"   Primary source: {primary_source_url}")

            for source_url in (candidate.get("supporting_source_urls") or [])[:2]:
                self.stdout.write(f"   Supporting source: {source_url}")

            self.stdout.write("")

    def apply_candidates(self, *, candidates, publisher_name, existing_normalized_titles):
        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            publisher = get_or_create_publisher(publisher_name)

            for candidate in candidates:
                title = clean_text(candidate.get("title"))
                normalized_title = normalize_title(title)

                if not candidate_has_required_run_fields(candidate):
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped incomplete run candidate: {title or '[blank title]'}"
                        )
                    )
                    continue

                if normalized_title in existing_normalized_titles:
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(f"Skipped existing catalog run match: {title}")
                    )
                    continue

                run = ComicRun.objects.create(
                    publisher=publisher,
                    title=title,
                    start_year=clean_text(candidate.get("start_year")),
                    first_issue_date=parse_date(candidate.get("first_issue_date")),
                    last_issue_date=parse_date(candidate.get("last_issue_date")),
                    status=map_catalog_status(candidate.get("status")),
                    issue_count=candidate.get("issue_count"),
                    description=clean_text(candidate.get("description")),
                )

                existing_normalized_titles.add(normalized_title)
                created_count += 1

                self.stdout.write(self.style.SUCCESS(f"Created ComicRun: {run}"))

        return created_count, skipped_count


def build_broad_prompt(*, publisher_name, limit, existing_runs):
    existing_run_lines = []

    for run in existing_runs:
        existing_run_lines.append(f"- {run.title} ({run.start_year or 'unknown year'})")

    existing_runs_text = "\n".join(existing_run_lines) or "- No existing catalog runs."

    return f"""
Find up to {limit} current or upcoming {publisher_name} comic runs that are NOT already in this catalog exclusion list.

Existing catalog runs to exclude:
{existing_runs_text}

Broad pass task:
- Return current or upcoming numbered comic runs only.
- Return fields if found.
- Do not stop at the first source if a displayed catalog field is missing.
- Required displayed catalog fields are title, start_year, status, issue_count, first_issue_date, last_issue_date, and description.
- Exclude collected editions, trade paperbacks, omnibuses, hardcovers, facsimiles, reprints, variant covers, posters, art books, toys, prose books, one-shots, and older completed runs.
- Exclude finite limited series unless a reliable source explicitly treats it as an ongoing run.
- Do not return a run if it appears to match the exclusion list.
- Do not guess.
- Use YYYY-MM-DD for dates.
- Keep descriptions under 180 characters.
- Keep supporting_source_urls to 2 or fewer URLs.

Return compact structured data only.
Use null for unknown fields.
""".strip()


def build_repair_prompt(*, publisher_name, repair_targets, existing_runs):
    existing_run_lines = []

    for run in existing_runs:
        existing_run_lines.append(f"- {run.title} ({run.start_year or 'unknown year'})")

    existing_runs_text = "\n".join(existing_run_lines) or "- No existing catalog runs."

    target_lines = []

    for target in repair_targets:
        missing_fields = ", ".join(target["missing_fields"])
        title = target.get("title") or "[blank title]"
        start_year = target.get("start_year") or "unknown year"
        target_lines.append(f"- {title} ({start_year}): missing {missing_fields}")

    target_text = "\n".join(target_lines)

    return f"""
Search specifically for missing fields on these possible {publisher_name} comic runs.

Existing catalog runs to exclude:
{existing_runs_text}

Targets:
{target_text}

Targeted repair rules:
- Search each target individually.
- Only return current or upcoming numbered comic runs.
- Search specifically for the missing fields named for each target.
- Required displayed catalog fields are title, start_year, status, issue_count, first_issue_date, last_issue_date, and description.
- Do not return collected editions, trades, omnibuses, hardcovers, facsimiles, reprints, variants, one-shots, or older completed runs.
- Do not return a run if it appears to match the exclusion list.
- Do not guess.
- Use YYYY-MM-DD for dates.
- Keep descriptions under 180 characters.
- Keep supporting_source_urls to 2 or fewer URLs.

Return compact structured data only.
Use null for fields still unknown after searching.
""".strip()


def parse_response_json(output_text):
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Could not parse model output as JSON: {exc}") from exc


def normalize_candidate_list(candidates):
    normalized = {}

    for candidate in candidates:
        normalized_candidate = normalize_candidate(candidate)
        key = normalize_title(normalized_candidate.get("title"))

        if not key:
            key = f"unknown-{len(normalized)}"

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
        "primary_source_url": clean_text(candidate.get("primary_source_url")),
        "supporting_source_urls": [
            clean_text(url)
            for url in candidate.get("supporting_source_urls", [])
            if clean_text(url)
        ][:2],
    }


def find_run_repair_targets(candidates):
    targets = []

    for candidate in candidates:
        missing_fields = get_missing_run_fields(candidate)

        if missing_fields:
            targets.append(
                {
                    "title": candidate.get("title"),
                    "start_year": candidate.get("start_year"),
                    "missing_fields": missing_fields,
                }
            )

    return targets


def merge_run_candidates(*, base_candidates, repair_candidates):
    merged = {
        normalize_title(candidate.get("title")) or f"unknown-{index}": dict(candidate)
        for index, candidate in enumerate(base_candidates)
    }

    for repair in repair_candidates:
        key = normalize_title(repair.get("title"))

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
        "issue_count",
        "first_issue_date",
        "last_issue_date",
        "description",
        "primary_source_url",
    ]:
        repair_value = repair.get(field_name)

        if field_name == "issue_count":
            if repair_value is not None:
                merged[field_name] = repair_value
            continue

        if clean_text(repair_value):
            merged[field_name] = clean_text(repair_value)

    supporting_urls = []

    for source_url in merged.get("supporting_source_urls", []):
        if source_url and source_url not in supporting_urls:
            supporting_urls.append(source_url)

    for source_url in repair.get("supporting_source_urls", []):
        if source_url and source_url not in supporting_urls:
            supporting_urls.append(source_url)

    merged["supporting_source_urls"] = supporting_urls[:2]

    return normalize_candidate(merged)


def get_missing_run_fields(candidate):
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


def candidate_has_required_run_fields(candidate):
    return not get_missing_run_fields(candidate)


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

    if status in ["ongoing", "upcoming"]:
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


def normalize_title(value):
    title = clean_text(value).casefold()
    title = re.sub(r"^the\s+", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return " ".join(title.split())


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()