import json
import os
import time
from collections import Counter
from datetime import datetime, time as datetime_time
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand, CommandError

from comics.models import (
    ComicIssue,
    ComicIssuePersonCredit,
    ComicPerson,
    ComicVolume,
    ComicVolumePersonCredit,
)


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
ISSUE_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"

VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"

PERSON_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/person/4040-{person_id}/"

USER_AGENT = "EzyReadComics Comic Vine API return inspector"

DEFAULT_ISSUE_IDS = [
    1174565,
    1174566,
    1174567,
    1174568,
    1174569,
]

DEFAULT_VOLUME_IDS = [
    156636,
    173503,
    173504,
    173505,
    173506,
]

DEFAULT_VOLUME_ID_FOR_ISSUE_LIST = 156636

ISSUE_BROAD_FIELD_PROBE = [
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
    "person_credits",
    "character_credits",
    "team_credits",
    "location_credits",
    "concept_credits",
    "object_credits",
    "story_arc_credits",
    "first_appearance_characters",
    "first_appearance_concepts",
    "first_appearance_locations",
    "first_appearance_objects",
    "first_appearance_storyarcs",
    "first_appearance_teams",
    "team_disbanded_in",
]

VOLUME_BROAD_FIELD_PROBE = [
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

PERSON_BROAD_FIELD_PROBE = [
    "id",
    "aliases",
    "api_detail_url",
    "birth",
    "country",
    "date_added",
    "date_last_updated",
    "deck",
    "description",
    "email",
    "gender",
    "hometown",
    "image",
    "name",
    "site_detail_url",
    "website",
]


class Command(BaseCommand):
    help = (
        "Inspect what Comic Vine returns for the endpoint types EzyReadComics uses. "
        "This command is read-only and does not query or write the local database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--issue-ids",
            nargs="+",
            type=int,
            default=DEFAULT_ISSUE_IDS,
            help="Comic Vine issue IDs to use for issue ID batch tests.",
        )

        parser.add_argument(
            "--volume-ids",
            nargs="+",
            type=int,
            default=DEFAULT_VOLUME_IDS,
            help="Comic Vine volume IDs to use for volume ID batch tests.",
        )

        parser.add_argument(
            "--volume-id-for-issue-list",
            type=int,
            default=DEFAULT_VOLUME_ID_FOR_ISSUE_LIST,
            help=(
                "Comic Vine volume ID to use for /issues/?filter=volume:<id> tests. "
                "Defaults to a known volume with issues."
            ),
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="List endpoint limit for inspection calls. Defaults to 5.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=3.0,
            help="Seconds to pause between Comic Vine requests. Defaults to 3.0.",
        )

        parser.add_argument(
            "--output-json",
            default="comicvine_api_inspection.json",
            help=(
                "Path where raw sanitized response data should be saved. "
                "Defaults to comicvine_api_inspection.json."
            ),
        )

        parser.add_argument(
            "--include-person-detail",
            action="store_true",
            help=(
                "After finding the first person credit, also inspect that person's detail endpoint. "
                "This is optional because person detail is not part of the current core import plan."
            ),
        )

        parser.add_argument(
            "--max-preview-items",
            type=int,
            default=2,
            help="How many result items to preview per endpoint. Defaults to 2.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError("COMICVINE_API_KEY is not set. Add it to your .env file.")

        issue_ids = remove_duplicates(options["issue_ids"])
        volume_ids = remove_duplicates(options["volume_ids"])
        volume_id_for_issue_list = options["volume_id_for_issue_list"]
        limit = options["limit"]
        request_delay = options["request_delay"]
        output_json = options["output_json"]
        include_person_detail = options["include_person_detail"]
        max_preview_items = options["max_preview_items"]

        validate_options(
            issue_ids=issue_ids,
            volume_ids=volume_ids,
            volume_id_for_issue_list=volume_id_for_issue_list,
            limit=limit,
            request_delay=request_delay,
            max_preview_items=max_preview_items,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine API return inspector"))
        self.stdout.write("This command is read-only.")
        self.stdout.write("It does not query your local database.")
        self.stdout.write("It does not write to your local database.")
        self.stdout.write("")
        self.stdout.write(f"Issue IDs: {', '.join(str(issue_id) for issue_id in issue_ids)}")
        self.stdout.write(f"Volume IDs: {', '.join(str(volume_id) for volume_id in volume_ids)}")
        self.stdout.write(f"Volume ID for issue-list test: {volume_id_for_issue_list}")
        self.stdout.write(f"List limit: {limit}")
        self.stdout.write(f"Request delay: {request_delay}")
        self.stdout.write(f"Raw sanitized JSON output: {output_json}")

        print_model_field_summary(self)

        inspection_results = []
        derived = {
            "issue_date_added_day": None,
            "issue_date_last_updated_day": None,
            "volume_date_last_updated_day": None,
            "first_person_credit_id": None,
        }

        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT})

            issue_id_batch_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="ISSUES BY PIPE-SEPARATED IDS — default returned fields",
                url=ISSUES_URL,
                params={
                    "api_key": api_key,
                    "format": "json",
                    "limit": limit,
                    "offset": 0,
                    "filter": "id:" + "|".join(str(issue_id) for issue_id in issue_ids),
                },
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, issue_id_batch_response)
            sleep_if_needed(request_delay)

            issue_id_batch_probe_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="ISSUES BY PIPE-SEPARATED IDS — broad field probe",
                url=ISSUES_URL,
                params={
                    "api_key": api_key,
                    "format": "json",
                    "limit": limit,
                    "offset": 0,
                    "filter": "id:" + "|".join(str(issue_id) for issue_id in issue_ids),
                    "field_list": ",".join(ISSUE_BROAD_FIELD_PROBE),
                },
                requested_fields=ISSUE_BROAD_FIELD_PROBE,
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, issue_id_batch_probe_response)
            sleep_if_needed(request_delay)

            issue_detail_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="ISSUE DETAIL — default returned fields",
                url=ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_ids[0]),
                params={
                    "api_key": api_key,
                    "format": "json",
                },
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, issue_detail_response)
            sleep_if_needed(request_delay)

            issue_detail_probe_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="ISSUE DETAIL — broad field probe",
                url=ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_ids[0]),
                params={
                    "api_key": api_key,
                    "format": "json",
                    "field_list": ",".join(ISSUE_BROAD_FIELD_PROBE),
                },
                requested_fields=ISSUE_BROAD_FIELD_PROBE,
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, issue_detail_probe_response)
            sleep_if_needed(request_delay)

            if derived["issue_date_added_day"]:
                inspect_endpoint(
                    command=self,
                    session=session,
                    inspection_results=inspection_results,
                    label="ISSUES BY date_added DAY — default returned fields",
                    url=ISSUES_URL,
                    params={
                        "api_key": api_key,
                        "format": "json",
                        "limit": limit,
                        "offset": 0,
                        "sort": "date_added:asc",
                        "filter": build_day_filter(
                            "date_added",
                            derived["issue_date_added_day"],
                        ),
                    },
                    max_preview_items=max_preview_items,
                )
                sleep_if_needed(request_delay)
            else:
                print_skipped(self, "ISSUES BY date_added DAY", "No issue date_added value was found.")

            if derived["issue_date_last_updated_day"]:
                inspect_endpoint(
                    command=self,
                    session=session,
                    inspection_results=inspection_results,
                    label="ISSUES BY date_last_updated DAY — default returned fields",
                    url=ISSUES_URL,
                    params={
                        "api_key": api_key,
                        "format": "json",
                        "limit": limit,
                        "offset": 0,
                        "sort": "date_last_updated:asc",
                        "filter": build_day_filter(
                            "date_last_updated",
                            derived["issue_date_last_updated_day"],
                        ),
                    },
                    max_preview_items=max_preview_items,
                )
                sleep_if_needed(request_delay)
            else:
                print_skipped(
                    self,
                    "ISSUES BY date_last_updated DAY",
                    "No issue date_last_updated value was found.",
                )

            inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="ISSUES BY VOLUME ID — default returned fields",
                url=ISSUES_URL,
                params={
                    "api_key": api_key,
                    "format": "json",
                    "limit": limit,
                    "offset": 0,
                    "sort": "issue_number:asc",
                    "filter": f"volume:{volume_id_for_issue_list}",
                },
                max_preview_items=max_preview_items,
            )
            sleep_if_needed(request_delay)

            volume_id_batch_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="VOLUMES BY PIPE-SEPARATED IDS — default returned fields",
                url=VOLUMES_URL,
                params={
                    "api_key": api_key,
                    "format": "json",
                    "limit": limit,
                    "offset": 0,
                    "filter": "id:" + "|".join(str(volume_id) for volume_id in volume_ids),
                },
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, volume_id_batch_response)
            sleep_if_needed(request_delay)

            volume_id_batch_probe_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="VOLUMES BY PIPE-SEPARATED IDS — broad field probe",
                url=VOLUMES_URL,
                params={
                    "api_key": api_key,
                    "format": "json",
                    "limit": limit,
                    "offset": 0,
                    "filter": "id:" + "|".join(str(volume_id) for volume_id in volume_ids),
                    "field_list": ",".join(VOLUME_BROAD_FIELD_PROBE),
                },
                requested_fields=VOLUME_BROAD_FIELD_PROBE,
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, volume_id_batch_probe_response)
            sleep_if_needed(request_delay)

            volume_detail_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="VOLUME DETAIL — default returned fields",
                url=VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_ids[0]),
                params={
                    "api_key": api_key,
                    "format": "json",
                },
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, volume_detail_response)
            sleep_if_needed(request_delay)

            volume_detail_probe_response = inspect_endpoint(
                command=self,
                session=session,
                inspection_results=inspection_results,
                label="VOLUME DETAIL — broad field probe",
                url=VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_ids[0]),
                params={
                    "api_key": api_key,
                    "format": "json",
                    "field_list": ",".join(VOLUME_BROAD_FIELD_PROBE),
                },
                requested_fields=VOLUME_BROAD_FIELD_PROBE,
                max_preview_items=max_preview_items,
            )
            update_derived_values_from_response(derived, volume_detail_probe_response)
            sleep_if_needed(request_delay)

            if derived["volume_date_last_updated_day"]:
                inspect_endpoint(
                    command=self,
                    session=session,
                    inspection_results=inspection_results,
                    label="VOLUMES BY date_last_updated DAY — default returned fields",
                    url=VOLUMES_URL,
                    params={
                        "api_key": api_key,
                        "format": "json",
                        "limit": limit,
                        "offset": 0,
                        "sort": "date_last_updated:asc",
                        "filter": build_day_filter(
                            "date_last_updated",
                            derived["volume_date_last_updated_day"],
                        ),
                    },
                    max_preview_items=max_preview_items,
                )
                sleep_if_needed(request_delay)
            else:
                print_skipped(
                    self,
                    "VOLUMES BY date_last_updated DAY",
                    "No volume date_last_updated value was found.",
                )

            if include_person_detail:
                if derived["first_person_credit_id"]:
                    inspect_endpoint(
                        command=self,
                        session=session,
                        inspection_results=inspection_results,
                        label="PERSON DETAIL — first person found from credit data",
                        url=PERSON_DETAIL_URL_TEMPLATE.format(
                            person_id=derived["first_person_credit_id"],
                        ),
                        params={
                            "api_key": api_key,
                            "format": "json",
                            "field_list": ",".join(PERSON_BROAD_FIELD_PROBE),
                        },
                        requested_fields=PERSON_BROAD_FIELD_PROBE,
                        max_preview_items=max_preview_items,
                    )
                    sleep_if_needed(request_delay)
                else:
                    print_skipped(
                        self,
                        "PERSON DETAIL",
                        "No person credit ID was found in inspected issue/volume detail responses.",
                    )

        write_inspection_json(output_json, inspection_results)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Inspection complete."))
        self.stdout.write(f"Raw sanitized response data saved to: {output_json}")
        self.stdout.write("")
        self.stdout.write("Send me the terminal output first.")
        self.stdout.write(
            "If we need deeper analysis after that, I may ask for the saved JSON file contents."
        )


