import json
import os
import time
from datetime import datetime, time as datetime_time
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from comics.models import ComicIssue, ComicVolume


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
ISSUE_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"

VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"

PERSON_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/person/4040-{person_id}/"
PUBLISHER_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/publisher/4010-{publisher_id}/"

USER_AGENT = "EzyReadComics Comic Vine API shape debugger"


class Command(BaseCommand):
    help = (
        "Inspect the full default response shapes for Comic Vine endpoints used by "
        "EzyReadComics. This command does not write to the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--issue-ids",
            nargs="+",
            type=int,
            help="Specific Comic Vine issue IDs to inspect.",
        )

        parser.add_argument(
            "--volume-ids",
            nargs="+",
            type=int,
            help="Specific Comic Vine volume IDs to inspect.",
        )

        parser.add_argument(
            "--sample-size",
            type=int,
            default=3,
            help="How many local issue/volume IDs to auto-pick. Defaults to 3.",
        )

        parser.add_argument(
            "--list-limit",
            type=int,
            default=5,
            help="How many records to request for list/date/volume-list probes. Defaults to 5.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=3.0,
            help="Seconds to pause between Comic Vine requests. Defaults to 3.0.",
        )

        parser.add_argument(
            "--save-json",
            default="comicvine_api_shape_probe_output.json",
            help=(
                "Local path where raw API responses should be saved. "
                "Defaults to comicvine_api_shape_probe_output.json."
            ),
        )

        parser.add_argument(
            "--no-extra-details",
            action="store_true",
            help=(
                "Skip person and publisher detail probes. By default, this command tries "
                "one person detail and one publisher detail when IDs are available."
            ),
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError("COMICVINE_API_KEY is not set. Add it to your .env file.")

        issue_ids = options["issue_ids"]
        volume_ids = options["volume_ids"]
        sample_size = options["sample_size"]
        list_limit = options["list_limit"]
        request_delay = options["request_delay"]
        save_json_path = options["save_json"]
        include_extra_details = not options["no_extra_details"]

        validate_options(
            issue_ids=issue_ids,
            volume_ids=volume_ids,
            sample_size=sample_size,
            list_limit=list_limit,
            request_delay=request_delay,
        )

        local_context = get_local_context(
            issue_ids=issue_ids,
            volume_ids=volume_ids,
            sample_size=sample_size,
        )

        if not local_context["issue_ids"]:
            raise CommandError("No issue IDs were provided or found locally.")

        if not local_context["volume_ids"]:
            raise CommandError("No volume IDs were provided or found locally.")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine API shape debugger"))
        self.stdout.write("This command does not write anything to the database.")
        self.stdout.write("Requests intentionally omit field_list so Comic Vine returns its default full shape.")
        self.stdout.write("")
        self.stdout.write("Issue IDs:")
        self.stdout.write(", ".join(str(issue_id) for issue_id in local_context["issue_ids"]))
        self.stdout.write("")
        self.stdout.write("Volume IDs:")
        self.stdout.write(", ".join(str(volume_id) for volume_id in local_context["volume_ids"]))
        self.stdout.write("")
        self.stdout.write(f"List limit: {list_limit}")
        self.stdout.write(f"Request delay: {request_delay}")
        self.stdout.write(f"Raw JSON output path: {save_json_path}")

        raw_results = {}

        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT})

            run_core_issue_probes(
                command=self,
                session=session,
                api_key=api_key,
                local_context=local_context,
                list_limit=list_limit,
                request_delay=request_delay,
                raw_results=raw_results,
            )

            run_core_volume_probes(
                command=self,
                session=session,
                api_key=api_key,
                local_context=local_context,
                list_limit=list_limit,
                request_delay=request_delay,
                raw_results=raw_results,
            )

            if include_extra_details:
                run_extra_detail_probes(
                    command=self,
                    session=session,
                    api_key=api_key,
                    request_delay=request_delay,
                    raw_results=raw_results,
                )

        save_raw_results(save_json_path, raw_results)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("API shape probe complete."))
        self.stdout.write(f"Raw API responses saved to: {save_json_path}")
        self.stdout.write("")
        self.stdout.write("Send me the console output first. If needed, you can also paste sections from the saved JSON file.")


