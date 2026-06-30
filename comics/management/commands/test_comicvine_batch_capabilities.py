import os
import time

import requests
from django.core.management.base import BaseCommand, CommandError

from comics.models import ComicIssue, ComicVolume


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
ISSUE_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"

VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"

USER_AGENT = "EzyReadComics Comic Vine batch capability tester"


class Command(BaseCommand):
    help = (
        "Test Comic Vine issue and volume batching capabilities. "
        "This command does not write to the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--issue-ids",
            nargs="+",
            type=int,
            help="Specific Comic Vine issue IDs to test.",
        )

        parser.add_argument(
            "--volume-ids",
            nargs="+",
            type=int,
            help="Specific Comic Vine volume IDs to test.",
        )

        parser.add_argument(
            "--sample-size",
            type=int,
            default=5,
            help="How many local issue/volume IDs to auto-pick when IDs are not provided. Defaults to 5.",
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
            raise CommandError("COMICVINE_API_KEY is not set. Add it to your .env file.")

        issue_ids = options["issue_ids"]
        volume_ids = options["volume_ids"]
        sample_size = options["sample_size"]
        request_delay = options["request_delay"]

        validate_options(
            issue_ids=issue_ids,
            volume_ids=volume_ids,
            sample_size=sample_size,
            request_delay=request_delay,
        )

        if not issue_ids:
            issue_ids = get_local_test_issue_ids(sample_size=sample_size)

        if not volume_ids:
            volume_ids = get_local_test_volume_ids(sample_size=sample_size)

        issue_ids = remove_duplicates(issue_ids)
        volume_ids = remove_duplicates(volume_ids)

        if not issue_ids:
            raise CommandError("No local Comic Vine issue IDs were found to test.")

        if not volume_ids:
            raise CommandError("No local Comic Vine volume IDs were found to test.")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine batch capability test"))
        self.stdout.write("This command does not write anything to the database.")

        self.stdout.write("")
        self.stdout.write("Testing issue IDs:")
        self.stdout.write(", ".join(str(issue_id) for issue_id in issue_ids))

        self.stdout.write("")
        self.stdout.write("Testing volume IDs:")
        self.stdout.write(", ".join(str(volume_id) for volume_id in volume_ids))

        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT})

            run_issue_tests(
                command=self,
                session=session,
                api_key=api_key,
                issue_ids=issue_ids,
                request_delay=request_delay,
            )

            run_volume_tests(
                command=self,
                session=session,
                api_key=api_key,
                volume_ids=volume_ids,
                request_delay=request_delay,
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Test complete."))
        self.stdout.write("")
        self.stdout.write("What matters most:")
        self.stdout.write(
            "- If /issues/ pipe-separated ID batching works and person_credits appears, issue hydration can likely be massively optimized."
        )
        self.stdout.write(
            "- If /issues/ ID batching works but person_credits does not appear, we can only batch list-level issue fields."
        )
        self.stdout.write(
            "- If /volumes/ people appears through the list endpoint, volume hydration can likely be massively optimized."
        )
        self.stdout.write(
            "- If /volumes/ people does not appear, volume credits still need detail calls."
        )


def validate_options(issue_ids, volume_ids, sample_size, request_delay):
    if issue_ids is not None and len(issue_ids) < 1:
        raise CommandError("--issue-ids must include at least one ID when provided.")

    if volume_ids is not None and len(volume_ids) < 1:
        raise CommandError("--volume-ids must include at least one ID when provided.")

    if sample_size < 1:
        raise CommandError("--sample-size must be at least 1.")

    if sample_size > 20:
        raise CommandError("--sample-size cannot be above 20 for this test command.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")


def get_local_test_issue_ids(sample_size):
    hydration_needed_ids = list(
        ComicIssue.objects.filter(
            comicvine_id__isnull=False,
            detail_hydration_attempted_at__isnull=True,
        )
        .order_by("id")
        .values_list("comicvine_id", flat=True)[:sample_size]
    )

    if hydration_needed_ids:
        return hydration_needed_ids

    return list(
        ComicIssue.objects.filter(comicvine_id__isnull=False)
        .order_by("id")
        .values_list("comicvine_id", flat=True)[:sample_size]
    )


def get_local_test_volume_ids(sample_size):
    hydration_needed_ids = list(
        ComicVolume.objects.filter(
            detail_hydration_attempted_at__isnull=True,
        )
        .order_by("id")
        .values_list("comicvine_id", flat=True)[:sample_size]
    )

    if hydration_needed_ids:
        return hydration_needed_ids

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


def run_issue_tests(command, session, api_key, issue_ids, request_delay):
    command.stdout.write("")
    command.stdout.write("=" * 72)
    command.stdout.write(command.style.SUCCESS("ISSUE TESTS"))
    command.stdout.write("=" * 72)

    run_issue_detail_control_test(
        command=command,
        session=session,
        api_key=api_key,
        issue_id=issue_ids[0],
    )

    sleep_if_needed(request_delay)

    run_issues_list_test(
        command=command,
        session=session,
        api_key=api_key,
        test_name="Single issue ID through /issues/",
        requested_issue_ids=[issue_ids[0]],
        filter_value=f"id:{issue_ids[0]}",
    )

    if len(issue_ids) > 1:
        sleep_if_needed(request_delay)

        run_issues_list_test(
            command=command,
            session=session,
            api_key=api_key,
            test_name="Multiple issue IDs with pipe-separated values",
            requested_issue_ids=issue_ids,
            filter_value="id:" + "|".join(str(issue_id) for issue_id in issue_ids),
        )

        sleep_if_needed(request_delay)

        run_issues_list_test(
            command=command,
            session=session,
            api_key=api_key,
            test_name="Multiple issue IDs with comma-separated values",
            requested_issue_ids=issue_ids,
            filter_value="id:" + ",".join(str(issue_id) for issue_id in issue_ids),
        )

        sleep_if_needed(request_delay)

        run_issues_list_test(
            command=command,
            session=session,
            api_key=api_key,
            test_name="Multiple repeated issue id filters with pipes",
            requested_issue_ids=issue_ids,
            filter_value="|".join(f"id:{issue_id}" for issue_id in issue_ids),
        )


def run_volume_tests(command, session, api_key, volume_ids, request_delay):
    command.stdout.write("")
    command.stdout.write("=" * 72)
    command.stdout.write(command.style.SUCCESS("VOLUME TESTS"))
    command.stdout.write("=" * 72)

    run_volume_detail_control_test(
        command=command,
        session=session,
        api_key=api_key,
        volume_id=volume_ids[0],
    )

    sleep_if_needed(request_delay)

    run_volumes_list_test(
        command=command,
        session=session,
        api_key=api_key,
        test_name="Single volume ID through /volumes/ with people requested",
        requested_volume_ids=[volume_ids[0]],
        filter_value=f"id:{volume_ids[0]}",
    )

    if len(volume_ids) > 1:
        sleep_if_needed(request_delay)

        run_volumes_list_test(
            command=command,
            session=session,
            api_key=api_key,
            test_name="Multiple volume IDs with pipe-separated values and people requested",
            requested_volume_ids=volume_ids,
            filter_value="id:" + "|".join(str(volume_id) for volume_id in volume_ids),
        )


def run_issue_detail_control_test(command, session, api_key, issue_id):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Control test: single issue detail endpoint"))
    command.stdout.write(f"Endpoint: /issue/4000-{issue_id}/")
    command.stdout.write("Purpose: compare detail fields against /issues/ list fields.")

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": ",".join(
            [
                "id",
                "name",
                "issue_number",
                "cover_date",
                "store_date",
                "date_added",
                "date_last_updated",
                "volume",
                "person_credits",
            ]
        ),
    }

    url = ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_id)
    response_data = fetch_raw_comicvine_json(session=session, url=url, params=params)

    print_issue_response_summary(
        command=command,
        response_data=response_data,
        expected_ids=[issue_id],
        is_detail_response=True,
    )


