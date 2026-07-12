import json
import os
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Prefetch
from openai import OpenAI

from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicRun,
    CreditPerson,
    CreditRole,
)


DEFAULT_MODEL = os.getenv(
    "OPENAI_MARVEL_OFFICIAL_ISSUE_MODEL",
    os.getenv("OPENAI_MARVEL_PROBE_MODEL", "gpt-5.6-luna"),
)
DEFAULT_PUBLISHER_NAME = "Marvel"
MARVEL_DOMAIN = "marvel.com"


ISSUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "issue_number": {"type": "string"},
        "published_date": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "writers": {
            "type": "array",
            "items": {"type": "string"},
        },
        "pencillers": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "issue_number",
        "published_date",
        "description",
        "writers",
        "pencillers",
    ],
}


RESULT_SCHEMA = {
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


class Command(BaseCommand):
    help = (
        "Test official Marvel-only issue filling. Uses only marvel.com, ignores issue titles, "
        "stores Published date, description, Writer credits, and Penciller credits."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            default=DEFAULT_MODEL,
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
            help="Comma-separated issue numbers to target, such as 1,2,3. Requires --run-id.",
        )
        parser.add_argument(
            "--limit-runs",
            type=int,
            default=1,
            help="Maximum number of runs to process. Default: 1",
        )
        parser.add_argument(
            "--limit-issues",
            type=int,
            default=5,
            help="Maximum issue numbers to request per run. Default: 5",
        )
        parser.add_argument(
            "--search-context",
            choices=["low", "medium", "high"],
            default="medium",
            help="Web-search context. Default: medium",
        )
        parser.add_argument(
            "--require-official-fields",
            action="store_true",
            help=(
                "Require issue number, published date, description, at least one Writer, "
                "and at least one Penciller before creating/updating an issue."
            ),
        )
        parser.add_argument(
            "--include-upcoming",
            action="store_true",
            help="Allow searches for future upcoming runs.",
        )
        parser.add_argument(
            "--clear-existing-titles",
            action="store_true",
            help="Blank existing ComicIssue.title values for issues touched by this command.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not create or update catalog data.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print raw JSON response.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print every issue candidate and database action.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise CommandError("OPENAI_API_KEY is not set.")

        publisher_name = clean_text(options["publisher"]) or DEFAULT_PUBLISHER_NAME
        run_id = options.get("run_id")
        forced_issue_numbers = parse_issue_numbers_argument(options.get("issue_numbers"))
        limit_runs = options["limit_runs"]
        limit_issues = options["limit_issues"]
        require_official_fields = options["require_official_fields"]

        if forced_issue_numbers and not run_id:
            raise CommandError("--issue-numbers requires --run-id.")

        if limit_runs < 1:
            raise CommandError("--limit-runs must be at least 1.")

        if limit_issues < 1:
            raise CommandError("--limit-issues must be at least 1.")

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
            run_id=run_id,
            forced_issue_numbers=forced_issue_numbers,
            limit_runs=limit_runs,
            limit_issues=limit_issues,
            runs=runs,
            include_upcoming=options["include_upcoming"],
            clear_existing_titles=options["clear_existing_titles"],
            require_official_fields=require_official_fields,
        )

        if not runs:
            self.stdout.write(
                self.style.SUCCESS(
                    "No runs need official Marvel issue filling. No OpenAI calls were made."
                )
            )
            return

        client = OpenAI(api_key=api_key)

        totals = {
            "api_calls": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "credits_added": 0,
        }

        for run in runs:
            existing_issues = get_existing_issues(run)
            target_issue_numbers = build_effective_target_issue_numbers(
                run=run,
                existing_issues=existing_issues,
                forced_issue_numbers=forced_issue_numbers,
            )[:limit_issues]

            if not target_issue_numbers:
                continue

            self.print_run_check(
                run=run,
                existing_issues=existing_issues,
                target_issue_numbers=target_issue_numbers,
            )

            data = self.call_marvel_issue_search(
                client=client,
                model=options["model"],
                search_context=options["search_context"],
                run=run,
                target_issue_numbers=target_issue_numbers,
                require_official_fields=require_official_fields,
            )
            totals["api_calls"] += 1

            if options["raw"]:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Raw official Marvel JSON"))
                self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))

            candidates = ensure_candidates_for_targets(
                candidates=normalize_candidate_list(data.get("issues", [])),
                target_issue_numbers=target_issue_numbers,
            )

            self.print_result(
                run=run,
                candidates=candidates,
                require_official_fields=require_official_fields,
                verbose=options["verbose"],
            )

            if options["dry_run"]:
                continue

            created, updated, skipped, credits_added = self.apply_candidates(
                run=run,
                candidates=candidates,
                clear_existing_titles=options["clear_existing_titles"],
                require_official_fields=require_official_fields,
                verbose=options["verbose"],
            )

            totals["created"] += created
            totals["updated"] += updated
            totals["skipped"] += skipped
            totals["credits_added"] += credits_added

        self.print_summary(
            totals=totals,
            dry_run=options["dry_run"],
        )

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
        issue_queryset = (
            ComicIssue.objects
            .prefetch_related("credits__person", "credits__role")
            .only(
                "id",
                "run_id",
                "issue_number",
                "title",
                "published_date",
                "description",
                "is_released",
            )
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
            has_incomplete_official_data = any(
                issue_needs_official_update(issue)
                for issue in existing_issues
            )

            if not has_missing_issues and not has_incomplete_official_data:
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
        run_id,
        forced_issue_numbers,
        limit_runs,
        limit_issues,
        runs,
        include_upcoming,
        clear_existing_titles,
        require_official_fields,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Official Marvel issue fill test"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'apply'}")
        self.stdout.write(f"Source: OpenAI Responses API web search, restricted to {MARVEL_DOMAIN}")
        self.stdout.write("Uses issue titles: no")
        self.stdout.write("Uses cover dates: no")

        if require_official_fields:
            self.stdout.write(
                "Required fields for issue row: issue_number, published_date, "
                "description, Writer, Penciller"
            )
        else:
            self.stdout.write("Required fields for issue row: issue_number, published_date")
            self.stdout.write("Optional official fields: description, Writer, Penciller")

        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Publisher: {publisher_name}")
        self.stdout.write(f"Search context: {search_context}")
        self.stdout.write(f"Run ID filter: {run_id or 'none'}")
        self.stdout.write(
            "Issue number filter: "
            f"{', '.join(forced_issue_numbers) if forced_issue_numbers else 'none'}"
        )
        self.stdout.write(f"Run limit: {limit_runs}")
        self.stdout.write(f"Issue limit per run: {limit_issues}")
        self.stdout.write(f"Runs needing official fill: {len(runs)}")
        self.stdout.write(
            "Include future upcoming runs: "
            f"{'yes' if include_upcoming else 'no'}"
        )
        self.stdout.write(
            "Require all official fields: "
            f"{'yes' if require_official_fields else 'no'}"
        )
        self.stdout.write(
            "Clear existing issue titles touched by command: "
            f"{'yes' if clear_existing_titles else 'no'}"
        )
        self.stdout.write("")

    def print_run_check(self, *, run, existing_issues, target_issue_numbers):
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"Checking run: {run}"))
        self.stdout.write(f"Catalog issue_count: {run.issue_count}")
        self.stdout.write(f"Existing attached issues: {len(existing_issues)}")
        self.stdout.write(
            "Existing issues missing official data: "
            f"{count_issues_needing_official_update(existing_issues)}"
        )
        self.stdout.write("Target issues: " + ", ".join(target_issue_numbers))
        self.stdout.write("")

    def call_marvel_issue_search(
        self,
        *,
        client,
        model,
        search_context,
        run,
        target_issue_numbers,
        require_official_fields,
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
                            "allowed_domains": [MARVEL_DOMAIN],
                        },
                    }
                ],
                tool_choice="required",
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Find official Marvel.com comic issue metadata. "
                            "Return compact JSON matching the schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_marvel_prompt(
                            run=run,
                            target_issue_numbers=target_issue_numbers,
                            require_official_fields=require_official_fields,
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "official_marvel_issue_metadata",
                        "strict": True,
                        "schema": RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI Marvel.com issue search failed for {run}: {exc}") from exc

        return parse_response_json(response.output_text)

    def print_result(self, *, run, candidates, require_official_fields, verbose):
        ready_count = sum(
            1
            for candidate in candidates
            if candidate_has_required_fields(
                candidate,
                require_official_fields=require_official_fields,
            )
        )
        incomplete_items = [
            f"#{candidate.get('issue_number') or '?'} ({', '.join(get_missing_candidate_fields(candidate, require_official_fields=require_official_fields))})"
            for candidate in candidates
            if not candidate_has_required_fields(
                candidate,
                require_official_fields=require_official_fields,
            )
        ]

        self.stdout.write("")
        self.stdout.write(
            "Official Marvel issue candidates: "
            f"{len(candidates)} ({ready_count} ready, {len(incomplete_items)} incomplete)"
        )

        if incomplete_items:
            self.stdout.write("Incomplete: " + "; ".join(incomplete_items))

        if not verbose:
            return

        self.stdout.write("")

        for index, candidate in enumerate(candidates, start=1):
            writers = ", ".join(candidate["writers"]) or "none"
            pencillers = ", ".join(candidate["pencillers"]) or "none"
            description = candidate.get("description") or "[blank]"
            missing_fields = get_missing_candidate_fields(
                candidate,
                require_official_fields=require_official_fields,
            )

            self.stdout.write(f"{index}. {run.title} #{candidate['issue_number']}")
            self.stdout.write(f"   Published date: {candidate.get('published_date') or 'unknown'}")
            self.stdout.write(f"   Description: {description}")
            self.stdout.write(f"   Writer: {writers}")
            self.stdout.write(f"   Penciller: {pencillers}")

            if missing_fields:
                self.stdout.write("   Missing: " + ", ".join(missing_fields))
            else:
                self.stdout.write("   Ready to write: yes")

            self.stdout.write("")

    def apply_candidates(
        self,
        *,
        run,
        candidates,
        clear_existing_titles,
        require_official_fields,
        verbose,
    ):
        existing_issue_map = {
            normalize_issue_number(issue.issue_number): issue
            for issue in get_existing_issues(run)
        }

        created_count = 0
        updated_count = 0
        skipped_count = 0
        credits_added_count = 0

        with transaction.atomic():
            writer_role = get_or_create_credit_role(
                name="Writer",
                display_order=10,
            )
            penciller_role = get_or_create_credit_role(
                name="Penciller",
                display_order=20,
            )

            for candidate in candidates:
                issue_number = canonical_issue_number(candidate.get("issue_number"))
                normalized_issue_number = normalize_issue_number(issue_number)

                if not candidate_has_required_fields(
                    candidate,
                    require_official_fields=require_official_fields,
                ):
                    skipped_count += 1
                    continue

                published_date = parse_date(candidate.get("published_date"))
                existing_issue = existing_issue_map.get(normalized_issue_number)

                if existing_issue:
                    changed = update_existing_issue_from_candidate(
                        issue=existing_issue,
                        candidate=candidate,
                        clear_existing_title=clear_existing_titles,
                    )

                    if changed:
                        existing_issue.save()
                        updated_count += 1

                        if verbose:
                            self.stdout.write(
                                self.style.SUCCESS(f"Updated ComicIssue: {existing_issue}")
                            )

                    issue = existing_issue
                else:
                    issue = ComicIssue.objects.create(
                        run=run,
                        issue_number=issue_number,
                        title="",
                        published_date=published_date,
                        cover_date=None,
                        is_released=published_date <= date.today(),
                        description=clean_text(candidate.get("description")),
                    )
                    existing_issue_map[normalized_issue_number] = issue
                    created_count += 1

                    if verbose:
                        self.stdout.write(
                            self.style.SUCCESS(f"Created ComicIssue: {issue}")
                        )

                credits_added_count += add_issue_credits(
                    issue=issue,
                    role=writer_role,
                    names=candidate["writers"],
                )
                credits_added_count += add_issue_credits(
                    issue=issue,
                    role=penciller_role,
                    names=candidate["pencillers"],
                )

        return created_count, updated_count, skipped_count, credits_added_count

    def print_summary(self, *, totals, dry_run):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Official Marvel issue fill complete."))
        self.stdout.write(f"OpenAI API calls made: {totals['api_calls']}")
        self.stdout.write(f"Created issues: {totals['created']}")
        self.stdout.write(f"Updated issues: {totals['updated']}")
        self.stdout.write(f"Skipped candidates: {totals['skipped']}")
        self.stdout.write(f"Issue credits added: {totals['credits_added']}")

        if dry_run:
            self.stdout.write("Dry run only. No catalog data was created or updated.")