def validate_options(
    issue_ids,
    volume_ids,
    volume_id_for_issue_list,
    limit,
    request_delay,
    max_preview_items,
):
    if not issue_ids:
        raise CommandError("At least one issue ID is required.")

    if not volume_ids:
        raise CommandError("At least one volume ID is required.")

    if volume_id_for_issue_list < 1:
        raise CommandError("--volume-id-for-issue-list must be a positive integer.")

    if limit < 1:
        raise CommandError("--limit must be at least 1.")

    if limit > 100:
        raise CommandError("--limit cannot be above 100 for Comic Vine list requests.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")

    if max_preview_items < 1:
        raise CommandError("--max-preview-items must be at least 1.")


def remove_duplicates(values):
    seen = set()
    deduped_values = []

    for value in values:
        if value in seen:
            continue

        seen.add(value)
        deduped_values.append(value)

    return deduped_values


def inspect_endpoint(
    command,
    session,
    inspection_results,
    label,
    url,
    params,
    requested_fields=None,
    max_preview_items=2,
):
    command.stdout.write("")
    command.stdout.write("=" * 90)
    command.stdout.write(command.style.SUCCESS(label))
    command.stdout.write("=" * 90)
    command.stdout.write(f"URL path: {urlparse(url).path}")
    command.stdout.write(f"Params: {format_sanitized_params(params)}")

    response_record = fetch_raw_comicvine_json(
        session=session,
        url=url,
        params=params,
    )

    response_record["label"] = label
    response_record["url_path"] = urlparse(url).path
    response_record["params"] = sanitize_params(params)
    inspection_results.append(response_record)

    print_response_summary(
        command=command,
        response_record=response_record,
        requested_fields=requested_fields,
        max_preview_items=max_preview_items,
    )

    return response_record


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


