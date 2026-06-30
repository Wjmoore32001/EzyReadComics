import os
import time

import requests
from django.core.management.base import BaseCommand, CommandError

from comics.models import ComicVolume


VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"
USER_AGENT = "EzyReadComics Comic Vine volume batching tester"


class Command(BaseCommand):
    help = (
        "Test whether Comic Vine can return multiple specific volumes from the "
        "/volumes/ list endpoint in one request. This command does not write to the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--volume-ids",
            nargs="+",
            type=int,
            help=(
                "Specific Comic Vine volume IDs to test. "
                "Example: --volume-ids 158814 12345 67890"
            ),
        )

        parser.add_argument(
            "--sample-size",
            type=int,
            default=5,
            help=(
                "How many local volume IDs to auto-pick when --volume-ids is not provided. "
                "Defaults to 5."
            ),
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=1.0,
            help="Seconds to pause between test requests. Defaults to 1.0.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        volume_ids = options["volume_ids"]
        sample_size = options["sample_size"]
        request_delay = options["request_delay"]

        validate_options(
            volume_ids=volume_ids,
            sample_size=sample_size,
            request_delay=request_delay,
        )

        if not volume_ids:
            volume_ids = get_local_test_volume_ids(sample_size=sample_size)

        if not volume_ids:
            raise CommandError("No local Comic Vine volume IDs were found to test.")

        volume_ids = remove_duplicates(volume_ids)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine volume batching test"))
        self.stdout.write("This command does not write anything to the database.")
        self.stdout.write("")
        self.stdout.write("Testing these Comic Vine volume IDs:")
        self.stdout.write(", ".join(str(volume_id) for volume_id in volume_ids))

        with requests.Session() as session:
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                }
            )

            run_detail_control_test(
                command=self,
                session=session,
                api_key=api_key,
                volume_id=volume_ids[0],
            )

            sleep_if_needed(request_delay)

            run_volumes_list_test(
                command=self,
                session=session,
                api_key=api_key,
                test_name="Single ID through /volumes/",
                requested_volume_ids=[volume_ids[0]],
                filter_value=f"id:{volume_ids[0]}",
            )

            if len(volume_ids) > 1:
                sleep_if_needed(request_delay)

                run_volumes_list_test(
                    command=self,
                    session=session,
                    api_key=api_key,
                    test_name="Multiple IDs with pipe-separated values",
                    requested_volume_ids=volume_ids,
                    filter_value="id:" + "|".join(str(volume_id) for volume_id in volume_ids),
                )

                sleep_if_needed(request_delay)

                run_volumes_list_test(
                    command=self,
                    session=session,
                    api_key=api_key,
                    test_name="Multiple IDs with comma-separated values",
                    requested_volume_ids=volume_ids,
                    filter_value="id:" + ",".join(str(volume_id) for volume_id in volume_ids),
                )

                sleep_if_needed(request_delay)

                run_volumes_list_test(
                    command=self,
                    session=session,
                    api_key=api_key,
                    test_name="Multiple repeated id filters with pipes",
                    requested_volume_ids=volume_ids,
                    filter_value="|".join(
                        f"id:{volume_id}"
                        for volume_id in volume_ids
                    ),
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Test complete."))
        self.stdout.write("")
        self.stdout.write("How to read the result:")
        self.stdout.write(
            "- If one of the multiple-ID tests returns only the requested IDs, batching is likely usable."
        )
        self.stdout.write(
            "- If it returns unrelated IDs, too many IDs, zero IDs, or an API error, that syntax is not usable."
        )
        self.stdout.write(
            "- If only the single-ID /volumes/ test works, Comic Vine may support ID filtering but not multi-ID batching."
        )


def validate_options(volume_ids, sample_size, request_delay):
    if volume_ids is not None and len(volume_ids) < 1:
        raise CommandError("--volume-ids must include at least one ID when provided.")

    if sample_size < 1:
        raise CommandError("--sample-size must be at least 1.")

    if sample_size > 20:
        raise CommandError("--sample-size cannot be above 20 for this test command.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")


def get_local_test_volume_ids(sample_size):
    missing_basic_data_ids = list(
        ComicVolume.objects.filter(
            publisher="",
            start_year="",
        )
        .order_by("id")
        .values_list("comicvine_id", flat=True)[:sample_size]
    )

    if missing_basic_data_ids:
        return missing_basic_data_ids

    return list(
        ComicVolume.objects.order_by("id")
        .values_list("comicvine_id", flat=True)[:sample_size]
    )


def remove_duplicates(values):
    seen = set()
    deduped_values = []

    for value in values:
        if value in seen:
            continue

        seen.add(value)
        deduped_values.append(value)

    return deduped_values


def run_detail_control_test(command, session, api_key, volume_id):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Control test: single volume detail endpoint"))
    command.stdout.write(f"Endpoint: /volume/4050-{volume_id}/")
    command.stdout.write("Purpose: prove the first ID is valid and see detail data shape.")

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": "id,name,publisher,start_year",
    }

    url = VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_id)
    response_data = fetch_raw_comicvine_json(
        session=session,
        url=url,
        params=params,
    )

    print_response_summary(
        command=command,
        response_data=response_data,
        expected_ids=[volume_id],
        is_detail_response=True,
    )