def build_marvel_prompt(*, run, target_issue_numbers, require_official_fields):
    issue_text = ", ".join(
        canonical_issue_number(issue_number)
        for issue_number in target_issue_numbers
    )

    required_text = (
        "Every returned issue should have issue_number, published_date, description, at least one Writer, and at least one Penciller. "
        "If any of those fields cannot be found on Marvel.com, return null/empty values so the local command can reject that issue."
        if require_official_fields
        else "published_date is required when available. description, writers, and pencillers should still be filled from Marvel.com when shown."
    )

    return f"""
Find official Marvel.com issue metadata.

Comic run:
Publisher: {run.publisher.name}
Run title: {run.title}
Start year: {run.start_year or "unknown"}

Issue numbers:
{issue_text}

Only use official Marvel.com issue pages.

For each issue:
- issue_number: the requested issue number
- published_date: the date shown by Marvel as "Published"
- description: the official issue description/synopsis text on the Marvel page
- writers: names listed by Marvel with the Writer credit
- pencillers: names listed by Marvel with the Penciller credit

Strictness:
{required_text}

Rules:
- Do not return issue titles.
- Do not return cover dates.
- Do not use community sites, wikis, shops, League of Comic Geeks, Comic Vine, or previews from non-Marvel sites.
- Match this exact run, start year, and issue number.
- Use YYYY-MM-DD for published_date.
- If the Marvel page exists but description is blank or unavailable, use an empty string.
- If Writer or Penciller is not listed, use an empty array.
- If no official Marvel page can be found for an issue, return that issue with published_date null.

Return one object for every requested issue number.
""".strip()