def print_response_summary(command, response_record, requested_fields, max_preview_items):
    command.stdout.write(f"HTTP status: {response_record['http_status']}")

    if response_record["transport_error"]:
        command.stdout.write(
            command.style.ERROR(f"Transport error: {response_record['transport_error']}")
        )
        return

    data = response_record["json"]

    if data is None:
        command.stdout.write(command.style.ERROR("Response was not valid JSON."))
        return

    command.stdout.write(f"Comic Vine status_code: {data.get('status_code')}")
    command.stdout.write(f"Comic Vine error: {data.get('error')}")
    command.stdout.write(f"number_of_total_results: {data.get('number_of_total_results')}")
    command.stdout.write(f"number_of_page_results: {data.get('number_of_page_results')}")

    if str(data.get("status_code")) != "1":
        command.stdout.write(command.style.ERROR("Comic Vine did not report success."))
        return

    results = normalize_results(data)

    if not results:
        command.stdout.write(command.style.WARNING("No result records returned."))
        return

    union_keys = sorted(get_union_keys(results))
    command.stdout.write("")
    command.stdout.write(f"Top-level result fields returned: {', '.join(union_keys)}")

    if requested_fields:
        returned_key_set = set(union_keys)
        requested_key_set = set(requested_fields)
        returned_requested_fields = sorted(requested_key_set & returned_key_set)
        missing_requested_fields = sorted(requested_key_set - returned_key_set)

        command.stdout.write("")
        command.stdout.write(
            f"Requested fields that returned: {', '.join(returned_requested_fields) or 'none'}"
        )
        command.stdout.write(
            f"Requested fields missing/ignored: {', '.join(missing_requested_fields) or 'none'}"
        )

    summarize_special_nested_fields(command, results)

    command.stdout.write("")
    command.stdout.write(f"Previewing first {min(len(results), max_preview_items)} result record(s):")
    for index, result in enumerate(results[:max_preview_items], start=1):
        print_result_preview(command, index, result)