def run_issues_list_test(command, session, api_key, test_name, requested_issue_ids, filter_value):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS(test_name))
    command.stdout.write("Endpoint: /issues/")
    command.stdout.write(f"Filter being tested: {filter_value}")

    params = {
        "api_key": api_key,
        "format": "json",
        "limit": 100,
        "offset": 0,
        "filter": filter_value,
        "field_list": ",".join(
            [
                "id",
                "name",
                "issue_number",
                "cover_date",
                "store_date",
                "date_added",
                "date_last_updated",
                "volume",
                "person_credits",
            ]
        ),
    }

    response_data = fetch_raw_comicvine_json(session=session, url=ISSUES_URL, params=params)

    print_issue_response_summary(
        command=command,
        response_data=response_data,
        expected_ids=requested_issue_ids,
        is_detail_response=False,
    )


def run_volume_detail_control_test(command, session, api_key, volume_id):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Control test: single volume detail endpoint"))
    command.stdout.write(f"Endpoint: /volume/4050-{volume_id}/")
    command.stdout.write("Purpose: compare detail fields against /volumes/ list fields.")

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": ",".join(
            [
                "id",
                "name",
                "publisher",
                "start_year",
                "count_of_issues",
                "first_issue",
                "last_issue",
                "people",
            ]
        ),
    }

    url = VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_id)
    response_data = fetch_raw_comicvine_json(session=session, url=url, params=params)

    print_volume_response_summary(
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
        "field_list": ",".join(
            [
                "id",
                "name",
                "publisher",
                "start_year",
                "count_of_issues",
                "first_issue",
                "last_issue",
                "people",
            ]
        ),
    }

    response_data = fetch_raw_comicvine_json(session=session, url=VOLUMES_URL, params=params)

    print_volume_response_summary(
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


def print_issue_response_summary(command, response_data, expected_ids, is_detail_response):
    data = print_basic_response_summary(command, response_data)

    if data is None:
        return

    if str(data.get("status_code")) != "1":
        return

    results = normalize_results(data, is_detail_response=is_detail_response)
    returned_ids = [result.get("id") for result in results if result.get("id")]

    print_id_match_summary(
        command=command,
        expected_ids=expected_ids,
        returned_ids=returned_ids,
        item_label="issue",
        is_detail_response=is_detail_response,
    )

    if not results:
        return

    command.stdout.write("")
    command.stdout.write("Returned issue preview:")
    for issue in results[:10]:
        print_issue_line(command, issue)


def print_volume_response_summary(command, response_data, expected_ids, is_detail_response):
    data = print_basic_response_summary(command, response_data)

    if data is None:
        return

    if str(data.get("status_code")) != "1":
        return

    results = normalize_results(data, is_detail_response=is_detail_response)
    returned_ids = [result.get("id") for result in results if result.get("id")]

    print_id_match_summary(
        command=command,
        expected_ids=expected_ids,
        returned_ids=returned_ids,
        item_label="volume",
        is_detail_response=is_detail_response,
    )

    if not results:
        return

    command.stdout.write("")
    command.stdout.write("Returned volume preview:")
    for volume in results[:10]:
        print_volume_line(command, volume)


def print_basic_response_summary(command, response_data):
    command.stdout.write(f"HTTP status: {response_data['http_status']}")

    if response_data["transport_error"]:
        command.stdout.write(
            command.style.ERROR(f"Transport error: {response_data['transport_error']}")
        )
        return None

    data = response_data["json"]

    if data is None:
        command.stdout.write(command.style.ERROR("Comic Vine response was not valid JSON."))
        return None

    command.stdout.write(f"Comic Vine status_code: {data.get('status_code')}")
    command.stdout.write(f"Comic Vine error: {data.get('error')}")
    command.stdout.write(f"number_of_total_results: {data.get('number_of_total_results')}")
    command.stdout.write(f"number_of_page_results: {data.get('number_of_page_results')}")

    if str(data.get("status_code")) != "1":
        command.stdout.write(command.style.ERROR("API did not report success."))

    return data


def normalize_results(data, is_detail_response):
    raw_results = data.get("results")

    if is_detail_response:
        if not raw_results:
            return []

        return [raw_results]

    return raw_results or []


def print_id_match_summary(command, expected_ids, returned_ids, item_label, is_detail_response):
    command.stdout.write(f"Returned IDs: {returned_ids}")

    if is_detail_response:
        return

    expected_id_set = set(expected_ids)
    returned_id_set = set(returned_ids)
    missing_ids = sorted(expected_id_set - returned_id_set)
    unexpected_ids = sorted(returned_id_set - expected_id_set)

    if missing_ids:
        command.stdout.write(f"Requested {item_label} IDs missing from response: {missing_ids}")
    else:
        command.stdout.write(f"Requested {item_label} IDs missing from response: none")

    if unexpected_ids:
        command.stdout.write(f"Unexpected {item_label} IDs returned: {unexpected_ids[:20]}")
    else:
        command.stdout.write(f"Unexpected {item_label} IDs returned: none")

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
            command.style.ERROR("Result: filter probably did not work for exact ID batching.")
        )
    else:
        command.stdout.write(
            command.style.WARNING("Result: no useful records were returned for this filter syntax.")
        )