def get_existing_issues(run):
    return list(
        run.issues.prefetch_related(
            "credits__person",
            "credits__role",
        ).order_by(
            "published_date",
            "issue_number",
            "id",
        )
    )


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
    existing_issue_map = {
        normalize_issue_number(issue.issue_number): issue
        for issue in existing_issues
    }
    target_issue_numbers = []

    for issue_number in forced_issue_numbers:
        existing_issue = existing_issue_map.get(normalize_issue_number(issue_number))

        if existing_issue is None or issue_needs_official_update(existing_issue):
            target_issue_numbers.append(issue_number)

    return sort_issue_numbers(unique_issue_numbers(target_issue_numbers))


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

        if issue_number and issue_needs_official_update(issue):
            issue_numbers.append(issue_number)

    return sort_issue_numbers(unique_issue_numbers(issue_numbers))


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


def issue_needs_official_update(issue):
    if issue.issue_number != canonical_issue_number(issue.issue_number):
        return True

    if issue.published_date is None:
        return True

    if not clean_text(issue.description):
        return True

    if not issue_has_role(issue, "Writer"):
        return True

    if not issue_has_role(issue, "Penciller"):
        return True

    return False


def count_issues_needing_official_update(issues):
    return sum(
        1
        for issue in issues
        if issue_needs_official_update(issue)
    )