def normalize_results(data):
    raw_results = data.get("results")

    if isinstance(raw_results, list):
        return raw_results

    if isinstance(raw_results, dict):
        return [raw_results]

    return []


def get_union_keys(results):
    keys = set()

    for result in results:
        if isinstance(result, dict):
            keys.update(result.keys())

    return keys


def summarize_special_nested_fields(command, results):
    command.stdout.write("")
    command.stdout.write("Nested field summary:")

    nested_fields_found = False

    for field_name in [
        "image",
        "volume",
        "publisher",
        "first_issue",
        "last_issue",
        "person_credits",
        "people",
        "character_credits",
        "team_credits",
        "location_credits",
        "concept_credits",
        "object_credits",
        "story_arc_credits",
        "first_appearance_characters",
        "first_appearance_concepts",
        "first_appearance_locations",
        "first_appearance_objects",
        "first_appearance_storyarcs",
        "first_appearance_teams",
        "team_disbanded_in",
    ]:
        values = [
            result.get(field_name)
            for result in results
            if isinstance(result, dict) and field_name in result
        ]

        if not values:
            continue

        nested_fields_found = True
        print_nested_field_summary(command, field_name, values)

    if not nested_fields_found:
        command.stdout.write("- No selected nested fields found.")


def print_nested_field_summary(command, field_name, values):
    non_empty_values = [
        value
        for value in values
        if value not in (None, "", [], {})
    ]

    if not non_empty_values:
        command.stdout.write(f"- {field_name}: returned but empty in inspected records")
        return

    first_value = non_empty_values[0]

    if isinstance(first_value, dict):
        command.stdout.write(
            f"- {field_name}: object keys = {', '.join(sorted(first_value.keys()))}"
        )
        return

    if isinstance(first_value, list):
        list_lengths = [
            len(value)
            for value in values
            if isinstance(value, list)
        ]

        command.stdout.write(
            f"- {field_name}: list returned; counts seen = {list_lengths}"
        )

        first_item = first_list_item(first_value)
        if isinstance(first_item, dict):
            command.stdout.write(
                f"  first {field_name} item keys = {', '.join(sorted(first_item.keys()))}"
            )

            if field_name in ("person_credits", "people"):
                print_credit_specific_summary(command, field_name, values)

        return

    command.stdout.write(f"- {field_name}: scalar sample = {first_value}")


