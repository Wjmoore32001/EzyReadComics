import os
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q
from django.utils import timezone

from comics.models import ComicPerson, ComicVolume, ComicVolumePersonCredit


VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"
USER_AGENT = "EzyReadComics volume detail hydrator"


@dataclass
class HydrationResult:
    volumes_needing_hydration_found: int = 0
    volumes_checked: int = 0
    volumes_hydrated: int = 0
    volumes_marked_attempted_without_detail: int = 0
    volume_people_synced: int = 0
    api_requests_made: int = 0


class Command(BaseCommand):
    help = "Hydrate local ComicVolume rows from Comic Vine volume detail records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--volume-limit",
            type=int,
            default=100,
            help="Maximum number of local volumes to hydrate in one run. Defaults to 100.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=0.25,
            help="Seconds to pause after each Comic Vine volume request. Defaults to 0.25.",
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

        volume_limit = options["volume_limit"]
        request_delay = options["request_delay"]
        dry_run = options["dry_run"]

        validate_options(
            volume_limit=volume_limit,
            request_delay=request_delay,
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine volume detail hydrator"))
        self.stdout.write("Hydrates local volumes using the Comic Vine volume detail endpoint.")
        self.stdout.write("Also syncs volume-level people credits when Comic Vine returns them.")
        self.stdout.write("Volumes are selected by detail_hydration_attempted_at, not by empty optional fields.")
        self.stdout.write(f"Volume limit this run: {volume_limit}")
        self.stdout.write(f"Request delay: {request_delay}")

        result = hydrate_volumes(
            command=self,
            api_key=api_key,
            volume_limit=volume_limit,
            request_delay=request_delay,
            dry_run=dry_run,
        )

        print_summary(self, result)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def validate_options(volume_limit, request_delay):
    if volume_limit < 1:
        raise CommandError("volume-limit must be at least 1.")

    if volume_limit > 100:
        raise CommandError("volume-limit cannot be above 100 for now.")

    if request_delay < 0:
        raise CommandError("request-delay cannot be negative.")


def hydrate_volumes(command, api_key, volume_limit, request_delay, dry_run):
    volumes_queryset = get_volumes_needing_hydration_queryset()
    volumes_needing_hydration_found = volumes_queryset.count()
    volumes_to_check = list(volumes_queryset[:volume_limit])

    result = HydrationResult(
        volumes_needing_hydration_found=volumes_needing_hydration_found,
    )

    command.stdout.write(f"Volumes needing hydration found: {volumes_needing_hydration_found}")

    if not volumes_to_check:
        command.stdout.write("")
        command.stdout.write(command.style.SUCCESS("No volumes need hydration."))
        command.stdout.write("No Comic Vine API request was needed.")
        return result

    for local_volume in volumes_to_check:
        result.volumes_checked += 1
        attempted_at = timezone.now()

        data = fetch_volume_detail(
            api_key=api_key,
            volume_id=local_volume.comicvine_id,
        )
        result.api_requests_made += 1

        remote_volume = data.get("results") or {}

        if not remote_volume or not remote_volume.get("id"):
            print_missing_detail_preview(
                command=command,
                local_volume=local_volume,
            )

            if not dry_run:
                mark_volume_hydration_attempted(
                    local_volume=local_volume,
                    attempted_at=attempted_at,
                )

            result.volumes_marked_attempted_without_detail += 1

            if request_delay > 0:
                time.sleep(request_delay)

            continue

        volume_data = build_volume_data(
            local_volume=local_volume,
            remote_volume=remote_volume,
            attempted_at=attempted_at,
        )

        if not has_useful_volume_data(volume_data):
            print_missing_detail_preview(
                command=command,
                local_volume=local_volume,
            )

            if not dry_run:
                mark_volume_hydration_attempted(
                    local_volume=local_volume,
                    attempted_at=attempted_at,
                )

            result.volumes_marked_attempted_without_detail += 1

            if request_delay > 0:
                time.sleep(request_delay)

            continue

        remote_people = remote_volume.get("people") or []

        print_volume_preview(
            command=command,
            local_volume=local_volume,
            volume_data=volume_data,
            remote_people=remote_people,
        )

        if not dry_run:
            people_synced = update_volume(
                local_volume=local_volume,
                volume_data=volume_data,
                remote_people=remote_people,
            )
            result.volume_people_synced += people_synced
        else:
            result.volume_people_synced += count_valid_people(remote_people)

        result.volumes_hydrated += 1

        if request_delay > 0:
            time.sleep(request_delay)

    return result


def get_volumes_needing_hydration_queryset():
    return (
        ComicVolume.objects.filter(comicvine_id__isnull=False)
        .filter(
            Q(detail_hydration_attempted_at__isnull=True)
            | Q(date_last_updated__gt=F("detail_hydration_attempted_at"))
        )
        .order_by(
            F("detail_hydration_attempted_at").asc(nulls_first=True),
            "id",
        )
    )


def fetch_volume_detail(api_key, volume_id):
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

    return fetch_comicvine_json(url, params)


def build_volume_data(local_volume, remote_volume, attempted_at):
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
        "publisher_comicvine_id": to_optional_int(publisher.get("id")) or local_volume.publisher_comicvine_id,
        "publisher_api_detail_url": publisher.get("api_detail_url") or local_volume.publisher_api_detail_url,
        "start_year": remote_volume.get("start_year") or local_volume.start_year,
        "count_of_issues": to_optional_int(remote_volume.get("count_of_issues")),
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
        "first_issue_comicvine_id": to_optional_int(first_issue.get("id")),
        "first_issue_number": first_issue.get("issue_number") or "",
        "first_issue_name": first_issue.get("name") or "",
        "first_issue_api_url": first_issue.get("api_detail_url") or "",
        "last_issue_comicvine_id": to_optional_int(last_issue.get("id")),
        "last_issue_number": last_issue.get("issue_number") or "",
        "last_issue_name": last_issue.get("name") or "",
        "last_issue_api_url": last_issue.get("api_detail_url") or "",
        "detail_hydration_attempted_at": attempted_at,
        "detail_hydrated_at": attempted_at,
    }


