import json
import os
import re
from collections import Counter
from datetime import date
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify
from openai import OpenAI

from catalog.models import ComicIssue, ComicPublisher, ComicRun
from comicvine.models import ComicVineIssue, ComicVineVolume


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
            default="medium",
            help="Search context for the run search. Default: medium",
        )
        parser.add_argument(
            "--skip-comicvine-match",
            action="store_true",
            help="Do not scan local Comic Vine volumes after creating a run.",
        )
        parser.add_argument(
            "--comicvine-match-limit",
            type=int,
            default=8,
            help="Maximum local Comic Vine volume matches to show after creating a run. Default: 8",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print candidates only. Do not create catalog rows or copy local Comic Vine issues.",
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

        comicvine_match_limit = options["comicvine_match_limit"]

        if comicvine_match_limit < 1:
            raise CommandError("--comicvine-match-limit must be at least 1.")

        model = options["model"]
        publisher_name = clean_text(options["publisher"]) or DEFAULT_PUBLISHER_NAME
        search_context = options["search_context"]
        skip_comicvine_match = options["skip_comicvine_match"]
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
            limit=limit,
            existing_runs=existing_runs,
            skip_comicvine_match=skip_comicvine_match,
            comicvine_match_limit=comicvine_match_limit,
        )

        client = OpenAI(api_key=api_key)

        broad_data = self.call_run_search(
            client=client,
            model=model,
            search_context=search_context,
            publisher_name=publisher_name,
            existing_runs=existing_runs,
            limit=limit,
        )

        api_calls = 1

        if print_raw:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Raw run search JSON"))
            self.stdout.write(json.dumps(broad_data, indent=2, ensure_ascii=False))

        candidates = normalize_candidate_list(broad_data.get("candidates", []))

        self.print_result(candidates=candidates, verbose=verbose)

        if dry_run:
            self.print_dry_run_comicvine_matches(
                candidates=candidates,
                publisher_name=publisher_name,
                skip_comicvine_match=skip_comicvine_match,
                comicvine_match_limit=comicvine_match_limit,
            )
            self.stdout.write("")
            self.stdout.write("Dry run only. No catalog rows were created.")
            self.stdout.write(f"OpenAI API calls made: {api_calls}")
            return

        created_count, skipped_count = self.apply_candidates(
            candidates=candidates,
            publisher_name=publisher_name,
            existing_run_keys=existing_run_keys,
            verbose=verbose,
            skip_comicvine_match=skip_comicvine_match,
            comicvine_match_limit=comicvine_match_limit,
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
        limit,
        existing_runs,
        skip_comicvine_match,
        comicvine_match_limit,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Find missing Marvel runs with AI"))
        self.stdout.write(f"Mode: {mode}")
        self.stdout.write("Source: OpenAI Responses API web search")
        self.stdout.write(
            f"Catalog writes: {'none' if mode == 'dry run' else 'create missing ComicRun rows only'}"
        )
        self.stdout.write("Creates issues from OpenAI: no")
        self.stdout.write("Local Comic Vine issue copy: " + ("off" if skip_comicvine_match else "prompt after run create"))
        self.stdout.write("Creates volumes: no")
        self.stdout.write("Creates credits/images: no")
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Publisher: {publisher_name}")
        self.stdout.write(f"Search context: {search_context}")
        self.stdout.write(f"Candidate limit: {limit}")
        self.stdout.write(f"Existing catalog runs excluded: {len(existing_runs)}")
        self.stdout.write(f"Local Comic Vine match display limit: {comicvine_match_limit}")
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
    ):
        prompt = build_broad_prompt(
            publisher_name=publisher_name,
            existing_runs=existing_runs,
            limit=limit,
        )

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
                            "Find confirmed current or upcoming comic run catalog fields "
                            "using web search and return JSON matching the schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "missing_marvel_runs",
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
            f"Run candidates found: {len(candidates)} "
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

    def print_dry_run_comicvine_matches(
        self,
        *,
        candidates,
        publisher_name,
        skip_comicvine_match,
        comicvine_match_limit,
    ):
        if skip_comicvine_match:
            return

        ready_candidates = [
            candidate
            for candidate in candidates
            if candidate_has_required_fields(candidate)
        ]

        if not ready_candidates:
            return

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Local Comic Vine match preview"))

        for candidate in ready_candidates:
            matches = find_possible_comicvine_volume_matches(
                title=candidate["title"],
                start_year=candidate["start_year"],
                publisher_name=publisher_name,
                limit=comicvine_match_limit,
            )

            self.stdout.write("")
            self.stdout.write(
                f"{candidate['title']} ({candidate['start_year']})"
            )

            if not matches:
                self.stdout.write("  No likely local Comic Vine volume matches.")
                continue

            for index, match in enumerate(matches, start=1):
                self.stdout.write(
                    format_comicvine_match_line(
                        index=index,
                        match=match,
                    )
                )

    def apply_candidates(
        self,
        *,
        candidates,
        publisher_name,
        existing_run_keys,
        verbose,
        skip_comicvine_match,
        comicvine_match_limit,
    ):
        created_count = 0
        skipped_count = 0

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

            with transaction.atomic():
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

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created run: {run.title} ({run.start_year or 'unknown year'}) [id={run.id}]"
                )
            )

            if verbose:
                self.stdout.write(
                    f"   status={run.status}, issue_count={run.issue_count}, "
                    f"first_issue_date={run.first_issue_date}, last_issue_date={run.last_issue_date}"
                )

            if not skip_comicvine_match:
                self.prompt_for_comicvine_issue_copy(
                    run=run,
                    publisher_name=publisher_name,
                    comicvine_match_limit=comicvine_match_limit,
                    verbose=verbose,
                )

        return created_count, skipped_count

    def prompt_for_comicvine_issue_copy(
        self,
        *,
        run,
        publisher_name,
        comicvine_match_limit,
        verbose,
    ):
        matches = find_possible_comicvine_volume_matches(
            title=run.title,
            start_year=run.start_year,
            publisher_name=publisher_name,
            limit=comicvine_match_limit,
        )

        self.stdout.write("")

        if not matches:
            self.stdout.write(
                self.style.WARNING(
                    f"No likely local Comic Vine volume matches for {run.title} ({run.start_year or 'unknown year'})."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Possible local Comic Vine matches for {run.title} ({run.start_year or 'unknown year'}):"
            )
        )

        for index, match in enumerate(matches, start=1):
            self.stdout.write(
                format_comicvine_match_line(
                    index=index,
                    match=match,
                )
            )

        self.stdout.write("0. Skip local Comic Vine issue copy")
        choice = input("Select Comic Vine volume to copy issues from: ").strip()

        if choice in ["", "0"]:
            self.stdout.write("Skipped local Comic Vine issue copy.")
            return

        try:
            selected_index = int(choice)
        except ValueError:
            self.stdout.write(self.style.WARNING("Invalid selection. Skipped local Comic Vine issue copy."))
            return

        if selected_index < 1 or selected_index > len(matches):
            self.stdout.write(self.style.WARNING("Invalid selection. Skipped local Comic Vine issue copy."))
            return

        selected_volume = matches[selected_index - 1]["volume"]

        result = copy_complete_comicvine_issues_to_catalog_run(
            catalog_run=run,
            comicvine_volume=selected_volume,
            verbose=verbose,
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Local Comic Vine issue copy complete from "
                f"{selected_volume.name} [comicvine_id={selected_volume.comicvine_id}]"
            )
        )
        self.stdout.write("API calls made for issue copy: 0")
        self.stdout.write(f"Source issues checked: {result['checked']}")
        self.stdout.write(f"Created catalog issues: {result['created']}")
        self.stdout.write(f"Updated catalog issues: {result['updated']}")
        self.stdout.write(f"Already complete catalog issues: {result['unchanged']}")
        self.stdout.write(f"Skipped source issues: {result['skipped']}")

        if result["skipped_reasons"]:
            self.stdout.write("Skipped reason counts:")

            for reason, count in sorted(result["skipped_reasons"].items()):
                self.stdout.write(f"- {reason}: {count}")


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
    upcoming_status = getattr(ComicRun, "STATUS_UPCOMING", "upcoming")
    ongoing_status = getattr(ComicRun, "STATUS_ONGOING", "ongoing")

    if status == "upcoming":
        return upcoming_status

    if status == "ongoing":
        return ongoing_status

    return ComicRun.STATUS_UNKNOWN