def validate_options(issue_ids, volume_ids, sample_size, list_limit, request_delay):
    if issue_ids is not None and len(issue_ids) < 1:
        raise CommandError("--issue-ids must include at least one ID when provided.")

    if volume_ids is not None and len(volume_ids) < 1:
        raise CommandError("--volume-ids must include at least one ID when provided.")

    if sample_size < 1:
        raise CommandError("--sample-size must be at least 1.")

    if sample_size > 20:
        raise CommandError("--sample-size cannot be above 20 for this debug command.")

    if list_limit < 1:
        raise CommandError("--list-limit must be at least 1.")

    if list_limit > 100:
        raise CommandError("--list-limit cannot be above 100.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")


def get_local_context(issue_ids, volume_ids, sample_size):
    context = {
        "issue_ids": remove_duplicates(issue_ids or get_local_issue_ids(sample_size)),
        "volume_ids": remove_duplicates(volume_ids or get_local_volume_ids(sample_size)),
        "issue_volume_id": None,
        "issue_date_added": None,
        "issue_date_last_updated": None,
        "volume_date_last_updated": None,
    }

    first_issue = (
        ComicIssue.objects.filter(comicvine_id__in=context["issue_ids"])
        .select_related("volume")
        .order_by("id")
        .first()
    )

    if first_issue:
        if first_issue.volume:
            context["issue_volume_id"] = first_issue.volume.comicvine_id

        if first_issue.date_added:
            context["issue_date_added"] = first_issue.date_added.date()

        if first_issue.date_last_updated:
            context["issue_date_last_updated"] = first_issue.date_last_updated.date()

    if not context["issue_volume_id"] and context["volume_ids"]:
        context["issue_volume_id"] = context["volume_ids"][0]

    first_volume = (
        ComicVolume.objects.filter(comicvine_id__in=context["volume_ids"])
        .order_by("id")
        .first()
    )

    if first_volume and first_volume.date_last_updated:
        context["volume_date_last_updated"] = first_volume.date_last_updated.date()

    return context


def get_local_issue_ids(sample_size):
    return list(
        ComicIssue.objects.filter(comicvine_id__isnull=False)
        .order_by("id")
        .values_list("comicvine_id", flat=True)[:sample_size]
    )


def get_local_volume_ids(sample_size):
    return list(
        ComicVolume.objects.filter(comicvine_id__isnull=False)
        .order_by("id")
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


def run_core_issue_probes(
    command,
    session,
    api_key,
    local_context,
    list_limit,
    request_delay,
    raw_results,
):
    command.stdout.write("")
    command.stdout.write("=" * 80)
    command.stdout.write(command.style.SUCCESS("ISSUE API UNITS"))
    command.stdout.write("=" * 80)

    issue_ids = local_context["issue_ids"]

    run_probe(
        command=command,
        session=session,
        api_key=api_key,
        probe_name="issue_detail_default_full_shape",
        endpoint_label=f"/issue/4000-{issue_ids[0]}/",
        url=ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_ids[0]),
        params={},
        raw_results=raw_results,
    )

    sleep_if_needed(request_delay)

    run_probe(
        command=command,
        session=session,
        api_key=api_key,
        probe_name="issues_list_by_pipe_ids_default_full_shape",
        endpoint_label="/issues/ filter=id:a|b|c",
        url=ISSUES_URL,
        params={
            "limit": list_limit,
            "offset": 0,
            "filter": "id:" + "|".join(str(issue_id) for issue_id in issue_ids),
        },
        raw_results=raw_results,
    )

    sleep_if_needed(request_delay)

    if local_context["issue_volume_id"]:
        run_probe(
            command=command,
            session=session,
            api_key=api_key,
            probe_name="issues_list_by_volume_default_full_shape",
            endpoint_label=f"/issues/ filter=volume:{local_context['issue_volume_id']}",
            url=ISSUES_URL,
            params={
                "limit": list_limit,
                "offset": 0,
                "filter": f"volume:{local_context['issue_volume_id']}",
            },
            raw_results=raw_results,
        )

        sleep_if_needed(request_delay)

    if local_context["issue_date_added"]:
        run_probe(
            command=command,
            session=session,
            api_key=api_key,
            probe_name="issues_list_by_date_added_default_full_shape",
            endpoint_label=f"/issues/ filter=date_added:{local_context['issue_date_added']}",
            url=ISSUES_URL,
            params={
                "limit": list_limit,
                "offset": 0,
                "sort": "date_added:asc",
                "filter": build_day_filter("date_added", local_context["issue_date_added"]),
            },
            raw_results=raw_results,
        )

        sleep_if_needed(request_delay)

    else:
        print_skipped_probe(
            command=command,
            probe_name="issues_list_by_date_added_default_full_shape",
            reason="No local issue date_added was available.",
        )

    if local_context["issue_date_last_updated"]:
        run_probe(
            command=command,
            session=session,
            api_key=api_key,
            probe_name="issues_list_by_date_last_updated_default_full_shape",
            endpoint_label=f"/issues/ filter=date_last_updated:{local_context['issue_date_last_updated']}",
            url=ISSUES_URL,
            params={
                "limit": list_limit,
                "offset": 0,
                "sort": "date_last_updated:asc",
                "filter": build_day_filter(
                    "date_last_updated",
                    local_context["issue_date_last_updated"],
                ),
            },
            raw_results=raw_results,
        )

        sleep_if_needed(request_delay)

    else:
        print_skipped_probe(
            command=command,
            probe_name="issues_list_by_date_last_updated_default_full_shape",
            reason="No local issue date_last_updated was available.",
        )


