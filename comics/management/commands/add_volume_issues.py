import os
import re
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from comics.models import (
    ComicCreditRole,
    ComicIssue,
    ComicIssuePersonCredit,
    ComicPerson,
    ComicVolume,
    ComicVolumePersonCredit,
)


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
ISSUE_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"
VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"

USER_AGENT = "EzyReadComics targeted volume issue importer"
ISSUE_PAGE_LIMIT = 100
UNKNOWN_ROLE_NAME = "Unknown"


@dataclass
class ImportResult:
    volume_id: int
    volume_name: str = ""
    volume_created: bool = False
    selected_filter: str = ""

    issue_pages_fetched: int = 0
    total_remote_issues: int = 0
    issues_checked: int = 0
    issues_created: int = 0
    existing_issues_skipped: int = 0
    existing_issues_linked_to_volume: int = 0
    missing_data_skipped: int = 0

    volume_hydrated: bool = False
    volume_marked_attempted_without_detail: bool = False
    volume_people_synced: int = 0

    target_issues_found_for_hydration: int = 0
    issues_hydrated: int = 0
    issues_marked_attempted_without_detail: int = 0
    issue_person_credits_synced: int = 0

    api_requests_made: int = 0


class Command(BaseCommand):
    help = (
        "Prompt for a Comic Vine volume ID or issue ID, import all issues "
        "for the related Comic Vine volume, then hydrate that volume and its issues."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be changed without saving anything.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=0,
            help="Seconds to pause after each Comic Vine request. Defaults to 0.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        dry_run = options["dry_run"]
        request_delay = options["request_delay"]

        if request_delay < 0:
            raise CommandError("request-delay cannot be negative.")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Targeted Comic Vine volume issue importer"))
        self.stdout.write("This imports every issue tied to one Comic Vine volume.")
        self.stdout.write("It then hydrates that volume and every local issue tied to it.")
        self.stdout.write("Enter plain Comic Vine IDs only, without 4000- or 4050- prefixes.")

        choice = prompt_for_choice()
        source_id = prompt_for_source_id(choice)

        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT})

            if choice == "1":
                volume_data, volume_created, api_requests = resolve_volume_from_volume_id(
                    command=self,
                    session=session,
                    api_key=api_key,
                    volume_id=source_id,
                    dry_run=dry_run,
                )
            else:
                volume_data, volume_created, api_requests = resolve_volume_from_issue_id(
                    command=self,
                    session=session,
                    api_key=api_key,
                    issue_id=source_id,
                    dry_run=dry_run,
                )

            if request_delay > 0 and api_requests > 0:
                time.sleep(request_delay)

            result = import_issues_for_volume(
                command=self,
                session=session,
                api_key=api_key,
                volume_data=volume_data,
                volume_created=volume_created,
                starting_api_requests=api_requests,
                request_delay=request_delay,
                dry_run=dry_run,
            )

            hydrate_target_volume_and_issues(
                command=self,
                session=session,
                api_key=api_key,
                result=result,
                request_delay=request_delay,
                dry_run=dry_run,
            )

        print_summary(self, result)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def prompt_for_choice():
    while True:
        print("")
        print("What do you want to enter?")
        print("1. Volume ID")
        print("2. Issue ID")

        choice = input("Enter 1 or 2: ").strip()

        if choice in {"1", "2"}:
            return choice

        print("Please enter 1 or 2.")


def prompt_for_source_id(choice):
    label = "volume ID" if choice == "1" else "issue ID"

    while True:
        raw_value = input(f"Enter Comic Vine {label}: ").strip()

        try:
            source_id = int(raw_value)
        except ValueError:
            print("Please enter a number.")
            continue

        if source_id > 0:
            return source_id

        print("Please enter a positive ID.")


def resolve_volume_from_volume_id(command, session, api_key, volume_id, dry_run):
    local_volume = ComicVolume.objects.filter(comicvine_id=volume_id).first()

    if local_volume:
        command.stdout.write("")
        command.stdout.write(command.style.SUCCESS("Volume found locally."))
        command.stdout.write(f"Volume: {local_volume.name}")
        command.stdout.write(f"Comic Vine Volume ID: {local_volume.comicvine_id}")
        command.stdout.write(f"Known issue count from volume: {local_volume.count_of_issues or 'unknown'}")

        return build_volume_data_from_local(local_volume), False, 0

    command.stdout.write("")
    command.stdout.write("Volume was not found locally.")
    command.stdout.write("Fetching volume detail from Comic Vine before importing issues.")

    data = fetch_volume_detail(
        session=session,
        api_key=api_key,
        volume_id=volume_id,
    )
    remote_volume = data.get("results") or {}

    if not remote_volume or not remote_volume.get("id"):
        raise CommandError(
            f"Comic Vine did not return usable volume detail for volume ID {volume_id}."
        )

    volume_data = build_volume_data_from_remote(remote_volume, fallback_volume_id=volume_id)

    if not dry_run:
        save_volume(volume_data)

    command.stdout.write(command.style.SUCCESS("Volume fetched from Comic Vine."))
    command.stdout.write(f"Volume: {volume_data['name']}")
    command.stdout.write(f"Comic Vine Volume ID: {volume_data['comicvine_id']}")
    command.stdout.write(f"Known issue count from volume: {volume_data.get('count_of_issues') or 'unknown'}")

    return volume_data, True, 1


