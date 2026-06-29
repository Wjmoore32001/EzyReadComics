import os
import re
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from comics.models import (
    ComicCreditRole,
    ComicIssue,
    ComicIssuePersonCredit,
    ComicPerson,
    ComicVolume,
)


ISSUE_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"
USER_AGENT = "EzyReadComics issue detail hydrator"
UNKNOWN_ROLE_NAME = "Unknown"


@dataclass
class HydrationResult:
    issues_needing_hydration_found: int = 0
    issues_checked: int = 0
    issues_hydrated: int = 0
    issues_marked_attempted_without_detail: int = 0
    issue_person_credits_synced: int = 0
    api_requests_made: int = 0


class Command(BaseCommand):
    help = "Hydrate local ComicIssue rows from Comic Vine issue detail records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--issue-limit",
            type=int,
            default=100,
            help="Maximum number of local issues to hydrate in one run. Defaults to 100.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=0,
            help="Seconds to pause after each Comic Vine issue request. Defaults to 0.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be changed without saving anything.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        issue_limit = options["issue_limit"]
        request_delay = options["request_delay"]
        dry_run = options["dry_run"]

        validate_options(
            issue_limit=issue_limit,
            request_delay=request_delay,
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine issue detail hydrator"))
        self.stdout.write("Hydrates local issues using the Comic Vine issue detail endpoint.")
        self.stdout.write("Also syncs issue-level person credits with roles.")
        self.stdout.write("Issues are selected by detail_hydration_attempted_at, not by empty optional fields.")
        self.stdout.write(f"Issue limit this run: {issue_limit}")
        self.stdout.write(f"Request delay: {request_delay}")

        with requests.Session() as session:
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                }
            )

            result = hydrate_issues(
                command=self,
                session=session,
                api_key=api_key,
                issue_limit=issue_limit,
                request_delay=request_delay,
                dry_run=dry_run,
            )

        print_summary(self, result)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def validate_options(issue_limit, request_delay):
    if issue_limit < 1:
        raise CommandError("issue-limit must be at least 1.")

    if issue_limit > 100:
        raise CommandError("issue-limit cannot be above 100 for now.")

    if request_delay < 0:
        raise CommandError("request-delay cannot be negative.")


def hydrate_issues(command, session, api_key, issue_limit, request_delay, dry_run):
    issues_queryset = get_issues_needing_hydration_queryset()
    issues_needing_hydration_found = issues_queryset.count()
    issues_to_check = list(issues_queryset[:issue_limit])

    result = HydrationResult(
        issues_needing_hydration_found=issues_needing_hydration_found,
    )

    command.stdout.write(f"Issues needing hydration found: {issues_needing_hydration_found}")

    if not issues_to_check:
        command.stdout.write("")
        command.stdout.write(command.style.SUCCESS("No issues need hydration."))
        command.stdout.write("No Comic Vine API request was needed.")
        return result

    for local_issue in issues_to_check:
        result.issues_checked += 1
        attempted_at = timezone.now()

        data = fetch_issue_detail(
            session=session,
            api_key=api_key,
            issue_id=local_issue.comicvine_id,
        )
        result.api_requests_made += 1

        remote_issue = data.get("results") or {}

        if not remote_issue or not remote_issue.get("id"):
            print_missing_detail_preview(
                command=command,
                local_issue=local_issue,
            )

            if not dry_run:
                mark_issue_hydration_attempted(
                    local_issue=local_issue,
                    attempted_at=attempted_at,
                )

            result.issues_marked_attempted_without_detail += 1

            if request_delay > 0:
                time.sleep(request_delay)

            continue

        issue_data = build_issue_data(
            local_issue=local_issue,
            remote_issue=remote_issue,
            attempted_at=attempted_at,
        )
        volume_data = remote_issue.get("volume") or {}
        remote_people = remote_issue.get("person_credits") or []

        print_issue_preview(
            command=command,
            local_issue=local_issue,
            issue_data=issue_data,
            remote_people=remote_people,
        )

        if not dry_run:
            people_synced = update_issue(
                local_issue=local_issue,
                issue_data=issue_data,
                volume_data=volume_data,
                remote_people=remote_people,
            )
            result.issue_person_credits_synced += people_synced
        else:
            result.issue_person_credits_synced += count_valid_person_credits(remote_people)

        result.issues_hydrated += 1

        if request_delay > 0:
            time.sleep(request_delay)

    return result


