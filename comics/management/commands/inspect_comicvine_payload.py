import json
import os
from datetime import datetime
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
ISSUE_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"

VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"

USER_AGENT = "EzyReadComics Comic Vine payload inspector"


class Command(BaseCommand):
    help = (
        "Inspect raw Comic Vine issue and volume payloads without saving anything. "
        "This is for model planning only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample-limit",
            type=int,
            default=1,
            help=(
                "Number of issue-list and volume-list records to fetch for inspection. "
                "Use 0 to skip list endpoint samples. Defaults to 1."
            ),
        )

        parser.add_argument(
            "--issue-id",
            type=int,
            help="Optional Comic Vine issue ID to inspect through the issue detail endpoint.",
        )

        parser.add_argument(
            "--volume-id",
            type=int,
            help="Optional Comic Vine volume ID to inspect through the volume detail endpoint.",
        )

        parser.add_argument(
            "--save-json",
            action="store_true",
            help="Save raw Comic Vine JSON responses to local sample files.",
        )

        parser.add_argument(
            "--output-dir",
            default="comicvine_payload_samples",
            help="Directory where raw JSON files are saved when --save-json is used.",
        )

        parser.add_argument(
            "--max-depth",
            type=int,
            default=4,
            help="Maximum nested depth to print when summarizing payload shapes. Defaults to 4.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        sample_limit = options["sample_limit"]
        issue_id = options["issue_id"]
        volume_id = options["volume_id"]
        save_json = options["save_json"]
        output_dir = Path(options["output_dir"])
        max_depth = options["max_depth"]

        validate_options(
            sample_limit=sample_limit,
            max_depth=max_depth,
        )

        if save_json:
            output_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comic Vine payload inspector"))
        self.stdout.write("No database changes will be made.")
        self.stdout.write("Requests are intentionally made without field_list.")
        self.stdout.write(f"List sample limit: {sample_limit}")

        if sample_limit > 0:
            issue_list_data = fetch_comicvine_json(
                url=ISSUES_URL,
                api_key=api_key,
                params={
                    "limit": sample_limit,
                    "sort": "date_added:desc",
                },
            )

            inspect_response(
                command=self,
                label="Issue list endpoint",
                data=issue_list_data,
                max_depth=max_depth,
            )

            if save_json:
                save_payload(
                    output_dir=output_dir,
                    filename="issue_list_sample.json",
                    data=issue_list_data,
                )

            volume_list_data = fetch_comicvine_json(
                url=VOLUMES_URL,
                api_key=api_key,
                params={
                    "limit": sample_limit,
                    "sort": "date_last_updated:desc",
                },
            )

            inspect_response(
                command=self,
                label="Volume list endpoint",
                data=volume_list_data,
                max_depth=max_depth,
            )

            if save_json:
                save_payload(
                    output_dir=output_dir,
                    filename="volume_list_sample.json",
                    data=volume_list_data,
                )

        if issue_id:
            issue_detail_data = fetch_comicvine_json(
                url=ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_id),
                api_key=api_key,
                params={},
            )

            inspect_response(
                command=self,
                label=f"Issue detail endpoint for issue {issue_id}",
                data=issue_detail_data,
                max_depth=max_depth,
            )

            if save_json:
                save_payload(
                    output_dir=output_dir,
                    filename=f"issue_detail_{issue_id}.json",
                    data=issue_detail_data,
                )

        if volume_id:
            volume_detail_data = fetch_comicvine_json(
                url=VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_id),
                api_key=api_key,
                params={},
            )

            inspect_response(
                command=self,
                label=f"Volume detail endpoint for volume {volume_id}",
                data=volume_detail_data,
                max_depth=max_depth,
            )

            if save_json:
                save_payload(
                    output_dir=output_dir,
                    filename=f"volume_detail_{volume_id}.json",
                    data=volume_detail_data,
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Payload inspection finished."))

        if save_json:
            self.stdout.write(f"Raw JSON files saved in: {output_dir}")


def validate_options(sample_limit, max_depth):
    if sample_limit < 0:
        raise CommandError("sample-limit cannot be negative.")

    if sample_limit > 10:
        raise CommandError(
            "sample-limit cannot be above 10. This command is for inspection, not importing."
        )

    if max_depth < 1:
        raise CommandError("max-depth must be at least 1.")


def fetch_comicvine_json(url, api_key, params):
    request_params = {
        "api_key": api_key,
        "format": "json",
        **params,
    }

    headers = {
        "User-Agent": USER_AGENT,
    }

    response = requests.get(
        url,
        params=request_params,
        headers=headers,
        timeout=30,
    )

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


def inspect_response(command, label, data, max_depth):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS(label))

    command.stdout.write("")
    command.stdout.write("Top-level response fields:")
    print_mapping_shape(
        command=command,
        value=data,
        indent_level=1,
        max_depth=1,
    )

    results = data.get("results")

    command.stdout.write("")
    command.stdout.write("Results shape:")

    if isinstance(results, list):
        command.stdout.write(f"  results: list[{len(results)}]")

        if results:
            command.stdout.write("")
            command.stdout.write("First result fields:")
            print_mapping_shape(
                command=command,
                value=results[0],
                indent_level=1,
                max_depth=max_depth,
            )
        else:
            command.stdout.write("  No result records returned.")

    elif isinstance(results, dict):
        command.stdout.write("  results: object")
        command.stdout.write("")
        command.stdout.write("Result fields:")
        print_mapping_shape(
            command=command,
            value=results,
            indent_level=1,
            max_depth=max_depth,
        )

    else:
        command.stdout.write(f"  results: {describe_value(results)}")


def print_mapping_shape(command, value, indent_level, max_depth):
    indent = "  " * indent_level

    if not isinstance(value, dict):
        command.stdout.write(f"{indent}{describe_value(value)}")
        return

    if max_depth < 1:
        command.stdout.write(f"{indent}...")
        return

    for key in sorted(value.keys()):
        item = value[key]
        command.stdout.write(f"{indent}{key}: {describe_value(item)}")

        if isinstance(item, dict):
            print_mapping_shape(
                command=command,
                value=item,
                indent_level=indent_level + 1,
                max_depth=max_depth - 1,
            )

        elif isinstance(item, list) and item:
            first_item = item[0]

            if isinstance(first_item, dict):
                command.stdout.write(f"{indent}  first item:")
                print_mapping_shape(
                    command=command,
                    value=first_item,
                    indent_level=indent_level + 2,
                    max_depth=max_depth - 1,
                )


def describe_value(value):
    if value is None:
        return "null"

    if isinstance(value, bool):
        return "bool"

    if isinstance(value, int):
        return "int"

    if isinstance(value, float):
        return "float"

    if isinstance(value, str):
        if value == "":
            return "str(empty)"
        return "str"

    if isinstance(value, dict):
        return f"object[{len(value)} keys]"

    if isinstance(value, list):
        if not value:
            return "list[0]"

        item_types = sorted({type(item).__name__ for item in value})
        return f"list[{len(value)}] of {', '.join(item_types)}"

    return type(value).__name__


def save_payload(output_dir, filename, data):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"{timestamp}_{filename}"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)