def resolve_volume_from_issue_id(command, session, api_key, issue_id, dry_run):
    local_issue = (
        ComicIssue.objects.filter(comicvine_id=issue_id)
        .select_related("volume")
        .first()
    )

    if local_issue and local_issue.volume and local_issue.volume.comicvine_id:
        command.stdout.write("")
        command.stdout.write(command.style.SUCCESS("Issue found locally with a linked volume."))
        command.stdout.write(f"Issue: {local_issue}")
        command.stdout.write(f"Comic Vine Issue ID: {local_issue.comicvine_id}")
        command.stdout.write(f"Volume: {local_issue.volume.name}")
        command.stdout.write(f"Comic Vine Volume ID: {local_issue.volume.comicvine_id}")
        command.stdout.write(f"Known issue count from volume: {local_issue.volume.count_of_issues or 'unknown'}")

        return build_volume_data_from_local(local_issue.volume), False, 0

    command.stdout.write("")
    command.stdout.write("Issue was not found locally with a linked volume.")
    command.stdout.write("Fetching issue detail from Comic Vine to find its volume.")

    issue_data = fetch_issue_detail(
        session=session,
        api_key=api_key,
        issue_id=issue_id,
    )
    remote_issue = issue_data.get("results") or {}

    if not remote_issue or not remote_issue.get("id"):
        raise CommandError(
            f"Comic Vine did not return usable issue detail for issue ID {issue_id}."
        )

    embedded_volume = remote_issue.get("volume") or {}
    volume_id = get_volume_id(embedded_volume)

    if not volume_id:
        raise CommandError(
            f"Comic Vine issue ID {issue_id} did not include a usable volume ID."
        )

    local_volume = ComicVolume.objects.filter(comicvine_id=volume_id).first()

    if local_volume:
        command.stdout.write(command.style.SUCCESS("Related volume found locally."))
        command.stdout.write(f"Volume: {local_volume.name}")
        command.stdout.write(f"Comic Vine Volume ID: {local_volume.comicvine_id}")
        command.stdout.write(f"Known issue count from volume: {local_volume.count_of_issues or 'unknown'}")

        return build_volume_data_from_local(local_volume), False, 1

    command.stdout.write("Related volume was not found locally.")
    command.stdout.write("Fetching related volume detail from Comic Vine.")

    volume_detail_data = fetch_volume_detail(
        session=session,
        api_key=api_key,
        volume_id=volume_id,
    )
    remote_volume = volume_detail_data.get("results") or {}

    if remote_volume and remote_volume.get("id"):
        volume_data = build_volume_data_from_remote(
            remote_volume=remote_volume,
            fallback_volume_id=volume_id,
        )
    else:
        volume_data = build_minimal_volume_data_from_embedded_volume(
            embedded_volume=embedded_volume,
            fallback_volume_id=volume_id,
        )

    if not dry_run:
        save_volume(volume_data)

    command.stdout.write(command.style.SUCCESS("Related volume prepared."))
    command.stdout.write(f"Volume: {volume_data['name']}")
    command.stdout.write(f"Comic Vine Volume ID: {volume_data['comicvine_id']}")
    command.stdout.write(f"Known issue count from volume: {volume_data.get('count_of_issues') or 'unknown'}")

    return volume_data, True, 2


def import_issues_for_volume(
    command,
    session,
    api_key,
    volume_data,
    volume_created,
    starting_api_requests,
    request_delay,
    dry_run,
):
    volume_id = volume_data["comicvine_id"]

    result = ImportResult(
        volume_id=volume_id,
        volume_name=volume_data["name"],
        volume_created=volume_created,
        api_requests_made=starting_api_requests,
    )

    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Importing issues for volume"))
    command.stdout.write(f"Volume: {volume_data['name']}")
    command.stdout.write(f"Comic Vine Volume ID: {volume_id}")
    command.stdout.write(f"Known issue count from volume detail: {volume_data.get('count_of_issues') or 'unknown'}")

    volume_filter, first_page_data = fetch_first_volume_issue_page(
        session=session,
        api_key=api_key,
        volume_id=volume_id,
    )
    result.api_requests_made += 1
    result.selected_filter = volume_filter

    offset = 0

    while True:
        if offset == 0:
            data = first_page_data
        else:
            data = fetch_volume_issue_page(
                session=session,
                api_key=api_key,
                volume_filter=volume_filter,
                limit=ISSUE_PAGE_LIMIT,
                offset=offset,
            )
            result.api_requests_made += 1

        total_results = to_int(data.get("number_of_total_results")) or 0
        issues = data.get("results") or []

        result.issue_pages_fetched += 1
        result.total_remote_issues = total_results

        command.stdout.write("")
        command.stdout.write(f"Issue page fetched: {result.issue_pages_fetched}")
        command.stdout.write(f"Comic Vine issue filter: {volume_filter}")
        command.stdout.write(f"Total remote issues for this volume: {total_results}")
        command.stdout.write(f"Current offset: {offset}")
        command.stdout.write(f"Issues returned in this page: {len(issues)}")

        if not issues:
            break

        existing_issue_ids = get_existing_issue_ids(issues)

        for issue in issues:
            result.issues_checked += 1

            save_result = save_or_link_issue(
                issue=issue,
                volume_data=volume_data,
                existing_issue_ids=existing_issue_ids,
                dry_run=dry_run,
            )

            if save_result == "created":
                result.issues_created += 1
            elif save_result == "existing":
                result.existing_issues_skipped += 1
            elif save_result == "linked":
                result.existing_issues_linked_to_volume += 1
            elif save_result == "missing":
                result.missing_data_skipped += 1

        offset += len(issues)

        if total_results > 0 and offset >= total_results:
            break

        if len(issues) < ISSUE_PAGE_LIMIT:
            break

        if request_delay > 0:
            time.sleep(request_delay)

    if not dry_run:
        refresh_volume_latest_issue_store_date(volume_id)

    return result