def run_core_volume_probes(
    command,
    session,
    api_key,
    local_context,
    list_limit,
    request_delay,
    raw_results,
):
    command.stdout.write("")
    command.stdout.write("=" * 80)
    command.stdout.write(command.style.SUCCESS("VOLUME API UNITS"))
    command.stdout.write("=" * 80)

    volume_ids = local_context["volume_ids"]

    run_probe(
        command=command,
        session=session,
        api_key=api_key,
        probe_name="volume_detail_default_full_shape",
        endpoint_label=f"/volume/4050-{volume_ids[0]}/",
        url=VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_ids[0]),
        params={},
        raw_results=raw_results,
    )

    sleep_if_needed(request_delay)

    run_probe(
        command=command,
        session=session,
        api_key=api_key,
        probe_name="volumes_list_by_pipe_ids_default_full_shape",
        endpoint_label="/volumes/ filter=id:a|b|c",
        url=VOLUMES_URL,
        params={
            "limit": list_limit,
            "offset": 0,
            "filter": "id:" + "|".join(str(volume_id) for volume_id in volume_ids),
        },
        raw_results=raw_results,
    )

    sleep_if_needed(request_delay)

    if local_context["volume_date_last_updated"]:
        run_probe(
            command=command,
            session=session,
            api_key=api_key,
            probe_name="volumes_list_by_date_last_updated_default_full_shape",
            endpoint_label=f"/volumes/ filter=date_last_updated:{local_context['volume_date_last_updated']}",
            url=VOLUMES_URL,
            params={
                "limit": list_limit,
                "offset": 0,
                "sort": "date_last_updated:asc",
                "filter": build_day_filter(
                    "date_last_updated",
                    local_context["volume_date_last_updated"],
                ),
            },
            raw_results=raw_results,
        )

        sleep_if_needed(request_delay)

    else:
        print_skipped_probe(
            command=command,
            probe_name="volumes_list_by_date_last_updated_default_full_shape",
            reason="No local volume date_last_updated was available.",
        )


def run_extra_detail_probes(command, session, api_key, request_delay, raw_results):
    command.stdout.write("")
    command.stdout.write("=" * 80)
    command.stdout.write(command.style.SUCCESS("EXTRA NESTED DETAIL API UNITS"))
    command.stdout.write("=" * 80)

    person_id = find_first_person_id(raw_results)
    publisher_id = find_first_publisher_id(raw_results)

    if person_id:
        run_probe(
            command=command,
            session=session,
            api_key=api_key,
            probe_name="person_detail_default_full_shape",
            endpoint_label=f"/person/4040-{person_id}/",
            url=PERSON_DETAIL_URL_TEMPLATE.format(person_id=person_id),
            params={},
            raw_results=raw_results,
        )

        sleep_if_needed(request_delay)

    else:
        print_skipped_probe(
            command=command,
            probe_name="person_detail_default_full_shape",
            reason="No person ID was found in issue person_credits or volume people.",
        )

    if publisher_id:
        run_probe(
            command=command,
            session=session,
            api_key=api_key,
            probe_name="publisher_detail_default_full_shape",
            endpoint_label=f"/publisher/4010-{publisher_id}/",
            url=PUBLISHER_DETAIL_URL_TEMPLATE.format(publisher_id=publisher_id),
            params={},
            raw_results=raw_results,
        )

        sleep_if_needed(request_delay)

    else:
        print_skipped_probe(
            command=command,
            probe_name="publisher_detail_default_full_shape",
            reason="No publisher ID was found in volume responses.",
        )


