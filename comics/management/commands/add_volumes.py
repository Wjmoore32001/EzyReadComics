import os
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from comics.models import ComicVolume


VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"
USER_AGENT = "EzyReadComics volume detail filler"


@dataclass
class HydrationResult:
    incomplete_volumes_found: int = 0
    volumes_checked: int = 0
    volumes_updated: int = 0
    volumes_skipped_missing_data: int = 0
    api_requests_made: int = 0


class Command(BaseCommand):
    help = "Fill missing local ComicVolume details from Comic Vine volume records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--volume-limit",
            type=int,
            default=100,
            help="Maximum number of incomplete local volumes to check in one run. Defaults to 100.",
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
        self.stdout.write(self.style.SUCCESS("Comic Vine volume detail filler"))
        self.stdout.write(f"Volume limit this run: {volume_limit}")
        self.stdout.write(f"Request delay: {request_delay}")

        result = hydrate_missing_volumes(
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


def hydrate_missing_volumes(command, api_key, volume_limit, request_delay, dry_run):
    incomplete_volumes_queryset = get_incomplete_volumes_queryset()
    incomplete_volumes_found = incomplete_volumes_queryset.count()
    volumes_to_check = list(incomplete_volumes_queryset[:volume_limit])

    result = HydrationResult(
        incomplete_volumes_found=incomplete_volumes_found,
    )

    command.stdout.write(f"Incomplete local volumes found: {incomplete_volumes_found}")

    if not volumes_to_check:
        command.stdout.write("")
        command.stdout.write(command.style.SUCCESS("No incomplete local volumes found."))
        command.stdout.write("No Comic Vine API request was needed.")
        return result

    for local_volume in volumes_to_check:
        result.volumes_checked += 1

        data = fetch_volume_detail(
            api_key=api_key,
            volume_id=local_volume.comicvine_id,
        )
        result.api_requests_made += 1

        remote_volume = data.get("results") or {}

        if not remote_volume:
            result.volumes_skipped_missing_data += 1
            continue

        volume_data = build_volume_data(
            local_volume=local_volume,
            remote_volume=remote_volume,
        )

        if not has_useful_volume_data(volume_data):
            result.volumes_skipped_missing_data += 1
            continue

        print_volume_preview(
            command=command,
            local_volume=local_volume,
            volume_data=volume_data,
        )

        if not dry_run:
            update_volume(
                local_volume=local_volume,
                volume_data=volume_data,
            )

        result.volumes_updated += 1

        if request_delay > 0:
            time.sleep(request_delay)

    return result


def get_incomplete_volumes_queryset():
    return (
        ComicVolume.objects.filter(
            Q(name="")
            | Q(date_added__isnull=True)
            | Q(date_last_updated__isnull=True)
            | Q(comicvine_url="")
        )
        .order_by("id")
    )


def fetch_volume_detail(api_key, volume_id):
    url = VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_id)

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": ",".join(
            [
                "id",
                "name",
                "publisher",
                "date_added",
                "date_last_updated",
                "site_detail_url",
            ]
        ),
    }

    return fetch_comicvine_json(url, params)


def build_volume_data(local_volume, remote_volume):
    publisher = remote_volume.get("publisher") or {}

    return {
        "comicvine_id": remote_volume.get("id") or local_volume.comicvine_id,
        "name": remote_volume.get("name") or local_volume.name,
        "publisher": publisher.get("name") or local_volume.publisher,
        "date_added": parse_comicvine_datetime(remote_volume.get("date_added")) or local_volume.date_added,
        "date_last_updated": parse_comicvine_datetime(remote_volume.get("date_last_updated")) or local_volume.date_last_updated,
        "comicvine_url": remote_volume.get("site_detail_url") or local_volume.comicvine_url,
    }


def has_useful_volume_data(volume_data):
    return any(
        [
            volume_data["name"],
            volume_data["publisher"],
            volume_data["date_added"],
            volume_data["date_last_updated"],
            volume_data["comicvine_url"],
        ]
    )


def update_volume(local_volume, volume_data):
    local_volume.name = volume_data["name"]
    local_volume.publisher = volume_data["publisher"]
    local_volume.date_added = volume_data["date_added"]
    local_volume.date_last_updated = volume_data["date_last_updated"]
    local_volume.comicvine_url = volume_data["comicvine_url"]

    local_volume.save(
        update_fields=[
            "name",
            "publisher",
            "date_added",
            "date_last_updated",
            "comicvine_url",
        ]
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


def print_volume_preview(command, local_volume, volume_data):
    command.stdout.write("")
    command.stdout.write(f"Volume fill: {volume_data['name']}")
    command.stdout.write(f"Comic Vine Volume ID: {local_volume.comicvine_id}")
    command.stdout.write(f"Publisher: {volume_data['publisher']}")
    command.stdout.write(f"Date Last Updated on Comic Vine: {volume_data['date_last_updated'] or ''}")


def print_summary(command, result):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Volume fill summary:"))
    command.stdout.write(f"Incomplete local volumes found: {result.incomplete_volumes_found}")
    command.stdout.write(f"Volumes checked this run: {result.volumes_checked}")
    command.stdout.write(f"Volumes updated this run: {result.volumes_updated}")
    command.stdout.write(f"Volumes skipped because Comic Vine returned missing data: {result.volumes_skipped_missing_data}")
    command.stdout.write(f"Comic Vine API requests made: {result.api_requests_made}")