def hydrate_target_volume_and_issues(command, session, api_key, result, request_delay, dry_run):
    local_volume = ComicVolume.objects.filter(comicvine_id=result.volume_id).first()

    if not local_volume:
        if dry_run:
            command.stdout.write("")
            command.stdout.write(
                command.style.WARNING(
                    "Dry run: volume was not saved, so targeted hydration can only be previewed from API data."
                )
            )
            return

        raise CommandError(
            f"Local volume {result.volume_id} was not found before hydration."
        )

    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Hydrating target volume"))
    command.stdout.write(f"Volume: {local_volume.name}")
    command.stdout.write(f"Comic Vine Volume ID: {local_volume.comicvine_id}")

    attempted_at = timezone.now()

    volume_detail_data = fetch_volume_detail(
        session=session,
        api_key=api_key,
        volume_id=local_volume.comicvine_id,
    )
    result.api_requests_made += 1

    remote_volume = volume_detail_data.get("results") or {}

    if not remote_volume or not remote_volume.get("id"):
        command.stdout.write(
            command.style.WARNING(
                "Comic Vine did not return usable volume detail for targeted hydration."
            )
        )

        if not dry_run:
            mark_volume_hydration_attempted(
                local_volume=local_volume,
                attempted_at=attempted_at,
            )

        result.volume_marked_attempted_without_detail = True
    else:
        volume_data = build_volume_hydration_data(
            local_volume=local_volume,
            remote_volume=remote_volume,
            attempted_at=attempted_at,
        )
        remote_people = remote_volume.get("people") or []

        print_volume_hydration_preview(
            command=command,
            local_volume=local_volume,
            volume_data=volume_data,
            remote_people=remote_people,
        )

        if not dry_run:
            result.volume_people_synced = update_volume_detail(
                local_volume=local_volume,
                volume_data=volume_data,
                remote_people=remote_people,
            )
        else:
            result.volume_people_synced = count_valid_people(remote_people)

        result.volume_hydrated = True

    if request_delay > 0:
        time.sleep(request_delay)

    hydrate_target_volume_issues(
        command=command,
        session=session,
        api_key=api_key,
        local_volume=local_volume,
        result=result,
        request_delay=request_delay,
        dry_run=dry_run,
    )


def hydrate_target_volume_issues(
    command,
    session,
    api_key,
    local_volume,
    result,
    request_delay,
    dry_run,
):
    issues_to_hydrate = list(
        ComicIssue.objects.filter(
            volume=local_volume,
            comicvine_id__isnull=False,
        ).order_by("store_date", "issue_number", "id")
    )

    result.target_issues_found_for_hydration = len(issues_to_hydrate)

    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Hydrating target volume issues"))
    command.stdout.write(f"Issues found locally for this volume: {len(issues_to_hydrate)}")

    if not issues_to_hydrate:
        command.stdout.write("No local issues were found for this volume.")
        return

    for local_issue in issues_to_hydrate:
        attempted_at = timezone.now()

        issue_detail_data = fetch_issue_detail_for_hydration(
            session=session,
            api_key=api_key,
            issue_id=local_issue.comicvine_id,
        )
        result.api_requests_made += 1

        remote_issue = issue_detail_data.get("results") or {}

        if not remote_issue or not remote_issue.get("id"):
            print_missing_issue_detail_preview(
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

        issue_data = build_issue_hydration_data(
            local_issue=local_issue,
            remote_issue=remote_issue,
            attempted_at=attempted_at,
        )
        remote_people = remote_issue.get("person_credits") or []

        print_issue_hydration_preview(
            command=command,
            local_issue=local_issue,
            issue_data=issue_data,
            remote_people=remote_people,
        )

        if not dry_run:
            people_synced = update_issue_detail(
                local_issue=local_issue,
                target_volume=local_volume,
                issue_data=issue_data,
                remote_people=remote_people,
            )
            result.issue_person_credits_synced += people_synced
        else:
            result.issue_person_credits_synced += count_valid_person_credits(remote_people)

        result.issues_hydrated += 1

        if request_delay > 0:
            time.sleep(request_delay)


def fetch_first_volume_issue_page(session, api_key, volume_id):
    volume_filter = f"volume:{volume_id}"

    data = fetch_volume_issue_page(
        session=session,
        api_key=api_key,
        volume_filter=volume_filter,
        limit=ISSUE_PAGE_LIMIT,
        offset=0,
    )

    return volume_filter, data


def fetch_volume_issue_page(session, api_key, volume_filter, limit, offset):
    params = {
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "offset": offset,
        "sort": "issue_number:asc",
        "filter": volume_filter,
        "field_list": ",".join(
            [
                "id",
                "aliases",
                "api_detail_url",
                "issue_number",
                "name",
                "date_added",
                "date_last_updated",
                "cover_date",
                "store_date",
                "site_detail_url",
                "deck",
                "description",
                "has_staff_review",
                "image",
                "volume",
            ]
        ),
    }

    return fetch_comicvine_json(session, ISSUES_URL, params)


def fetch_issue_detail(session, api_key, issue_id):
    url = ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_id)

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": ",".join(
            [
                "id",
                "api_detail_url",
                "issue_number",
                "name",
                "site_detail_url",
                "volume",
            ]
        ),
    }

    return fetch_comicvine_json(session, url, params)