def print_credit_specific_summary(command, field_name, values):
    credit_items = []

    for value in values:
        if isinstance(value, list):
            credit_items.extend(
                item
                for item in value
                if isinstance(item, dict)
            )

    if not credit_items:
        return

    role_counter = Counter()

    for item in credit_items:
        role = item.get("role") or item.get("job") or item.get("type") or ""
        if role:
            role_counter[role] += 1

    command.stdout.write(f"  total {field_name} objects previewed = {len(credit_items)}")

    if role_counter:
        common_roles = [
            f"{role}: {count}"
            for role, count in role_counter.most_common(10)
        ]
        command.stdout.write(f"  common role/job values = {', '.join(common_roles)}")
    else:
        command.stdout.write("  no role/job values found in previewed credit objects")

    for sample_index, item in enumerate(credit_items[:3], start=1):
        command.stdout.write(
            f"  sample credit {sample_index}: "
            f"id={item.get('id') or 'None'} | "
            f"name={item.get('name') or 'None'} | "
            f"role={item.get('role') or item.get('job') or item.get('type') or 'None'} | "
            f"api_detail_url={item.get('api_detail_url') or 'None'} | "
            f"site_detail_url={item.get('site_detail_url') or 'None'}"
        )


def first_list_item(value):
    if not isinstance(value, list):
        return None

    if not value:
        return None

    return value[0]


def print_result_preview(command, index, result):
    command.stdout.write(f"Result {index}:")

    for key in sorted(result.keys()):
        value = result[key]
        command.stdout.write(f"  {key}: {format_preview_value(value)}")