def print_issue_line(command, issue):
    volume = issue.get("volume") or {}
    person_credits = issue.get("person_credits")

    command.stdout.write(
        f"- issue={issue.get('id')} | #{issue.get('issue_number') or ''} | "
        f"{issue.get('name') or ''} | "
        f"volume={volume.get('id') or 'None'} {volume.get('name') or ''}"
    )

    command.stdout.write(
        f"  fields returned: {', '.join(sorted(issue.keys()))}"
    )

    if "person_credits" in issue:
        command.stdout.write(
            f"  person_credits field returned: yes | count={count_list_value(person_credits)}"
        )
    else:
        command.stdout.write("  person_credits field returned: no")


def print_volume_line(command, volume):
    publisher = volume.get("publisher") or {}
    first_issue = volume.get("first_issue") or {}
    last_issue = volume.get("last_issue") or {}
    people = volume.get("people")

    command.stdout.write(
        f"- volume={volume.get('id')} | {volume.get('name') or ''} | "
        f"publisher={publisher.get('name') or 'None'} | "
        f"start_year={volume.get('start_year') or 'None'} | "
        f"count_of_issues={volume.get('count_of_issues') or 'None'}"
    )

    command.stdout.write(
        f"  first_issue={first_issue.get('id') or 'None'} | "
        f"last_issue={last_issue.get('id') or 'None'}"
    )

    command.stdout.write(
        f"  fields returned: {', '.join(sorted(volume.keys()))}"
    )

    if "people" in volume:
        command.stdout.write(
            f"  people field returned: yes | count={count_list_value(people)}"
        )
    else:
        command.stdout.write("  people field returned: no")


def count_list_value(value):
    if isinstance(value, list):
        return len(value)

    if value is None:
        return 0

    return 1


def sleep_if_needed(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)