def fetch_issue_detail_for_hydration(session, api_key, issue_id):
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


def fetch_volume_detail(session, api_key, volume_id):
    url = VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_id)

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": ",".join(
            [
                "id",
                "aliases",
                "api_detail_url",
                "count_of_issues",
                "date_added",
                "date_last_updated",
                "deck",
                "description",
                "first_issue",
                "image",
                "last_issue",
                "name",
                "people",
                "publisher",
                "site_detail_url",
                "start_year",
            ]
        ),
    }

    return fetch_comicvine_json(session, url, params)


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


def get_existing_issue_ids(issues):
    issue_ids = [
        to_int(issue.get("id"))
        for issue in issues
        if to_int(issue.get("id"))
    ]

    return set(
        ComicIssue.objects.filter(
            comicvine_id__in=issue_ids,
        ).values_list("comicvine_id", flat=True)
    )


def save_or_link_issue(issue, volume_data, existing_issue_ids, dry_run):
    issue_id = to_int(issue.get("id"))

    if not issue_id:
        return "missing"

    if issue_id in existing_issue_ids:
        existing_issue = (
            ComicIssue.objects.filter(comicvine_id=issue_id)
            .select_related("volume")
            .first()
        )

        if not existing_issue:
            return "existing"

        if (
            existing_issue.volume
            and existing_issue.volume.comicvine_id == volume_data["comicvine_id"]
        ):
            return "existing"

        if dry_run:
            return "linked"

        volume_object = get_or_create_volume_object(volume_data)
        existing_issue.volume = volume_object
        existing_issue.save(update_fields=["volume"])

        return "linked"

    if dry_run:
        return "created"

    with transaction.atomic():
        volume_object = get_or_create_volume_object(volume_data)
        image = issue.get("image") or {}

        ComicIssue.objects.create(
            comicvine_id=issue_id,
            volume=volume_object,
            issue_number=issue.get("issue_number") or "",
            issue_title=issue.get("name") or "",
            cover_date=parse_comicvine_date(issue.get("cover_date")),
            store_date=parse_comicvine_date(issue.get("store_date")),
            date_added=parse_comicvine_datetime(issue.get("date_added")),
            date_last_updated=parse_comicvine_datetime(issue.get("date_last_updated")),
            comicvine_url=issue.get("site_detail_url") or "",
            api_detail_url=issue.get("api_detail_url") or "",
            aliases=issue.get("aliases") or "",
            deck=issue.get("deck") or "",
            description=issue.get("description") or "",
            has_staff_review=bool(issue.get("has_staff_review")),
            comicvine_image_icon_url=image.get("icon_url") or "",
            comicvine_image_medium_url=image.get("medium_url") or "",
            comicvine_image_screen_url=image.get("screen_url") or "",
            comicvine_image_screen_large_url=image.get("screen_large_url") or "",
            comicvine_image_small_url=image.get("small_url") or "",
            comicvine_image_super_url=image.get("super_url") or "",
            comicvine_image_thumb_url=image.get("thumb_url") or "",
            comicvine_image_tiny_url=image.get("tiny_url") or "",
            comicvine_image_original_url=image.get("original_url") or "",
            comicvine_image_tags=image.get("image_tags") or "",
        )

    return "created"


def save_volume(volume_data):
    with transaction.atomic():
        volume_object = get_or_create_volume_object(volume_data)

        update_fields = []

        fields_to_copy = [
            "publisher",
            "publisher_comicvine_id",
            "publisher_api_detail_url",
            "start_year",
            "count_of_issues",
            "date_added",
            "date_last_updated",
            "comicvine_url",
            "api_detail_url",
            "aliases",
            "deck",
            "description",
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
            "display_image_url",
            "display_image_source",
            "first_issue_comicvine_id",
            "first_issue_number",
            "first_issue_name",
            "first_issue_api_url",
            "last_issue_comicvine_id",
            "last_issue_number",
            "last_issue_name",
            "last_issue_api_url",
        ]

        if volume_data["name"] and volume_object.name != volume_data["name"]:
            volume_object.name = volume_data["name"]
            update_fields.append("name")

        for field_name in fields_to_copy:
            new_value = volume_data.get(field_name)

            if new_value in [None, ""]:
                continue

            if getattr(volume_object, field_name) != new_value:
                setattr(volume_object, field_name, new_value)
                update_fields.append(field_name)

        if update_fields:
            volume_object.save(update_fields=update_fields)

        return volume_object


