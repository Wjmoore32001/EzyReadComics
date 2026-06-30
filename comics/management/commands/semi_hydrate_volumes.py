import os
import time
from dataclasses import dataclass

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from comics.models import ComicVolume


VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
USER_AGENT = "EzyReadComics volume semi-hydrator"


@dataclass
class SemiHydrationResult:
    volumes_missing_basic_data_found: int = 0
    volumes_selected_this_run: int = 0
    volume_batches_requested: int = 0
    volumes_checked: int = 0
    volumes_returned_by_comicvine: int = 0
    volumes_updated: int = 0
    volumes_not_returned_by_comicvine: int = 0
    volumes_without_usable_basic_data: int = 0
    unexpected_volumes_returned: int = 0
    publishers_added: int = 0
    start_years_added: int = 0
    api_requests_made: int = 0


class Command(BaseCommand):
    help = (
        "Lightly fills ComicVolume publisher and start_year from Comic Vine "
        "using batched /volumes/ requests, without touching normal hydration tracking or credits."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--volume-limit",
            type=int,
            default=None,
            help=(
                "Maximum number of matching local volumes to check in one run. "
                "Defaults to all matching volumes."
            ),
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help=(
                "Number of volume IDs to request from Comic Vine per API call. "
                "Defaults to 100."
            ),
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=0,
            help="Seconds to pause after each Comic Vine batch request. Defaults to 0.",
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
        batch_size = options["batch_size"]
        request_delay = options["request_delay"]
        dry_run = options["dry_run"]

        validate_options(
            volume_limit=volume_limit,
            batch_size=batch_size,
            request_delay=request_delay,
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine volume semi-hydrator"))
        self.stdout.write(
            "Fills only publisher and start_year for volumes missing both fields."
        )
        self.stdout.write(
            "Uses batched /volumes/ requests with pipe-separated Comic Vine volume IDs."
        )
        self.stdout.write(
            "Does not touch hydration tracking, credits, images, descriptions, scans, or sync state."
        )
        self.stdout.write("Selection rule: publisher is empty AND start_year is empty.")

        if volume_limit is None:
            self.stdout.write("Volume limit this run: all matching volumes")
        else:
            self.stdout.write(f"Volume limit this run: {volume_limit}")

        self.stdout.write(f"Batch size: {batch_size}")
        self.stdout.write(f"Request delay: {request_delay}")

        with requests.Session() as session:
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                }
            )

            result = semi_hydrate_volumes(
                command=self,
                session=session,
                api_key=api_key,
                volume_limit=volume_limit,
                batch_size=batch_size,
                request_delay=request_delay,
                dry_run=dry_run,
            )

        print_summary(self, result)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def validate_options(volume_limit, batch_size, request_delay):
    if volume_limit is not None and volume_limit < 1:
        raise CommandError("volume-limit must be at least 1 when provided.")

    if batch_size < 1:
        raise CommandError("batch-size must be at least 1.")

    if batch_size > 100:
        raise CommandError("batch-size cannot be above 100 for Comic Vine list requests.")

    if request_delay < 0:
        raise CommandError("request-delay cannot be negative.")


def semi_hydrate_volumes(
    command,
    session,
    api_key,
    volume_limit,
    batch_size,
    request_delay,
    dry_run,
):
    volumes_queryset = get_volumes_missing_basic_data_queryset()
    volumes_missing_basic_data_found = volumes_queryset.count()

    if volume_limit is not None:
        volumes_to_check = list(volumes_queryset[:volume_limit])
    else:
        volumes_to_check = list(volumes_queryset)

    result = SemiHydrationResult(
        volumes_missing_basic_data_found=volumes_missing_basic_data_found,
        volumes_selected_this_run=len(volumes_to_check),
    )

    command.stdout.write("")
    command.stdout.write(
        f"Volumes missing both publisher and start_year found: "
        f"{result.volumes_missing_basic_data_found}"
    )
    command.stdout.write(f"Volumes selected this run: {result.volumes_selected_this_run}")

    if not volumes_to_check:
        command.stdout.write("")
        command.stdout.write(command.style.SUCCESS("No volumes need semi-hydration."))
        command.stdout.write("No Comic Vine API request was needed.")
        return result

    batches = chunk_list(volumes_to_check, batch_size)

    for batch_number, local_volume_batch in enumerate(batches, start=1):
        result.volume_batches_requested += 1

        command.stdout.write("")
        command.stdout.write(
            command.style.SUCCESS(
                f"Volume semi-hydration batch {batch_number}/{len(batches)}"
            )
        )
        command.stdout.write(f"Volumes in this batch: {len(local_volume_batch)}")

        local_volumes_by_comicvine_id = {
            local_volume.comicvine_id: local_volume
            for local_volume in local_volume_batch
        }

        requested_volume_ids = list(local_volumes_by_comicvine_id.keys())

        data = fetch_volume_batch(
            session=session,
            api_key=api_key,
            volume_ids=requested_volume_ids,
        )

        result.api_requests_made += 1

        remote_volumes = data.get("results") or []
        remote_volumes_by_comicvine_id = {
            remote_volume.get("id"): remote_volume
            for remote_volume in remote_volumes
            if remote_volume.get("id")
        }

        result.volumes_returned_by_comicvine += len(remote_volumes_by_comicvine_id)

        unexpected_ids = sorted(
            set(remote_volumes_by_comicvine_id.keys()) - set(requested_volume_ids)
        )

        if unexpected_ids:
            result.unexpected_volumes_returned += len(unexpected_ids)
            command.stdout.write(
                command.style.WARNING(
                    f"Unexpected Comic Vine volume IDs returned: {unexpected_ids[:20]}"
                )
            )

        for local_volume in local_volume_batch:
            result.volumes_checked += 1

            remote_volume = remote_volumes_by_comicvine_id.get(local_volume.comicvine_id)

            if not remote_volume:
                result.volumes_not_returned_by_comicvine += 1
                continue

            basic_data = build_basic_volume_data(remote_volume)
            update_fields = get_fields_that_would_update(local_volume, basic_data)

            if not update_fields:
                result.volumes_without_usable_basic_data += 1
                continue

            if not dry_run:
                saved_update_fields = update_volume_basic_data(
                    volume_id=local_volume.id,
                    basic_data=basic_data,
                )
            else:
                saved_update_fields = update_fields

            if saved_update_fields:
                result.volumes_updated += 1

                if "publisher" in saved_update_fields:
                    result.publishers_added += 1

                if "start_year" in saved_update_fields:
                    result.start_years_added += 1

        command.stdout.write(
            f"Progress: checked {result.volumes_checked}/{result.volumes_selected_this_run}"
        )
        command.stdout.write(f"Updated so far: {result.volumes_updated}")
        command.stdout.write(f"Comic Vine API requests made so far: {result.api_requests_made}")

        sleep_if_needed(request_delay)

    return result