def run_probe(command, session, api_key, probe_name, endpoint_label, url, params, raw_results):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS(probe_name))
    command.stdout.write(f"Endpoint: {endpoint_label}")

    request_params = {
        "api_key": api_key,
        "format": "json",
        **params,
    }

    # Do not add field_list. This is intentional.
    response_data = fetch_raw_comicvine_json(
        session=session,
        url=url,
        params=request_params,
    )

    raw_results[probe_name] = {
        "endpoint": endpoint_label,
        "params_without_api_key": {
            key: value
            for key, value in request_params.items()
            if key != "api_key"
        },
        "response": response_data,
    }

    print_response_summary(
        command=command,
        response_data=response_data,
    )


def fetch_raw_comicvine_json(session, url, params):
    try:
        response = session.get(url, params=params, timeout=45)
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


def print_response_summary(command, response_data):
    command.stdout.write(f"HTTP status: {response_data['http_status']}")

    if response_data["transport_error"]:
        command.stdout.write(
            command.style.ERROR(f"Transport error: {response_data['transport_error']}")
        )
        return

    data = response_data["json"]

    if data is None:
        command.stdout.write(command.style.ERROR("Response was not valid JSON."))
        return

    command.stdout.write(f"Comic Vine status_code: {data.get('status_code')}")
    command.stdout.write(f"Comic Vine error: {data.get('error')}")
    command.stdout.write(f"number_of_total_results: {data.get('number_of_total_results')}")
    command.stdout.write(f"number_of_page_results: {data.get('number_of_page_results')}")

    if str(data.get("status_code")) != "1":
        command.stdout.write(command.style.ERROR("Comic Vine API did not report success."))
        return

    results = normalize_results(data)

    if not results:
        command.stdout.write(command.style.WARNING("No result records returned."))
        return

    command.stdout.write("")
    command.stdout.write("Result count summarized:")
    command.stdout.write(str(len(results)))

    command.stdout.write("")
    command.stdout.write("Top-level result fields:")
    print_field_list(command, collect_top_level_fields(results))

    command.stdout.write("")
    command.stdout.write("First result field shapes:")
    print_result_shape(command, results[0])

    command.stdout.write("")
    command.stdout.write("Credit / nested relationship summary:")
    print_credit_and_relationship_summary(command, results[0])


def normalize_results(data):
    raw_results = data.get("results")

    if isinstance(raw_results, list):
        return raw_results

    if isinstance(raw_results, dict):
        return [raw_results]

    return []


def collect_top_level_fields(results):
    fields = set()

    for result in results:
        if isinstance(result, dict):
            fields.update(result.keys())

    return sorted(fields)


def print_field_list(command, fields):
    for field in fields:
        command.stdout.write(f"- {field}")


def print_result_shape(command, result):
    for key in sorted(result.keys()):
        value = result[key]
        command.stdout.write(format_value_shape(key, value))


def format_value_shape(key, value):
    if isinstance(value, dict):
        return f"- {key}: object keys={sorted(value.keys())}"

    if isinstance(value, list):
        if not value:
            return f"- {key}: list count=0"

        first_item = value[0]

        if isinstance(first_item, dict):
            return (
                f"- {key}: list count={len(value)} "
                f"first_item_keys={sorted(first_item.keys())}"
            )

        return f"- {key}: list count={len(value)} first_item_type={type(first_item).__name__}"

    return f"- {key}: {type(value).__name__} sample={truncate_value(value)}"