def get_issues_needing_hydration_queryset():
    return (
        ComicIssue.objects.filter(comicvine_id__isnull=False)
        .filter(
            Q(detail_hydration_attempted_at__isnull=True)
            | Q(date_last_updated__gt=F("detail_hydration_attempted_at"))
        )
        .order_by(
            F("detail_hydration_attempted_at").asc(nulls_first=True),
            "id",
        )
    )


def fetch_issue_detail(session, api_key, issue_id):
    url = ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_id)

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": ",".join(
            [
                "id",
                "aliases",
                "api_detail_url",
                "cover_date",
                "date_added",
                "date_last_updated",
                "deck",
                "description",
                "has_staff_review",
                "image",
                "issue_number",
                "name",
                "person_credits",
                "site_detail_url",
                "store_date",
                "volume",
            ]
        ),
    }

    return fetch_comicvine_json(session, url, params)


def build_issue_data(local_issue, remote_issue, attempted_at):
    image = remote_issue.get("image") or {}

    return {
        "comicvine_id": remote_issue.get("id") or local_issue.comicvine_id,
        "issue_number": remote_issue.get("issue_number") or local_issue.issue_number,
        "issue_title": remote_issue.get("name") or "",
        "cover_date": parse_comicvine_date(remote_issue.get("cover_date")),
        "store_date": parse_comicvine_date(remote_issue.get("store_date")),
        "date_added": parse_comicvine_datetime(remote_issue.get("date_added")) or local_issue.date_added,
        "date_last_updated": parse_comicvine_datetime(remote_issue.get("date_last_updated")) or local_issue.date_last_updated,
        "comicvine_url": remote_issue.get("site_detail_url") or local_issue.comicvine_url,
        "api_detail_url": remote_issue.get("api_detail_url") or local_issue.api_detail_url,
        "aliases": remote_issue.get("aliases") or "",
        "deck": remote_issue.get("deck") or "",
        "description": remote_issue.get("description") or "",
        "has_staff_review": bool(remote_issue.get("has_staff_review")),
        "detail_hydration_attempted_at": attempted_at,
        "detail_hydrated_at": attempted_at,
        "comicvine_image_icon_url": image.get("icon_url") or "",
        "comicvine_image_medium_url": image.get("medium_url") or "",
        "comicvine_image_screen_url": image.get("screen_url") or "",
        "comicvine_image_screen_large_url": image.get("screen_large_url") or "",
        "comicvine_image_small_url": image.get("small_url") or "",
        "comicvine_image_super_url": image.get("super_url") or "",
        "comicvine_image_thumb_url": image.get("thumb_url") or "",
        "comicvine_image_tiny_url": image.get("tiny_url") or "",
        "comicvine_image_original_url": image.get("original_url") or "",
        "comicvine_image_tags": image.get("image_tags") or "",
    }