def run_volumes_list_test(command, session, api_key, test_name, requested_volume_ids, filter_value):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS(test_name))
    command.stdout.write("Endpoint: /volumes/")
    command.stdout.write(f"Filter being tested: {filter_value}")

    params = {
        "api_key": api_key,
        "format": "json",
        "limit": 100,
        "offset": 0,
        "filter": filter_value,
        "field_list": "id,name,publisher,start_year",
    }

    response_data = fetch_raw_comicvine_json(
        session=session,
        url=VOLUMES_URL,
        params=params,
    )

    print_response_summary(
        command=command,
        response_data=response_data,
        expected_ids=requested_volume_ids,
        is_detail_response=False,
    )


def fetch_raw_comicvine_json(session, url, params):
    try:
        response = session.get(url, params=params, timeout=30)
    except requests.RequestException as error:
        return {
            "transport_error": str(error),
            "http_status": None,
            "json": None,
        }

    try:
        data = response.json()
    except ValueError:
        data = None

    return {
        "transport_error": "",
        "http_status": response.status_code,
        "json": data,
    }


def print_response_summary(command, response_data, expected_ids, is_detail_response):
    command.stdout.write(f"HTTP status: {response_data['http_status']}")

    if response_data["transport_error"]:
        command.stdout.write(
            command.style.ERROR(f"Transport error: {response_data['transport_error']}")
        )
        return

    data = response_data["json"]

    if data is None:
        command.stdout.write(command.style.ERROR("Comic Vine response was not valid JSON."))
        return

    api_status_code = data.get("status_code")
    api_error = data.get("error")

    command.stdout.write(f"Comic Vine status_code: {api_status_code}")
    command.stdout.write(f"Comic Vine error: {api_error}")

    if str(api_status_code) != "1":
        command.stdout.write(command.style.ERROR("API did not report success."))
        return

    if is_detail_response:
        result = data.get("results") or {}
        returned_ids = [result.get("id")] if result.get("id") else []
        command.stdout.write(f"Returned detail ID: {returned_ids[0] if returned_ids else 'None'}")

        if result:
            print_volume_line(command, result)

        return

    results = data.get("results") or []
    returned_ids = [
        result.get("id")
        for result in results
        if result.get("id")
    ]

    expected_id_set = set(expected_ids)
    returned_id_set = set(returned_ids)
    missing_ids = sorted(expected_id_set - returned_id_set)
    unexpected_ids = sorted(returned_id_set - expected_id_set)

    command.stdout.write(f"number_of_total_results: {data.get('number_of_total_results')}")
    command.stdout.write(f"number_of_page_results: {data.get('number_of_page_results')}")
    command.stdout.write(f"Returned IDs: {returned_ids}")

    if missing_ids:
        command.stdout.write(f"Requested IDs missing from response: {missing_ids}")
    else:
        command.stdout.write("Requested IDs missing from response: none")

    if unexpected_ids:
        command.stdout.write(f"Unexpected IDs returned: {unexpected_ids[:20]}")
    else:
        command.stdout.write("Unexpected IDs returned: none")

    if returned_id_set == expected_id_set:
        command.stdout.write(command.style.SUCCESS("Result: exact requested ID match."))
    elif returned_id_set and returned_id_set.issubset(expected_id_set):
        command.stdout.write(
            command.style.WARNING(
                "Result: only requested IDs were returned, but not all requested IDs came back."
            )
        )
    elif unexpected_ids:
        command.stdout.write(
            command.style.ERROR(
                "Result: filter probably did not work for exact ID batching."
            )
        )
    else:
        command.stdout.write(
            command.style.WARNING(
                "Result: no useful volume records were returned for this filter syntax."
            )
        )

    if results:
        command.stdout.write("")
        command.stdout.write("Returned volume preview:")
        for result in results[:10]:
            print_volume_line(command, result)


def print_volume_line(command, volume):
    publisher = volume.get("publisher") or {}
    publisher_name = publisher.get("name") or ""
    start_year = volume.get("start_year") or ""

    command.stdout.write(
        f"- {volume.get('id')} | {volume.get('name') or ''} | "
        f"publisher={publisher_name or 'None'} | start_year={start_year or 'None'}"
    )


def sleep_if_needed(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)