def issue_has_role(issue, role_name):
    target_role_name = role_name.casefold()

    for credit in issue.credits.all():
        if credit.role.name.casefold() == target_role_name:
            return True

    return False


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
                "published_date": None,
                "description": "",
                "writers": [],
                "pencillers": [],
            }

    return sort_candidates(candidate_map.values())


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
        "published_date": clean_text(candidate.get("published_date")) or None,
        "description": clean_text(candidate.get("description")),
        "writers": normalize_name_list(candidate.get("writers")),
        "pencillers": normalize_name_list(candidate.get("pencillers")),
    }


def normalize_name_list(value):
    if not value:
        return []

    if isinstance(value, str):
        value = [value]

    names = []
    seen = set()

    for item in value:
        name = clean_credit_name(item)
        key = name.casefold()

        if not name or key in seen:
            continue

        seen.add(key)
        names.append(name)

    return names


def clean_credit_name(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,;")


def candidate_has_required_fields(candidate, *, require_official_fields):
    return not get_missing_candidate_fields(
        candidate,
        require_official_fields=require_official_fields,
    )


def get_missing_candidate_fields(candidate, *, require_official_fields):
    missing_fields = []

    if not canonical_issue_number(candidate.get("issue_number")):
        missing_fields.append("issue_number")

    if parse_date(candidate.get("published_date")) is None:
        missing_fields.append("published_date")

    if require_official_fields:
        if not clean_text(candidate.get("description")):
            missing_fields.append("description")

        if not candidate.get("writers"):
            missing_fields.append("writer")

        if not candidate.get("pencillers"):
            missing_fields.append("penciller")

    return missing_fields


def update_existing_issue_from_candidate(*, issue, candidate, clear_existing_title):
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

    candidate_published_date = parse_date(candidate.get("published_date"))

    if candidate_published_date is not None and issue.published_date != candidate_published_date:
        issue.published_date = candidate_published_date
        changed = True

    if candidate_published_date is not None:
        candidate_is_released = candidate_published_date <= date.today()

        if issue.is_released != candidate_is_released:
            issue.is_released = candidate_is_released
            changed = True

    candidate_description = clean_text(candidate.get("description"))

    if candidate_description and issue.description != candidate_description:
        issue.description = candidate_description
        changed = True

    if clear_existing_title and issue.title:
        issue.title = ""
        changed = True

    return changed


def get_or_create_credit_role(*, name, display_order):
    role = CreditRole.objects.filter(name__iexact=name).first()

    if role is None:
        return CreditRole.objects.create(
            name=name,
            display_order=display_order,
            show_by_default=True,
        )

    changed = False

    if role.display_order != display_order:
        role.display_order = display_order
        changed = True

    if not role.show_by_default:
        role.show_by_default = True
        changed = True

    if changed:
        role.save(update_fields=["display_order", "show_by_default"])

    return role


def add_issue_credits(*, issue, role, names):
    created_count = 0

    for index, name in enumerate(names, start=1):
        person = get_or_create_credit_person(name)

        _, created = ComicIssueCredit.objects.get_or_create(
            issue=issue,
            person=person,
            role=role,
            defaults={
                "credit_order": index,
            },
        )

        if created:
            created_count += 1

    return created_count


def get_or_create_credit_person(name):
    existing = CreditPerson.objects.filter(name__iexact=name).first()

    if existing:
        return existing

    return CreditPerson.objects.create(name=name)


def parse_response_json(output_text):
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Could not parse model output as JSON: {exc}") from exc


def parse_issue_numbers_argument(value):
    if not value:
        return []

    issue_numbers = []

    for part in re.split(r"[,\s]+", value):
        issue_number = canonical_issue_number(part)

        if issue_number:
            issue_numbers.append(issue_number)

    return sort_issue_numbers(unique_issue_numbers(issue_numbers))


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
    return re.sub(r"[^a-z0-9.]+", "", value)


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


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()