def update_issue(local_issue, issue_data, volume_data, remote_people):
    with transaction.atomic():
        volume_object = local_issue.volume or get_or_create_volume_object(volume_data)

        local_issue.volume = volume_object
        local_issue.issue_number = issue_data["issue_number"]
        local_issue.issue_title = issue_data["issue_title"]

        local_issue.cover_date = issue_data["cover_date"]
        local_issue.store_date = issue_data["store_date"]

        local_issue.date_added = issue_data["date_added"]
        local_issue.date_last_updated = issue_data["date_last_updated"]

        local_issue.comicvine_url = issue_data["comicvine_url"]
        local_issue.api_detail_url = issue_data["api_detail_url"]

        local_issue.aliases = issue_data["aliases"]
        local_issue.deck = issue_data["deck"]
        local_issue.description = issue_data["description"]
        local_issue.has_staff_review = issue_data["has_staff_review"]

        local_issue.detail_hydration_attempted_at = issue_data["detail_hydration_attempted_at"]
        local_issue.detail_hydrated_at = issue_data["detail_hydrated_at"]

        local_issue.comicvine_image_icon_url = issue_data["comicvine_image_icon_url"]
        local_issue.comicvine_image_medium_url = issue_data["comicvine_image_medium_url"]
        local_issue.comicvine_image_screen_url = issue_data["comicvine_image_screen_url"]
        local_issue.comicvine_image_screen_large_url = issue_data["comicvine_image_screen_large_url"]
        local_issue.comicvine_image_small_url = issue_data["comicvine_image_small_url"]
        local_issue.comicvine_image_super_url = issue_data["comicvine_image_super_url"]
        local_issue.comicvine_image_thumb_url = issue_data["comicvine_image_thumb_url"]
        local_issue.comicvine_image_tiny_url = issue_data["comicvine_image_tiny_url"]
        local_issue.comicvine_image_original_url = issue_data["comicvine_image_original_url"]
        local_issue.comicvine_image_tags = issue_data["comicvine_image_tags"]

        local_issue.save(
            update_fields=[
                "volume",
                "issue_number",
                "issue_title",
                "cover_date",
                "store_date",
                "date_added",
                "date_last_updated",
                "comicvine_url",
                "api_detail_url",
                "aliases",
                "deck",
                "description",
                "has_staff_review",
                "detail_hydration_attempted_at",
                "detail_hydrated_at",
                "comicvine_image_icon_url",
                "comicvine_image_medium_url",
                "comicvine_image_screen_url",
                "comicvine_image_screen_large_url",
                "comicvine_image_small_url",
                "comicvine_image_super_url",
                "comicvine_image_thumb_url",
                "comicvine_image_tiny_url",
                "comicvine_image_original_url",
                "comicvine_image_tags",
            ]
        )

        return sync_issue_person_credits(
            issue=local_issue,
            remote_people=remote_people,
        )


def mark_issue_hydration_attempted(local_issue, attempted_at):
    local_issue.detail_hydration_attempted_at = attempted_at
    local_issue.save(update_fields=["detail_hydration_attempted_at"])


def get_or_create_volume_object(volume_data):
    volume_id = get_volume_id(volume_data)

    if not volume_id:
        return None

    volume_object, created = ComicVolume.objects.get_or_create(
        comicvine_id=volume_id,
        defaults={
            "name": volume_data.get("name") or "",
            "comicvine_url": volume_data.get("site_detail_url") or "",
            "api_detail_url": volume_data.get("api_detail_url") or "",
        },
    )

    if created:
        return volume_object

    fields_to_update = []

    name = volume_data.get("name") or ""
    if not volume_object.name and name:
        volume_object.name = name
        fields_to_update.append("name")

    comicvine_url = volume_data.get("site_detail_url") or ""
    if not volume_object.comicvine_url and comicvine_url:
        volume_object.comicvine_url = comicvine_url
        fields_to_update.append("comicvine_url")

    api_detail_url = volume_data.get("api_detail_url") or ""
    if not volume_object.api_detail_url and api_detail_url:
        volume_object.api_detail_url = api_detail_url
        fields_to_update.append("api_detail_url")

    if fields_to_update:
        volume_object.save(update_fields=fields_to_update)

    return volume_object


def sync_issue_person_credits(issue, remote_people):
    synced_credit_ids = []
    synced_count = 0

    for person_data in remote_people:
        person_comicvine_id = to_optional_int(person_data.get("id"))

        if not person_comicvine_id:
            continue

        person = get_or_update_person(person_data)
        role = get_or_create_credit_role(person_data.get("role"))

        credit, _ = ComicIssuePersonCredit.objects.update_or_create(
            issue=issue,
            person=person,
            role=role,
            defaults={
                "api_detail_url": person_data.get("api_detail_url") or "",
                "comicvine_url": person_data.get("site_detail_url") or "",
            },
        )

        synced_credit_ids.append(credit.id)
        synced_count += 1

    stale_credits = ComicIssuePersonCredit.objects.filter(issue=issue)

    if synced_credit_ids:
        stale_credits = stale_credits.exclude(id__in=synced_credit_ids)

    stale_credits.delete()

    return synced_count