def format_preview_value(value):
    if isinstance(value, dict):
        return f"object(keys={', '.join(sorted(value.keys()))})"

    if isinstance(value, list):
        if not value:
            return "list(count=0)"

        first_item = value[0]
        if isinstance(first_item, dict):
            return (
                f"list(count={len(value)}, "
                f"first_item_keys={', '.join(sorted(first_item.keys()))})"
            )

        return f"list(count={len(value)}, first_item={truncate_text(str(first_item))})"

    if value is None:
        return "None"

    return truncate_text(str(value))


def truncate_text(value, max_length=180):
    cleaned = value.replace("\n", "\\n").replace("\r", "\\r")

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[: max_length - 3] + "..."


def update_derived_values_from_response(derived, response_record):
    data = response_record.get("json")

    if not isinstance(data, dict):
        return

    if str(data.get("status_code")) != "1":
        return

    results = normalize_results(data)

    if not results:
        return

    for result in results:
        if not isinstance(result, dict):
            continue

        if not derived["issue_date_added_day"]:
            derived["issue_date_added_day"] = extract_date_day(result.get("date_added"))

        if not derived["issue_date_last_updated_day"]:
            derived["issue_date_last_updated_day"] = extract_date_day(
                result.get("date_last_updated")
            )

        if not derived["volume_date_last_updated_day"]:
            derived["volume_date_last_updated_day"] = extract_date_day(
                result.get("date_last_updated")
            )

        if not derived["first_person_credit_id"]:
            derived["first_person_credit_id"] = find_first_person_credit_id(result)


def find_first_person_credit_id(result):
    for field_name in ("person_credits", "people"):
        value = result.get(field_name)

        if not isinstance(value, list):
            continue

        for item in value:
            if not isinstance(item, dict):
                continue

            person_id = item.get("id")

            if person_id:
                return person_id

    return None


def extract_date_day(value):
    if not value:
        return None

    text_value = str(value).strip()

    if not text_value:
        return None

    # Comic Vine commonly returns values like:
    # "2026-06-29 14:20:11"
    # This only needs the YYYY-MM-DD day part for date scan tests.
    date_part = text_value[:10]

    try:
        datetime.strptime(date_part, "%Y-%m-%d")
    except ValueError:
        return None

    return date_part


def build_day_filter(field_name, date_day):
    scan_date = datetime.strptime(date_day, "%Y-%m-%d").date()
    start_datetime = datetime.combine(scan_date, datetime_time.min)
    end_datetime = datetime.combine(scan_date, datetime_time.max).replace(microsecond=0)

    return f"{field_name}:{start_datetime}|{end_datetime}"


def print_skipped(command, label, reason):
    command.stdout.write("")
    command.stdout.write("=" * 90)
    command.stdout.write(command.style.WARNING(f"SKIPPED: {label}"))
    command.stdout.write("=" * 90)
    command.stdout.write(reason)


def sanitize_params(params):
    sanitized = {}

    for key, value in params.items():
        if key == "api_key":
            sanitized[key] = "<hidden>"
        else:
            sanitized[key] = value

    return sanitized


def format_sanitized_params(params):
    sanitized = sanitize_params(params)

    return json.dumps(sanitized, indent=2, sort_keys=True)


def write_inspection_json(output_json, inspection_results):
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(
            inspection_results,
            output_file,
            indent=2,
            sort_keys=True,
        )


def print_model_field_summary(command):
    command.stdout.write("")
    command.stdout.write("=" * 90)
    command.stdout.write(command.style.SUCCESS("CURRENT LOCAL MODEL FIELD SUMMARY"))
    command.stdout.write("=" * 90)
    command.stdout.write("This uses model definitions only. It does not query your database.")
    command.stdout.write("")

    for model in [
        ComicVolume,
        ComicIssue,
        ComicPerson,
        ComicIssuePersonCredit,
        ComicVolumePersonCredit,
    ]:
        command.stdout.write(f"{model.__name__}:")
        command.stdout.write(f"  {', '.join(get_concrete_field_names(model))}")


def get_concrete_field_names(model):
    field_names = []

    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue

        field_names.append(field.name)

    return field_names


def sleep_if_needed(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)