def has_useful_volume_data(volume_data):
    return any(
        [
            volume_data["name"],
            volume_data["publisher"],
            volume_data["date_added"],
            volume_data["date_last_updated"],
            volume_data["comicvine_url"],
            volume_data["api_detail_url"],
        ]
    )


def update_volume(local_volume, volume_data, remote_people):
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


def mark_volume_hydration_attempted(local_volume, attempted_at):
    local_volume.detail_hydration_attempted_at = attempted_at
    local_volume.save(update_fields=["detail_hydration_attempted_at"])


def sync_volume_people(volume, remote_people):
    synced_person_ids = []
    synced_count = 0

    for person_data in remote_people:
        person_comicvine_id = to_optional_int(person_data.get("id"))

        if not person_comicvine_id:
            continue

        person = get_or_update_person(person_data)
        synced_person_ids.append(person.id)

        ComicVolumePersonCredit.objects.update_or_create(
            volume=volume,
            person=person,
            defaults={
                "credit_count": to_optional_int(person_data.get("count")),
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


def count_valid_people(remote_people):
    return sum(
        1
        for person_data in remote_people
        if to_optional_int(person_data.get("id"))
    )


def get_preferred_image_url(image):
    return (
        image.get("small_url")
        or image.get("medium_url")
        or image.get("screen_url")
        or image.get("original_url")
        or ""
    )


def fetch_comicvine_json(url, params):
    headers = {
        "User-Agent": USER_AGENT,
    }

    response = requests.get(url, params=params, headers=headers, timeout=30)

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


def print_volume_preview(command, local_volume, volume_data, remote_people):
    command.stdout.write("")
    command.stdout.write(f"Volume hydrate: {volume_data['name']}")
    command.stdout.write(f"Comic Vine Volume ID: {local_volume.comicvine_id}")
    command.stdout.write(f"Publisher: {volume_data['publisher']}")
    command.stdout.write(f"Date Last Updated on Comic Vine: {volume_data['date_last_updated'] or ''}")
    command.stdout.write(f"Volume people returned: {count_valid_people(remote_people)}")


def print_missing_detail_preview(command, local_volume):
    command.stdout.write("")
    command.stdout.write(f"Volume hydration attempted but no usable detail was returned: {local_volume}")
    command.stdout.write(f"Comic Vine Volume ID: {local_volume.comicvine_id}")


def print_summary(command, result):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Volume hydration summary:"))
    command.stdout.write(f"Volumes needing hydration found: {result.volumes_needing_hydration_found}")
    command.stdout.write(f"Volumes checked this run: {result.volumes_checked}")
    command.stdout.write(f"Volumes hydrated this run: {result.volumes_hydrated}")
    command.stdout.write(f"Volumes marked attempted without usable detail: {result.volumes_marked_attempted_without_detail}")
    command.stdout.write(f"Volume people credits synced: {result.volume_people_synced}")
    command.stdout.write(f"Comic Vine API requests made: {result.api_requests_made}")