def get_or_create_volume_object(volume_data):
    volume_id = volume_data["comicvine_id"]
    volume_name = volume_data["name"] or f"Comic Vine Volume {volume_id}"

    volume_object, _ = ComicVolume.objects.get_or_create(
        comicvine_id=volume_id,
        defaults={
            "name": volume_name,
            "publisher": volume_data.get("publisher") or "",
            "publisher_comicvine_id": volume_data.get("publisher_comicvine_id"),
            "publisher_api_detail_url": volume_data.get("publisher_api_detail_url") or "",
            "start_year": volume_data.get("start_year") or "",
            "count_of_issues": volume_data.get("count_of_issues"),
            "date_added": volume_data.get("date_added"),
            "date_last_updated": volume_data.get("date_last_updated"),
            "comicvine_url": volume_data.get("comicvine_url") or "",
            "api_detail_url": volume_data.get("api_detail_url") or "",
            "aliases": volume_data.get("aliases") or "",
            "deck": volume_data.get("deck") or "",
            "description": volume_data.get("description") or "",
            "comicvine_image_icon_url": volume_data.get("comicvine_image_icon_url") or "",
            "comicvine_image_medium_url": volume_data.get("comicvine_image_medium_url") or "",
            "comicvine_image_screen_url": volume_data.get("comicvine_image_screen_url") or "",
            "comicvine_image_screen_large_url": volume_data.get("comicvine_image_screen_large_url") or "",
            "comicvine_image_small_url": volume_data.get("comicvine_image_small_url") or "",
            "comicvine_image_super_url": volume_data.get("comicvine_image_super_url") or "",
            "comicvine_image_thumb_url": volume_data.get("comicvine_image_thumb_url") or "",
            "comicvine_image_tiny_url": volume_data.get("comicvine_image_tiny_url") or "",
            "comicvine_image_original_url": volume_data.get("comicvine_image_original_url") or "",
            "comicvine_image_tags": volume_data.get("comicvine_image_tags") or "",
            "display_image_url": volume_data.get("display_image_url") or "",
            "display_image_source": (
                volume_data.get("display_image_source")
                or ComicVolume.IMAGE_SOURCE_UNKNOWN
            ),
            "first_issue_comicvine_id": volume_data.get("first_issue_comicvine_id"),
            "first_issue_number": volume_data.get("first_issue_number") or "",
            "first_issue_name": volume_data.get("first_issue_name") or "",
            "first_issue_api_url": volume_data.get("first_issue_api_url") or "",
            "last_issue_comicvine_id": volume_data.get("last_issue_comicvine_id"),
            "last_issue_number": volume_data.get("last_issue_number") or "",
            "last_issue_name": volume_data.get("last_issue_name") or "",
            "last_issue_api_url": volume_data.get("last_issue_api_url") or "",
        },
    )

    return volume_object


def update_volume_detail(local_volume, volume_data, remote_people):
    with transaction.atomic():
        local_volume.name = volume_data["name"]
        local_volume.publisher = volume_data["publisher"]
        local_volume.publisher_comicvine_id = volume_data["publisher_comicvine_id"]
        local_volume.publisher_api_detail_url = volume_data["publisher_api_detail_url"]

        local_volume.start_year = volume_data["start_year"]
        local_volume.count_of_issues = volume_data["count_of_issues"]

        local_volume.date_added = volume_data["date_added"]
        local_volume.date_last_updated = volume_data["date_last_updated"]

        local_volume.comicvine_url = volume_data["comicvine_url"]
        local_volume.api_detail_url = volume_data["api_detail_url"]

        local_volume.aliases = volume_data["aliases"]
        local_volume.deck = volume_data["deck"]
        local_volume.description = volume_data["description"]

        local_volume.comicvine_image_icon_url = volume_data["comicvine_image_icon_url"]
        local_volume.comicvine_image_medium_url = volume_data["comicvine_image_medium_url"]
        local_volume.comicvine_image_screen_url = volume_data["comicvine_image_screen_url"]
        local_volume.comicvine_image_screen_large_url = volume_data["comicvine_image_screen_large_url"]
        local_volume.comicvine_image_small_url = volume_data["comicvine_image_small_url"]
        local_volume.comicvine_image_super_url = volume_data["comicvine_image_super_url"]
        local_volume.comicvine_image_thumb_url = volume_data["comicvine_image_thumb_url"]
        local_volume.comicvine_image_tiny_url = volume_data["comicvine_image_tiny_url"]
        local_volume.comicvine_image_original_url = volume_data["comicvine_image_original_url"]
        local_volume.comicvine_image_tags = volume_data["comicvine_image_tags"]

        local_volume.display_image_url = volume_data["display_image_url"]
        local_volume.display_image_source = volume_data["display_image_source"]

        local_volume.first_issue_comicvine_id = volume_data["first_issue_comicvine_id"]
        local_volume.first_issue_number = volume_data["first_issue_number"]
        local_volume.first_issue_name = volume_data["first_issue_name"]
        local_volume.first_issue_api_url = volume_data["first_issue_api_url"]

        local_volume.last_issue_comicvine_id = volume_data["last_issue_comicvine_id"]
        local_volume.last_issue_number = volume_data["last_issue_number"]
        local_volume.last_issue_name = volume_data["last_issue_name"]
        local_volume.last_issue_api_url = volume_data["last_issue_api_url"]

        local_volume.detail_hydration_attempted_at = volume_data["detail_hydration_attempted_at"]
        local_volume.detail_hydrated_at = volume_data["detail_hydrated_at"]

        local_volume.save(
            update_fields=[
                "name",
                "publisher",
                "publisher_comicvine_id",
                "publisher_api_detail_url",
                "start_year",
                "count_of_issues",
                "date_added",
                "date_last_updated",
                "comicvine_url",
                "api_detail_url",
                "aliases",
                "deck",
                "description",
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
                "display_image_url",
                "display_image_source",
                "first_issue_comicvine_id",
                "first_issue_number",
                "first_issue_name",
                "first_issue_api_url",
                "last_issue_comicvine_id",
                "last_issue_number",
                "last_issue_name",
                "last_issue_api_url",
                "detail_hydration_attempted_at",
                "detail_hydrated_at",
            ]
        )

        return sync_volume_people(
            volume=local_volume,
            remote_people=remote_people,
        )


