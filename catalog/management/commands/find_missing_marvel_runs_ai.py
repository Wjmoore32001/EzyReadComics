import json
import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify
from openai import OpenAI

from catalog.models import ComicPublisher, ComicRun

from ._local_comicvine_helpers import (
    clean_text,
    copy_complete_comicvine_issues_to_catalog_run,
    find_possible_comicvine_volume_matches,
    format_comicvine_match_line,
    normalize_title,
    parse_date,
)


DEFAULT_MODEL = "gpt-5.5"
DEFAULT_PUBLISHER_NAME = "Marvel"
DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_BATCHES = 3


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


REQUIRED_TEXT_FIELDS = [
    "title",
    "start_year",
    "status",
    "first_issue_date",
    "last_issue_date",
    "description",
]

DATE_FIELDS = [
    "first_issue_date",
    "last_issue_date",
]

VALID_STATUSES = {
    "ongoing",
    "upcoming",
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
            default=DEFAULT_BATCH_SIZE,
            help="Maximum new runs to create from one successful batch. Default: 5",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help="Number of run candidates to ask AI for per batch. Default: 5",
        )
        parser.add_argument(
            "--max-batches",
            type=int,
            default=DEFAULT_MAX_BATCHES,
            help="Maximum AI batches to try when returned candidates already exist. Default: 3",
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
            help="Maximum local Comic Vine volume matches to show. Default: 8",
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
        limit = options["limit"]
        batch_size = options["batch_size"]
        max_batches = options["max_batches"]
        comicvine_match_limit = options["comicvine_match_limit"]

        if limit < 1:
            raise CommandError("--limit must be at least 1.")

        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")

        if max_batches < 1:
            raise CommandError("--max-batches must be at least 1.")

        if comicvine_match_limit < 1:
            raise CommandError("--comicvine-match-limit must be at least 1.")

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise CommandError(
                "OPENAI_API_KEY is not set. Add it to your .env file before running this command."
            )

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
            dry_run=dry_run,
            model=model,
            publisher_name=publisher_name,
            search_context=search_context,
            limit=limit,
            batch_size=batch_size,
            max_batches=max_batches,
            existing_runs=existing_runs,
            skip_comicvine_match=skip_comicvine_match,
            comicvine_match_limit=comicvine_match_limit,
        )

        client = OpenAI(api_key=api_key)

        rejected_candidates = []
        seen_candidate_keys = set()
        api_calls = 0
        created_count = 0
        skipped_count = 0

        for batch_number in range(1, max_batches + 1):
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"AI candidate batch {batch_number}/{max_batches}"
                )
            )

            data = self.call_run_search(
                client=client,
                model=model,
                search_context=search_context,
                publisher_name=publisher_name,
                batch_size=batch_size,
                rejected_candidates=rejected_candidates,
            )
            api_calls += 1

            if print_raw:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Raw run search JSON"))
                self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))

            candidates = normalize_candidate_list(data.get("candidates", []))
            self.print_result(candidates=candidates, verbose=verbose)

            batch_create_candidates, batch_rejections = classify_candidates(
                candidates=candidates,
                existing_runs=existing_runs,
                seen_candidate_keys=seen_candidate_keys,
            )

            rejected_candidates.extend(batch_rejections)
            skipped_count += len(batch_rejections)

            if not batch_create_candidates:
                if not candidates:
                    self.stdout.write("No candidates returned. Stopping.")
                    break

                self.stdout.write(
                    "No new complete runs in this batch. "
                    "Rejected candidates will be excluded from the next batch."
                )
                continue

            remaining_create_slots = limit - created_count
            create_candidates = batch_create_candidates[:remaining_create_slots]

            if dry_run:
                self.print_dry_run_create_preview(
                    candidates=create_candidates,
                    publisher_name=publisher_name,
                    skip_comicvine_match=skip_comicvine_match,
                    comicvine_match_limit=comicvine_match_limit,
                )

                created_count += len(create_candidates)
                break

            batch_created_count = self.apply_candidates(
                candidates=create_candidates,
                publisher_name=publisher_name,
                existing_runs=existing_runs,
                existing_run_keys=existing_run_keys,
                verbose=verbose,
                skip_comicvine_match=skip_comicvine_match,
                comicvine_match_limit=comicvine_match_limit,
            )

            created_count += batch_created_count

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created {batch_created_count} new run(s) from this batch."
                )
            )

            break

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Apply complete." if not dry_run else "Dry run complete."))
        self.stdout.write(f"OpenAI API calls made: {api_calls}")
        self.stdout.write(f"Created runs: {0 if dry_run else created_count}")
        self.stdout.write(f"Would create runs: {created_count if dry_run else 0}")
        self.stdout.write(f"Rejected/skipped candidates: {skipped_count}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog rows were created.")

    def write_header(
        self,
        *,
        dry_run,
        model,
        publisher_name,
        search_context,
        limit,
        batch_size,
        max_batches,
        existing_runs,
        skip_comicvine_match,
        comicvine_match_limit,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Find missing Marvel runs with AI"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write("Source: OpenAI Responses API web search")
        self.stdout.write(
            f"Catalog writes: {'none' if dry_run else 'create missing ComicRun rows only'}"
        )
        self.stdout.write("Creates issues from OpenAI: no")
        self.stdout.write(
            "Local Comic Vine issue copy: "
            + ("off" if skip_comicvine_match else "prompt after run create")
        )
        self.stdout.write("Creates volumes: no")
        self.stdout.write("Creates credits/images: no")
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Publisher: {publisher_name}")
        self.stdout.write(f"Search context: {search_context}")
        self.stdout.write(f"Batch size: {batch_size}")
        self.stdout.write(f"Max batches: {max_batches}")
        self.stdout.write(f"New run create limit: {limit}")
        self.stdout.write(f"Existing catalog runs checked locally: {len(existing_runs)}")
        self.stdout.write("Existing catalog runs sent to AI: no")
        self.stdout.write(f"Local Comic Vine match display limit: {comicvine_match_limit}")
        self.stdout.write("")

    def call_run_search(
        self,
        *,
        client,
        model,
        search_context,
        publisher_name,
        batch_size,
        rejected_candidates,
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
                            "Find confirmed current or upcoming comic run catalog fields. "
                            "Return compact JSON matching the schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_broad_prompt(
                            publisher_name=publisher_name,
                            batch_size=batch_size,
                            rejected_candidates=rejected_candidates,
                        ),
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
        ready_count = sum(
            1
            for candidate in candidates
            if candidate_has_required_fields(candidate)
        )
        incomplete_titles = [
            candidate.get("title") or "[blank title]"
            for candidate in candidates
            if not candidate_has_required_fields(candidate)
        ]

        self.stdout.write("")
        self.stdout.write(
            f"Run candidates found: {len(candidates)} "
            f"({ready_count} ready, {len(incomplete_titles)} incomplete)"
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
                "   Issue count: "
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

    def print_dry_run_create_preview(
        self,
        *,
        candidates,
        publisher_name,
        skip_comicvine_match,
        comicvine_match_limit,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Dry-run new runs that would be created"))

        for candidate in candidates:
            self.stdout.write(
                f"- {candidate['title']} ({candidate['start_year']})"
            )

        if skip_comicvine_match:
            return

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Local Comic Vine match preview"))

        for candidate in candidates:
            matches = find_possible_comicvine_volume_matches(
                title=candidate["title"],
                start_year=candidate["start_year"],
                publisher_name=publisher_name,
                limit=comicvine_match_limit,
            )

            self.stdout.write("")
            self.stdout.write(f"{candidate['title']} ({candidate['start_year']})")

            if not matches:
                self.stdout.write("  No likely local Comic Vine volume matches.")
                continue

            for index, match in enumerate(matches, start=1):
                self.stdout.write(format_comicvine_match_line(index=index, match=match))

    def apply_candidates(
        self,
        *,
        candidates,
        publisher_name,
        existing_runs,
        existing_run_keys,
        verbose,
        skip_comicvine_match,
        comicvine_match_limit,
    ):
        created_count = 0
        publisher = get_or_create_publisher(publisher_name)

        for candidate in candidates:
            title = clean_text(candidate.get("title"))
            start_year = clean_text(candidate.get("start_year"))
            candidate_key = run_key(title, start_year)

            if not candidate_has_required_fields(candidate):
                continue

            if candidate_key in existing_run_keys:
                continue

            if find_existing_catalog_run_match(candidate=candidate, existing_runs=existing_runs):
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

            existing_runs.append(run)
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

        return created_count

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
                    f"No likely local Comic Vine volume matches for {run.title} "
                    f"({run.start_year or 'unknown year'})."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Possible local Comic Vine matches for {run.title} "
                f"({run.start_year or 'unknown year'}):"
            )
        )

        for index, match in enumerate(matches, start=1):
            self.stdout.write(format_comicvine_match_line(index=index, match=match))

        selected_volume = self.get_selected_comicvine_volume(matches)

        if selected_volume is None:
            self.stdout.write("Skipped local Comic Vine issue copy.")
            return

        result = copy_complete_comicvine_issues_to_catalog_run(
            catalog_run=run,
            comicvine_volume=selected_volume,
            verbose=verbose,
            raise_issue_count=False,
        )

        self.print_local_copy_result(
            selected_volume=selected_volume,
            result=result,
        )

    def get_selected_comicvine_volume(self, matches):
        self.stdout.write("0. Skip local Comic Vine issue copy")
        choice = input("Select Comic Vine volume to copy issues from: ").strip()

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

        for message in result["messages"]:
            self.stdout.write(message)


def build_broad_prompt(*, publisher_name, batch_size, rejected_candidates):
    rejected_text = build_rejected_candidates_text(rejected_candidates)

    return f"""
Find up to {batch_size} current or upcoming {publisher_name} numbered comic runs.

Today: {date.today().isoformat()}

Do not return these candidates again:
{rejected_text}

Return fields: title, start_year, status, issue_count, first_issue_date, last_issue_date, description.

Rules:
- status is upcoming if issue #1 has a future on-sale date.
- status is ongoing if issue #1 is already on sale and the run is not completed.
- issue_count is released plus officially solicited issues.
- first_issue_date is issue #1 on-sale date.
- last_issue_date is latest released or solicited issue on-sale date.
- description is plain text under 180 characters.
- Exclude collected editions, trades, omnibuses, hardcovers, facsimiles, reprints, variants, posters, art books, toys, prose books, one-shots, completed older runs, and finite limited series unless a reliable source explicitly treats it as ongoing.
- Dates must use YYYY-MM-DD.
- Use null for unknown fields.

Return compact JSON only.
""".strip()


def build_rejected_candidates_text(rejected_candidates):
    if not rejected_candidates:
        return "none"

    return "; ".join(
        f"{item['title']} ({item.get('start_year') or 'unknown'})"
        for item in rejected_candidates[-30:]
        if item.get("title")
    ) or "none"


def classify_candidates(*, candidates, existing_runs, seen_candidate_keys):
    create_candidates = []
    rejected_candidates = []

    for candidate in candidates:
        title = clean_text(candidate.get("title"))
        start_year = clean_text(candidate.get("start_year"))
        key = run_key(title, start_year)

        if not candidate_has_required_fields(candidate):
            rejected_candidates.append(
                build_rejection(candidate=candidate, reason="incomplete")
            )
            continue

        if key and key in seen_candidate_keys:
            rejected_candidates.append(
                build_rejection(candidate=candidate, reason="repeated")
            )
            continue

        existing_match = find_existing_catalog_run_match(
            candidate=candidate,
            existing_runs=existing_runs,
        )

        if existing_match:
            rejected_candidates.append(
                build_rejection(
                    candidate=candidate,
                    reason=f"exists as {existing_match.title} ({existing_match.start_year or 'unknown'})",
                )
            )
            continue

        create_candidates.append(candidate)

        if key:
            seen_candidate_keys.add(key)

    for rejection in rejected_candidates:
        key = run_key(rejection.get("title"), rejection.get("start_year"))

        if key:
            seen_candidate_keys.add(key)

    return create_candidates, rejected_candidates


def build_rejection(*, candidate, reason):
    return {
        "title": clean_text(candidate.get("title")) or "[blank title]",
        "start_year": clean_text(candidate.get("start_year")),
        "reason": reason,
    }


def find_existing_catalog_run_match(*, candidate, existing_runs):
    candidate_title = clean_text(candidate.get("title"))
    candidate_year = clean_text(candidate.get("start_year"))
    candidate_key = run_key(candidate_title, candidate_year)

    for run in existing_runs:
        if run_key(run.title, run.start_year) == candidate_key:
            return run

    candidate_normalized_title = normalize_title(candidate_title)

    if not candidate_normalized_title:
        return None

    for run in existing_runs:
        run_year = clean_text(run.start_year)

        if candidate_year and run_year and candidate_year != run_year:
            continue

        run_normalized_title = normalize_title(run.title)

        if not run_normalized_title:
            continue

        if candidate_normalized_title == run_normalized_title:
            return run

        if (
            candidate_year
            and run_year
            and (
                candidate_normalized_title in run_normalized_title
                or run_normalized_title in candidate_normalized_title
            )
        ):
            return run

    return None


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

        normalized[key or f"unknown-{index}"] = normalized_candidate

    return list(normalized.values())


def normalize_candidate(candidate):
    return {
        "title": clean_text(candidate.get("title")),
        "start_year": clean_text(candidate.get("start_year")),
        "status": clean_text(candidate.get("status")),
        "issue_count": parse_positive_int(candidate.get("issue_count")),
        "first_issue_date": clean_text(candidate.get("first_issue_date")),
        "last_issue_date": clean_text(candidate.get("last_issue_date")),
        "description": clean_text(candidate.get("description")),
    }


def get_missing_candidate_fields(candidate):
    missing_fields = [
        field_name
        for field_name in REQUIRED_TEXT_FIELDS
        if not clean_text(candidate.get(field_name))
    ]

    issue_count = candidate.get("issue_count")

    if issue_count is None or issue_count <= 0:
        missing_fields.append("issue_count")

    for field_name in DATE_FIELDS:
        if parse_date(candidate.get(field_name)) is None and field_name not in missing_fields:
            missing_fields.append(field_name)

    status = clean_text(candidate.get("status")).lower()

    if status not in VALID_STATUSES and "status" not in missing_fields:
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
        return getattr(ComicRun, "STATUS_UPCOMING", "upcoming")

    if status == "ongoing":
        return getattr(ComicRun, "STATUS_ONGOING", "ongoing")

    return ComicRun.STATUS_UNKNOWN


def run_key(title, start_year):
    normalized_title = normalize_title(title)
    normalized_year = clean_text(start_year)

    if not normalized_title:
        return ""

    return f"{normalized_title}::{normalized_year}"


def parse_positive_int(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    if number < 1:
        return None

    return number