def get_or_update_person(person_data):
    person_comicvine_id = to_optional_int(person_data.get("id"))
    name = person_data.get("name") or f"Comic Vine Person {person_comicvine_id}"

    person, created = ComicPerson.objects.get_or_create(
        comicvine_id=person_comicvine_id,
        defaults={
            "name": name,
            "api_detail_url": person_data.get("api_detail_url") or "",
            "comicvine_url": person_data.get("site_detail_url") or "",
        },
    )

    if created:
        return person

    fields_to_update = []

    if name and person.name != name:
        person.name = name
        fields_to_update.append("name")

    api_detail_url = person_data.get("api_detail_url") or ""
    if api_detail_url and person.api_detail_url != api_detail_url:
        person.api_detail_url = api_detail_url
        fields_to_update.append("api_detail_url")

    comicvine_url = person_data.get("site_detail_url") or ""
    if comicvine_url and person.comicvine_url != comicvine_url:
        person.comicvine_url = comicvine_url
        fields_to_update.append("comicvine_url")

    if fields_to_update:
        person.save(update_fields=fields_to_update)

    return person


def get_or_create_credit_role(raw_role_name):
    role_name = normalize_role_name(raw_role_name)

    role, _ = ComicCreditRole.objects.get_or_create(name=role_name)

    return role


def normalize_role_name(raw_role_name):
    role_name = (raw_role_name or "").strip()

    if not role_name:
        return UNKNOWN_ROLE_NAME

    return role_name[:100]


def count_valid_person_credits(remote_people):
    return sum(
        1
        for person_data in remote_people
        if to_optional_int(person_data.get("id"))
    )


def get_volume_id(volume):
    raw_volume_id = volume.get("id")

    if raw_volume_id:
        try:
            return int(raw_volume_id)
        except (TypeError, ValueError):
            pass

    api_detail_url = volume.get("api_detail_url") or ""
    match = re.search(r"4050-(\d+)", api_detail_url)

    if match:
        return int(match.group(1))

    return None


def fetch_comicvine_json(session, url, params):
    response = session.get(url, params=params, timeout=30)

    if response.status_code == 420:
        raise CommandError(
            "Comic Vine returned HTTP 420. This is probably a temporary rate or velocity limit. "
            "Wait before running the command again."
        )

    if response.status_code != 200:
        raise CommandError(
            f"Comic Vine request failed with HTTP status {response.status_code}."
        )

    data = response.json()

    status_code = data.get("status_code")
    error_message = data.get("error")

    if str(status_code) != "1":
        raise CommandError(
            f"Comic Vine API returned status_code={status_code}: {error_message}"
        )

    return data


def parse_comicvine_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_comicvine_datetime(value):
    if not value:
        return None

    try:
        parsed_datetime = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    if timezone.is_naive(parsed_datetime):
        return timezone.make_aware(parsed_datetime, timezone.get_current_timezone())

    return parsed_datetime


def to_optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def print_issue_preview(command, local_issue, issue_data, remote_people):
    command.stdout.write("")
    command.stdout.write(f"Issue hydrate: {local_issue}")
    command.stdout.write(f"Comic Vine Issue ID: {local_issue.comicvine_id}")
    command.stdout.write(f"Issue Title: {issue_data['issue_title']}")
    command.stdout.write(f"Date Last Updated on Comic Vine: {issue_data['date_last_updated'] or ''}")
    command.stdout.write(f"Person credits returned: {count_valid_person_credits(remote_people)}")


def print_missing_detail_preview(command, local_issue):
    command.stdout.write("")
    command.stdout.write(f"Issue hydration attempted but no usable detail was returned: {local_issue}")
    command.stdout.write(f"Comic Vine Issue ID: {local_issue.comicvine_id}")


def print_summary(command, result):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Issue hydration summary:"))
    command.stdout.write(f"Issues needing hydration found: {result.issues_needing_hydration_found}")
    command.stdout.write(f"Issues checked this run: {result.issues_checked}")
    command.stdout.write(f"Issues hydrated this run: {result.issues_hydrated}")
    command.stdout.write(f"Issues marked attempted without usable detail: {result.issues_marked_attempted_without_detail}")
    command.stdout.write(f"Issue person credits synced: {result.issue_person_credits_synced}")
    command.stdout.write(f"Comic Vine API requests made: {result.api_requests_made}")