def update_issue_detail(local_issue, target_volume, issue_data, remote_people):
    with transaction.atomic():
        local_issue.volume = target_volume
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


def sync_volume_people(volume, remote_people):
    synced_person_ids = []
    synced_count = 0

    for person_data in remote_people:
        person_comicvine_id = to_int(person_data.get("id"))

        if not person_comicvine_id:
            continue

        person = get_or_update_person(person_data)
        synced_person_ids.append(person.id)

        ComicVolumePersonCredit.objects.update_or_create(
            volume=volume,
            person=person,
            defaults={
                "credit_count": to_int(person_data.get("count")),
                "api_detail_url": person_data.get("api_detail_url") or "",
                "comicvine_url": person_data.get("site_detail_url") or "",
            },
        )

        synced_count += 1

    stale_credits = ComicVolumePersonCredit.objects.filter(volume=volume)

    if synced_person_ids:
        stale_credits = stale_credits.exclude(person_id__in=synced_person_ids)

    stale_credits.delete()

    return synced_count


def sync_issue_person_credits(issue, remote_people):
    synced_credit_ids = []
    synced_count = 0

    for person_data in remote_people:
        person_comicvine_id = to_int(person_data.get("id"))

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
    person_comicvine_id = to_int(person_data.get("id"))

    if not person_comicvine_id:
        return None

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


def mark_volume_hydration_attempted(local_volume, attempted_at):
    local_volume.detail_hydration_attempted_at = attempted_at
    local_volume.save(update_fields=["detail_hydration_attempted_at"])


def mark_issue_hydration_attempted(local_issue, attempted_at):
    local_issue.detail_hydration_attempted_at = attempted_at
    local_issue.save(update_fields=["detail_hydration_attempted_at"])


def refresh_volume_latest_issue_store_date(volume_id):
    volume = ComicVolume.objects.filter(comicvine_id=volume_id).first()

    if not volume:
        return

    latest_store_date = ComicIssue.objects.filter(
        volume=volume,
        store_date__isnull=False,
    ).aggregate(latest_store_date=Max("store_date"))["latest_store_date"]

    if volume.latest_local_issue_store_date != latest_store_date:
        volume.latest_local_issue_store_date = latest_store_date
        volume.save(update_fields=["latest_local_issue_store_date"])


def build_volume_data_from_local(local_volume):
    return {
        "comicvine_id": local_volume.comicvine_id,
        "name": local_volume.name,
        "publisher": local_volume.publisher,
        "publisher_comicvine_id": local_volume.publisher_comicvine_id,
        "publisher_api_detail_url": local_volume.publisher_api_detail_url,
        "start_year": local_volume.start_year,
        "count_of_issues": local_volume.count_of_issues,
        "date_added": local_volume.date_added,
        "date_last_updated": local_volume.date_last_updated,
        "comicvine_url": local_volume.comicvine_url,
        "api_detail_url": local_volume.api_detail_url,
        "aliases": local_volume.aliases,
        "deck": local_volume.deck,
        "description": local_volume.description,
        "comicvine_image_icon_url": local_volume.comicvine_image_icon_url,
        "comicvine_image_medium_url": local_volume.comicvine_image_medium_url,
        "comicvine_image_screen_url": local_volume.comicvine_image_screen_url,
        "comicvine_image_screen_large_url": local_volume.comicvine_image_screen_large_url,
        "comicvine_image_small_url": local_volume.comicvine_image_small_url,
        "comicvine_image_super_url": local_volume.comicvine_image_super_url,
        "comicvine_image_thumb_url": local_volume.comicvine_image_thumb_url,
        "comicvine_image_tiny_url": local_volume.comicvine_image_tiny_url,
        "comicvine_image_original_url": local_volume.comicvine_image_original_url,
        "comicvine_image_tags": local_volume.comicvine_image_tags,
        "display_image_url": local_volume.display_image_url,
        "display_image_source": local_volume.display_image_source,
        "first_issue_comicvine_id": local_volume.first_issue_comicvine_id,
        "first_issue_number": local_volume.first_issue_number,
        "first_issue_name": local_volume.first_issue_name,
        "first_issue_api_url": local_volume.first_issue_api_url,
        "last_issue_comicvine_id": local_volume.last_issue_comicvine_id,
        "last_issue_number": local_volume.last_issue_number,
        "last_issue_name": local_volume.last_issue_name,
        "last_issue_api_url": local_volume.last_issue_api_url,
    }