def find_possible_comicvine_volume_matches(*, title, start_year, publisher_name, limit):
    normalized_title = normalize_title(title)
    cleaned_year = clean_text(start_year)

    if not normalized_title:
        return []

    volumes = ComicVineVolume.objects.prefetch_related("issues").all()

    if cleaned_year:
        volumes = volumes.filter(start_year=cleaned_year)

    if publisher_name:
        publisher_filtered = volumes.filter(publisher__iexact=publisher_name)

        if publisher_filtered.exists():
            volumes = publisher_filtered

    matches = []

    for volume in volumes:
        score = rough_title_score(title, volume.name)

        if score < 0.34:
            continue

        source_issues = list(volume.issues.all())
        complete_issue_count = sum(
            1
            for issue in source_issues
            if not get_source_issue_validation_errors(issue)
        )

        matches.append(
            {
                "volume": volume,
                "score": score,
                "issue_count": len(source_issues),
                "complete_issue_count": complete_issue_count,
            }
        )

    matches.sort(
        key=lambda item: (
            item["score"],
            item["complete_issue_count"],
            item["issue_count"],
        ),
        reverse=True,
    )

    return matches[:limit]


def rough_title_score(catalog_title, comicvine_title):
    catalog_normalized = normalize_title(catalog_title)
    comicvine_normalized = normalize_title(comicvine_title)

    if not catalog_normalized or not comicvine_normalized:
        return 0.0

    if catalog_normalized == comicvine_normalized:
        return 1.0

    if catalog_normalized in comicvine_normalized or comicvine_normalized in catalog_normalized:
        return 0.92

    catalog_tokens = set(catalog_normalized.split())
    comicvine_tokens = set(comicvine_normalized.split())

    if not catalog_tokens or not comicvine_tokens:
        return 0.0

    overlap = len(catalog_tokens & comicvine_tokens)
    token_score = overlap / max(len(catalog_tokens), len(comicvine_tokens))
    sequence_score = SequenceMatcher(None, catalog_normalized, comicvine_normalized).ratio()

    return max(token_score, sequence_score)