def print_credit_and_relationship_summary(command, result):
    relationship_fields = [
        "person_credits",
        "people",
        "character_credits",
        "team_credits",
        "location_credits",
        "concept_credits",
        "object_credits",
        "story_arc_credits",
        "publisher",
        "volume",
        "first_issue",
        "last_issue",
    ]

    found_any = False

    for field in relationship_fields:
        if field not in result:
            continue

        found_any = True
        value = result[field]

        if isinstance(value, list):
            command.stdout.write(f"- {field}: list count={len(value)}")

            if value and isinstance(value[0], dict):
                command.stdout.write(f"  first item keys: {sorted(value[0].keys())}")
                print_credit_role_counts(command, field, value)
                print_credit_preview(command, value)

        elif isinstance(value, dict):
            command.stdout.write(f"- {field}: object keys={sorted(value.keys())}")
            command.stdout.write(f"  preview: {format_small_object(value)}")

        else:
            command.stdout.write(f"- {field}: {type(value).__name__} sample={truncate_value(value)}")

    if not found_any:
        command.stdout.write("- No known credit/relationship fields found on first result.")


def print_credit_role_counts(command, field_name, values):
    role_counts = {}

    for item in values:
        if not isinstance(item, dict):
            continue

        role = item.get("role") or item.get("role_name") or item.get("type") or ""

        if not role:
            continue

        role_counts[role] = role_counts.get(role, 0) + 1

    if not role_counts:
        return

    command.stdout.write(f"  role/type counts for {field_name}:")
    for role, count in sorted(role_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:20]:
        command.stdout.write(f"    {role}: {count}")


def print_credit_preview(command, values):
    command.stdout.write("  first credit/relationship items:")

    for item in values[:5]:
        if not isinstance(item, dict):
            command.stdout.write(f"    - {truncate_value(item)}")
            continue

        pieces = []

        for key in ["id", "name", "role", "role_name", "type", "api_detail_url", "site_detail_url"]:
            if key in item and item[key]:
                pieces.append(f"{key}={truncate_value(item[key])}")

        command.stdout.write("    - " + " | ".join(pieces))


def format_small_object(value):
    pieces = []

    for key in ["id", "name", "issue_number", "api_detail_url", "site_detail_url"]:
        if key in value and value[key]:
            pieces.append(f"{key}={truncate_value(value[key])}")

    if pieces:
        return " | ".join(pieces)

    return truncate_value(value)


def truncate_value(value, max_length=120):
    if value is None:
        return "None"

    text = str(value).replace("\n", " ").replace("\r", " ").strip()

    if len(text) <= max_length:
        return text

    return text[:max_length] + "..."


def build_day_filter(field_name, date_value):
    start_datetime = datetime.combine(date_value, datetime_time.min)
    end_datetime = datetime.combine(date_value, datetime_time.max).replace(microsecond=0)

    return f"{field_name}:{start_datetime}|{end_datetime}"


def find_first_person_id(raw_results):
    for probe_data in raw_results.values():
        data = probe_data.get("response", {}).get("json")

        if not data or str(data.get("status_code")) != "1":
            continue

        for result in normalize_results(data):
            person_id = find_person_id_in_result(result)

            if person_id:
                return person_id

    return None


def find_person_id_in_result(result):
    for field in ["person_credits", "people"]:
        values = result.get(field)

        if not isinstance(values, list):
            continue

        for item in values:
            if not isinstance(item, dict):
                continue

            person_id = item.get("id")

            if person_id:
                return person_id

    return None


def find_first_publisher_id(raw_results):
    for probe_data in raw_results.values():
        data = probe_data.get("response", {}).get("json")

        if not data or str(data.get("status_code")) != "1":
            continue

        for result in normalize_results(data):
            publisher = result.get("publisher")

            if not isinstance(publisher, dict):
                continue

            publisher_id = publisher.get("id")

            if publisher_id:
                return publisher_id

    return None


def print_skipped_probe(command, probe_name, reason):
    command.stdout.write("")
    command.stdout.write(command.style.WARNING(f"{probe_name} skipped"))
    command.stdout.write(reason)


def sleep_if_needed(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)


def save_raw_results(save_json_path, raw_results):
    output_path = Path(save_json_path)
    output_path.write_text(
        json.dumps(raw_results, indent=2, sort_keys=True),
        encoding="utf-8",
    )