def build_volume_data_from_remote(remote_volume, fallback_volume_id):
    publisher = remote_volume.get("publisher") or {}
    image = remote_volume.get("image") or {}
    first_issue = remote_volume.get("first_issue") or {}
    last_issue = remote_volume.get("last_issue") or {}

    volume_id = to_int(remote_volume.get("id")) or fallback_volume_id
    preferred_image_url = get_preferred_image_url(image)

    return {
        "comicvine_id": volume_id,
        "name": remote_volume.get("name") or f"Comic Vine Volume {volume_id}",
        "publisher": publisher.get("name") or "",
        "publisher_comicvine_id": to_int(publisher.get("id")),
        "publisher_api_detail_url": publisher.get("api_detail_url") or "",
        "start_year": remote_volume.get("start_year") or "",
        "count_of_issues": to_int(remote_volume.get("count_of_issues")),
        "date_added": parse_comicvine_datetime(remote_volume.get("date_added")),
        "date_last_updated": parse_comicvine_datetime(remote_volume.get("date_last_updated")),
        "comicvine_url": remote_volume.get("site_detail_url") or "",
        "api_detail_url": remote_volume.get("api_detail_url") or "",
        "aliases": remote_volume.get("aliases") or "",
        "deck": remote_volume.get("deck") or "",
        "description": remote_volume.get("description") or "",
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
        "display_image_url": preferred_image_url,
        "display_image_source": (
            ComicVolume.IMAGE_SOURCE_COMICVINE_VOLUME
            if preferred_image_url
            else ComicVolume.IMAGE_SOURCE_UNKNOWN
        ),
        "first_issue_comicvine_id": to_int(first_issue.get("id")),
        "first_issue_number": first_issue.get("issue_number") or "",
        "first_issue_name": first_issue.get("name") or "",
        "first_issue_api_url": first_issue.get("api_detail_url") or "",
        "last_issue_comicvine_id": to_int(last_issue.get("id")),
        "last_issue_number": last_issue.get("issue_number") or "",
        "last_issue_name": last_issue.get("name") or "",
        "last_issue_api_url": last_issue.get("api_detail_url") or "",
    }


def build_volume_hydration_data(local_volume, remote_volume, attempted_at):
    publisher = remote_volume.get("publisher") or {}
    image = remote_volume.get("image") or {}
    first_issue = remote_volume.get("first_issue") or {}
    last_issue = remote_volume.get("last_issue") or {}

    display_image_url = local_volume.display_image_url
    display_image_source = local_volume.display_image_source

    preferred_image_url = get_preferred_image_url(image)

    if (
        display_image_source != ComicVolume.IMAGE_SOURCE_MANUAL
        and not display_image_url
        and preferred_image_url
    ):
        display_image_url = preferred_image_url
        display_image_source = ComicVolume.IMAGE_SOURCE_COMICVINE_VOLUME

    return {
        "comicvine_id": remote_volume.get("id") or local_volume.comicvine_id,
        "name": remote_volume.get("name") or local_volume.name,
        "publisher": publisher.get("name") or local_volume.publisher,
        "publisher_comicvine_id": to_int(publisher.get("id")) or local_volume.publisher_comicvine_id,
        "publisher_api_detail_url": publisher.get("api_detail_url") or local_volume.publisher_api_detail_url,
        "start_year": remote_volume.get("start_year") or local_volume.start_year,
        "count_of_issues": to_int(remote_volume.get("count_of_issues")),
        "date_added": parse_comicvine_datetime(remote_volume.get("date_added")) or local_volume.date_added,
        "date_last_updated": parse_comicvine_datetime(remote_volume.get("date_last_updated")) or local_volume.date_last_updated,
        "comicvine_url": remote_volume.get("site_detail_url") or local_volume.comicvine_url,
        "api_detail_url": remote_volume.get("api_detail_url") or local_volume.api_detail_url,
        "aliases": remote_volume.get("aliases") or "",
        "deck": remote_volume.get("deck") or "",
        "description": remote_volume.get("description") or "",
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
        "display_image_url": display_image_url,
        "display_image_source": display_image_source,
        "first_issue_comicvine_id": to_int(first_issue.get("id")),
        "first_issue_number": first_issue.get("issue_number") or "",
        "first_issue_name": first_issue.get("name") or "",
        "first_issue_api_url": first_issue.get("api_detail_url") or "",
        "last_issue_comicvine_id": to_int(last_issue.get("id")),
        "last_issue_number": last_issue.get("issue_number") or "",
        "last_issue_name": last_issue.get("name") or "",
        "last_issue_api_url": last_issue.get("api_detail_url") or "",
        "detail_hydration_attempted_at": attempted_at,
        "detail_hydrated_at": attempted_at,
    }


def build_issue_hydration_data(local_issue, remote_issue, attempted_at):
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