def format_comicvine_match_line(*, index, match):
    volume = match["volume"]

    return (
        f"{index}. {volume.name} "
        f"({volume.start_year or 'unknown year'}) "
        f"[comicvine_id={volume.comicvine_id}, local_id={volume.id}, "
        f"issues={match['issue_count']}, complete={match['complete_issue_count']}, "
        f"score={match['score']:.2f}]"
    )


def copy_complete_comicvine_issues_to_catalog_run(*, catalog_run, comicvine_volume, verbose):
    source_issues = list(
        ComicVineIssue.objects.filter(volume=comicvine_volume)
        .order_by("store_date", "cover_date", "issue_number", "id")
    )

    existing_catalog_issues = {
        normalize_issue_number(issue.issue_number): issue
        for issue in catalog_run.issues.all()
    }

    created_count = 0
    updated_count = 0
    unchanged_count = 0
    skipped_count = 0
    skipped_reasons = Counter()

    with transaction.atomic():
        for source_issue in source_issues:
            validation_errors = get_source_issue_validation_errors(source_issue)

            if validation_errors:
                skipped_count += 1

                for reason in validation_errors:
                    skipped_reasons[reason] += 1

                if verbose:
                    print(format_source_skip_line(source_issue=source_issue, reasons=validation_errors))

                continue

            issue_number = canonical_issue_number(source_issue.issue_number)
            normalized_issue_number = normalize_issue_number(issue_number)
            existing_issue = existing_catalog_issues.get(normalized_issue_number)

            if existing_issue:
                changed = update_existing_catalog_issue_from_source(
                    catalog_issue=existing_issue,
                    source_issue=source_issue,
                )

                if changed:
                    existing_issue.save()
                    updated_count += 1

                    if verbose:
                        print(f"Updated catalog issue from Comic Vine: {existing_issue}")
                else:
                    unchanged_count += 1

                    if verbose:
                        print(f"Already complete: {existing_issue}")

                continue

            catalog_issue = ComicIssue.objects.create(
                run=catalog_run,
                issue_number=issue_number,
                title=clean_text(source_issue.issue_title),
                store_date=source_issue.store_date,
                cover_date=source_issue.cover_date,
                is_released=is_released_from_store_date(source_issue.store_date),
                description="",
            )

            existing_catalog_issues[normalized_issue_number] = catalog_issue
            created_count += 1

            if verbose:
                print(f"Created catalog issue from Comic Vine: {catalog_issue}")

    return {
        "checked": len(source_issues),
        "created": created_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
        "skipped": skipped_count,
        "skipped_reasons": skipped_reasons,
    }