def get_volumes_missing_basic_data_queryset():
    return (
        ComicVolume.objects.filter(
            publisher="",
            start_year="",
        )
        .only(
            "id",
            "comicvine_id",
            "name",
            "publisher",
            "publisher_comicvine_id",
            "publisher_api_detail_url",
            "start_year",
        )
        .order_by("id")
    )


def fetch_volume_batch(session, api_key, volume_ids):
    params = {
        "api_key": api_key,
        "format": "json",
        "limit": 100,
        "offset": 0,
        "filter": "id:" + "|".join(str(volume_id) for volume_id in volume_ids),
        "field_list": ",".join(
            [
                "id",
                "name",
                "publisher",
                "start_year",
            ]
        ),
    }

    return fetch_comicvine_json(session, VOLUMES_URL, params)


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


def build_basic_volume_data(remote_volume):
    publisher = remote_volume.get("publisher") or {}

    return {
        "publisher": clean_text(publisher.get("name")),
        "publisher_comicvine_id": to_optional_int(publisher.get("id")),
        "publisher_api_detail_url": clean_text(publisher.get("api_detail_url")),
        "start_year": clean_text(remote_volume.get("start_year")),
    }


def get_fields_that_would_update(local_volume, basic_data):
    fields_to_update = []

    if not local_volume.publisher and basic_data["publisher"]:
        fields_to_update.append("publisher")

        if basic_data["publisher_comicvine_id"] is not None:
            fields_to_update.append("publisher_comicvine_id")

        if basic_data["publisher_api_detail_url"]:
            fields_to_update.append("publisher_api_detail_url")

    if not local_volume.start_year and basic_data["start_year"]:
        fields_to_update.append("start_year")

    return fields_to_update


def update_volume_basic_data(volume_id, basic_data):
    with transaction.atomic():
        local_volume = ComicVolume.objects.select_for_update().get(id=volume_id)
        fields_to_update = get_fields_that_would_update(local_volume, basic_data)

        if not fields_to_update:
            return []

        if "publisher" in fields_to_update:
            local_volume.publisher = basic_data["publisher"]

        if "publisher_comicvine_id" in fields_to_update:
            local_volume.publisher_comicvine_id = basic_data["publisher_comicvine_id"]

        if "publisher_api_detail_url" in fields_to_update:
            local_volume.publisher_api_detail_url = basic_data["publisher_api_detail_url"]

        if "start_year" in fields_to_update:
            local_volume.start_year = basic_data["start_year"]

        local_volume.save(update_fields=fields_to_update)

    return fields_to_update


def chunk_list(values, chunk_size):
    return [
        values[index:index + chunk_size]
        for index in range(0, len(values), chunk_size)
    ]


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def to_optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sleep_if_needed(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)


def print_summary(command, result):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Volume semi-hydration summary:"))
    command.stdout.write(
        f"Volumes missing both publisher and start_year found: "
        f"{result.volumes_missing_basic_data_found}"
    )
    command.stdout.write(f"Volumes selected this run: {result.volumes_selected_this_run}")
    command.stdout.write(f"Volume batches requested: {result.volume_batches_requested}")
    command.stdout.write(f"Volumes checked this run: {result.volumes_checked}")
    command.stdout.write(
        f"Volumes returned by Comic Vine: {result.volumes_returned_by_comicvine}"
    )
    command.stdout.write(f"Volumes updated this run: {result.volumes_updated}")
    command.stdout.write(f"Publishers added: {result.publishers_added}")
    command.stdout.write(f"Start years added: {result.start_years_added}")
    command.stdout.write(
        f"Volumes not returned by Comic Vine: {result.volumes_not_returned_by_comicvine}"
    )
    command.stdout.write(
        f"Volumes checked but no publisher/start_year was available: "
        f"{result.volumes_without_usable_basic_data}"
    )
    command.stdout.write(
        f"Unexpected volumes returned by Comic Vine: {result.unexpected_volumes_returned}"
    )
    command.stdout.write(f"Comic Vine API requests made: {result.api_requests_made}")