def build_minimal_volume_data_from_embedded_volume(embedded_volume, fallback_volume_id):
    volume_id = get_volume_id(embedded_volume) or fallback_volume_id

    return {
        "comicvine_id": volume_id,
        "name": embedded_volume.get("name") or f"Comic Vine Volume {volume_id}",
        "publisher": "",
        "publisher_comicvine_id": None,
        "publisher_api_detail_url": "",
        "start_year": "",
        "count_of_issues": None,
        "date_added": None,
        "date_last_updated": None,
        "comicvine_url": embedded_volume.get("site_detail_url") or "",
        "api_detail_url": embedded_volume.get("api_detail_url") or "",
        "aliases": "",
        "deck": "",
        "description": "",
        "comicvine_image_icon_url": "",
        "comicvine_image_medium_url": "",
        "comicvine_image_screen_url": "",
        "comicvine_image_screen_large_url": "",
        "comicvine_image_small_url": "",
        "comicvine_image_super_url": "",
        "comicvine_image_thumb_url": "",
        "comicvine_image_tiny_url": "",
        "comicvine_image_original_url": "",
        "comicvine_image_tags": "",
        "display_image_url": "",
        "display_image_source": ComicVolume.IMAGE_SOURCE_UNKNOWN,
        "first_issue_comicvine_id": None,
        "first_issue_number": "",
        "first_issue_name": "",
        "first_issue_api_url": "",
        "last_issue_comicvine_id": None,
        "last_issue_number": "",
        "last_issue_name": "",
        "last_issue_api_url": "",
    }


def get_volume_id(volume):
    raw_volume_id = volume.get("id")

    if raw_volume_id:
        parsed_id = to_int(raw_volume_id)

        if parsed_id:
            return parsed_id

    api_detail_url = volume.get("api_detail_url") or ""
    match = re.search(r"4050-(\d+)", api_detail_url)

    if match:
        return int(match.group(1))

    return None


def get_preferred_image_url(image):
    return (
        image.get("small_url")
        or image.get("medium_url")
        or image.get("screen_url")
        or image.get("original_url")
        or ""
    )


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


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def count_valid_people(remote_people):
    return sum(
        1
        for person_data in remote_people
        if to_int(person_data.get("id"))
    )


def count_valid_person_credits(remote_people):
    return sum(
        1
        for person_data in remote_people
        if to_int(person_data.get("id"))
    )


def print_volume_hydration_preview(command, local_volume, volume_data, remote_people):
    command.stdout.write("")
    command.stdout.write(f"Volume hydrate: {volume_data['name']}")
    command.stdout.write(f"Comic Vine Volume ID: {local_volume.comicvine_id}")
    command.stdout.write(f"Publisher: {volume_data['publisher']}")
    command.stdout.write(f"Date Last Updated on Comic Vine: {volume_data['date_last_updated'] or ''}")
    command.stdout.write(f"Volume people returned: {count_valid_people(remote_people)}")


def print_issue_hydration_preview(command, local_issue, issue_data, remote_people):
    command.stdout.write("")
    command.stdout.write(f"Issue hydrate: {local_issue}")
    command.stdout.write(f"Comic Vine Issue ID: {local_issue.comicvine_id}")
    command.stdout.write(f"Issue Title: {issue_data['issue_title']}")
    command.stdout.write(f"Date Last Updated on Comic Vine: {issue_data['date_last_updated'] or ''}")
    command.stdout.write(f"Person credits returned: {count_valid_person_credits(remote_people)}")


def print_missing_issue_detail_preview(command, local_issue):
    command.stdout.write("")
    command.stdout.write(f"Issue hydration attempted but no usable detail was returned: {local_issue}")
    command.stdout.write(f"Comic Vine Issue ID: {local_issue.comicvine_id}")


def print_summary(command, result):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Targeted volume issue import and hydration summary:"))
    command.stdout.write(f"Volume: {result.volume_name}")
    command.stdout.write(f"Comic Vine Volume ID: {result.volume_id}")
    command.stdout.write(f"Volume created locally: {result.volume_created}")
    command.stdout.write(f"Comic Vine issue filter used: {result.selected_filter}")

    command.stdout.write("")
    command.stdout.write("Issue import:")
    command.stdout.write(f"Issue pages fetched: {result.issue_pages_fetched}")
    command.stdout.write(f"Total remote issues for this volume: {result.total_remote_issues}")
    command.stdout.write(f"Issues checked: {result.issues_checked}")
    command.stdout.write(f"Issues created: {result.issues_created}")
    command.stdout.write(f"Existing issues skipped: {result.existing_issues_skipped}")
    command.stdout.write(
        f"Existing issues linked to this volume: {result.existing_issues_linked_to_volume}"
    )
    command.stdout.write(f"Missing-data issues skipped: {result.missing_data_skipped}")

    command.stdout.write("")
    command.stdout.write("Targeted hydration:")
    command.stdout.write(f"Volume hydrated: {result.volume_hydrated}")
    command.stdout.write(
        f"Volume marked attempted without usable detail: {result.volume_marked_attempted_without_detail}"
    )
    command.stdout.write(f"Volume people credits synced: {result.volume_people_synced}")
    command.stdout.write(f"Local issues found for targeted hydration: {result.target_issues_found_for_hydration}")
    command.stdout.write(f"Issues hydrated: {result.issues_hydrated}")
    command.stdout.write(
        f"Issues marked attempted without usable detail: {result.issues_marked_attempted_without_detail}"
    )
    command.stdout.write(f"Issue person credits synced: {result.issue_person_credits_synced}")

    command.stdout.write("")
    command.stdout.write(f"Comic Vine API requests made: {result.api_requests_made}")