def get_source_issue_validation_errors(source_issue):
    errors = []

    if not canonical_issue_number(source_issue.issue_number):
        errors.append("missing issue_number")

    if not clean_text(source_issue.issue_title):
        errors.append("missing title")

    if source_issue.store_date is None:
        errors.append("missing store_date")

    if source_issue.cover_date is None:
        errors.append("missing cover_date")

    return errors


def update_existing_catalog_issue_from_source(*, catalog_issue, source_issue):
    changed = False
    source_issue_number = canonical_issue_number(source_issue.issue_number)

    if source_issue_number and catalog_issue.issue_number != source_issue_number:
        duplicate_exists = (
            ComicIssue.objects.filter(
                run=catalog_issue.run,
                issue_number=source_issue_number,
            )
            .exclude(id=catalog_issue.id)
            .exists()
        )

        if not duplicate_exists:
            catalog_issue.issue_number = source_issue_number
            changed = True

    source_title = clean_text(source_issue.issue_title)

    if title_needs_repair(catalog_issue.title) and source_title:
        catalog_issue.title = source_title
        changed = True

    if catalog_issue.store_date is None and source_issue.store_date is not None:
        catalog_issue.store_date = source_issue.store_date
        changed = True

    if catalog_issue.cover_date is None and source_issue.cover_date is not None:
        catalog_issue.cover_date = source_issue.cover_date
        changed = True

    source_is_released = is_released_from_store_date(source_issue.store_date)

    if catalog_issue.is_released != source_is_released:
        catalog_issue.is_released = source_is_released
        changed = True

    return changed


def format_source_skip_line(*, source_issue, reasons):
    issue_number = clean_text(source_issue.issue_number) or "?"
    title = clean_text(source_issue.issue_title) or "[blank]"
    reason_text = ", ".join(reasons)

    return (
        f"Skipped Comic Vine issue #{issue_number}: "
        f"title={title}; "
        f"store_date={source_issue.store_date or 'missing'}; "
        f"cover_date={source_issue.cover_date or 'missing'}; "
        f"reason={reason_text}"
    )


def title_needs_repair(title):
    title = clean_text(title)

    if not title:
        return True

    return title.casefold() == "untitled"


def is_released_from_store_date(store_date):
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


def canonical_issue_number(value):
    value = clean_text(value)
    value = re.sub(r"^\s*issue\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*no\.?\s*", "", value, flags=re.IGNORECASE)

    while value.startswith("#"):
        value = value[1:].strip()

    return value.strip()


def normalize_issue_number(value):
    value = canonical_issue_number(value).casefold()
    value = re.sub(r"[^a-z0-9.]+", "", value)
    return value


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
    title = " ".join(title.split())

    stop_words = {
        "a",
        "an",
        "and",
        "by",
        "of",
        "the",
    }

    tokens = [
        token
        for token in title.split()
        if token not in stop_words
    ]

    return " ".join(tokens)


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()