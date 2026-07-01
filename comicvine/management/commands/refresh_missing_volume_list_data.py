import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from requests.exceptions import RequestException

from comicvine.api.client import (
    ComicVineAPIError,
    create_comicvine_session,
    fetch_volumes_by_ids,
    get_comicvine_api_key,
)
from comicvine.api.fields import VOLUME_LIST_FIELDS
from comicvine.api.parsing import clean_text
from comicvine.models import ComicVineVolume
from comicvine.services.sync.volumes import (
    build_volume_list_data,
    chunk_list,
    get_volume_list_update_fields,
    get_volumes_needing_list_data_refresh_queryset,
    save_volume_list_data,
)


USER_AGENT = "EzyReadComics refresh_missing_volume_list_data"

DEFAULT_API_ERROR_RETRY_DELAY = 90 * 60


class Command(BaseCommand):
    help = "Refresh Comic Vine volume list data using batched /volumes/ requests."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Comic Vine volume batch size. Defaults to 100. Maximum is 100.",
        )

        parser.add_argument(
            "--max-batches",
            type=int,
            default=None,
            help=(
                "Optional maximum batches to fetch this run. "
                "If omitted during a real run, all selected volumes are processed. "
                "Dry runs default to 1 batch."
            ),
        )

        parser.add_argument(
            "--volume-limit",
            type=int,
            default=None,
            help="Optional maximum number of local volumes to select.",
        )

        parser.add_argument(
            "--volume-ids",
            help=(
                "Optional comma-separated Comic Vine volume IDs to refresh directly. "
                "Example: --volume-ids 158814,40550"
            ),
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=3.0,
            help="Seconds to wait between successful volume batches. Defaults to 3.",
        )

        parser.add_argument(
            "--api-error-retry-delay",
            type=float,
            default=DEFAULT_API_ERROR_RETRY_DELAY,
            help=(
                "Seconds to pause after a Comic Vine/API/web error before retrying. "
                "Defaults to 5400 seconds, which is 90 minutes."
            ),
        )

        parser.add_argument(
            "--stop-on-api-error",
            action="store_true",
            help=(
                "Stop immediately on a Comic Vine/API/web error instead of pausing "
                "and retrying. Dry runs always behave this way."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and summarize what would happen without writing to the database.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        max_batches = options["max_batches"]
        volume_limit = options["volume_limit"]
        volume_ids = parse_volume_ids(options["volume_ids"])
        request_delay = options["request_delay"]
        api_error_retry_delay = options["api_error_retry_delay"]
        dry_run = options["dry_run"]

        stop_on_api_error = options["stop_on_api_error"] or dry_run

        if dry_run and max_batches is None:
            max_batches = 1

        validate_command_options(
            batch_size=batch_size,
            max_batches=max_batches,
            volume_limit=volume_limit,
            request_delay=request_delay,
            api_error_retry_delay=api_error_retry_delay,
        )

        api_key = get_comicvine_api_key()

        close_old_connections()

        local_volumes = get_selected_volumes(
            volume_ids=volume_ids,
            volume_limit=volume_limit,
        )

        matching_count = get_matching_volume_count(volume_ids=volume_ids)
        batches = chunk_list(local_volumes, batch_size)

        if max_batches is not None:
            batches = batches[:max_batches]

        selected_this_run = sum(len(batch) for batch in batches)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Refresh Comic Vine volume data"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")

        if volume_ids:
            self.stdout.write(f"Volume source: specific IDs ({len(volume_ids)})")
        else:
            self.stdout.write("Volume source: volumes needing list-data refresh")

        self.stdout.write(f"Volumes matching selection: {matching_count}")
        self.stdout.write(f"Volumes selected this run: {selected_this_run}")
        self.stdout.write(f"Batch size: {batch_size}")

        if max_batches is None:
            self.stdout.write("Batch cap: no limit")
        else:
            self.stdout.write(f"Batch cap: {max_batches}")

        if stop_on_api_error:
            self.stdout.write("API/web error handling: stop immediately")
        else:
            self.stdout.write(
                f"API/web error handling: pause {api_error_retry_delay} seconds, then retry"
            )

        if not batches:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("No volumes selected."))
            return

        total_result = build_empty_result()
        stopped_by_api_error = False
        api_errors_seen = 0
        api_error_retries = 0
        batch_index = 0

        with create_comicvine_session(USER_AGENT) as session:
            while batch_index < len(batches):
                close_old_connections()

                local_volume_batch = batches[batch_index]
                batch_number = batch_index + 1

                if batch_number > 1:
                    sleep_if_needed(request_delay)

                self.stdout.write("")
                self.stdout.write("=" * 80)
                self.stdout.write(f"Volume batch {batch_number} of {len(batches)}")
                self.stdout.write(f"Volumes in batch: {len(local_volume_batch)}")
                self.stdout.write("=" * 80)

                try:
                    batch_result, item_results = process_volume_batch(
                        session=session,
                        api_key=api_key,
                        local_volume_batch=local_volume_batch,
                        dry_run=dry_run,
                    )
                except (ComicVineAPIError, RequestException) as error:
                    api_errors_seen += 1

                    self.stdout.write("")
                    self.stdout.write(self.style.ERROR("Comic Vine/API/web error."))
                    self.stdout.write(str(error))
                    self.stdout.write("")

                    if stop_on_api_error:
                        stopped_by_api_error = True
                        self.stdout.write(
                            "Progress from completed batches was saved. "
                            "The current batch was not marked complete. "
                            "Run this command again later to continue."
                        )
                        break

                    api_error_retries += 1

                    self.stdout.write(
                        "Progress from completed batches was saved. "
                        "The current batch was not marked complete."
                    )
                    self.stdout.write(
                        f"Pausing for {format_seconds(api_error_retry_delay)} before retrying "
                        f"volume batch {batch_number}."
                    )

                    sleep_if_needed(api_error_retry_delay)

                    self.stdout.write("")
                    self.stdout.write(
                        self.style.WARNING(
                            "Retrying after API/web error. Press Ctrl+C to stop the command."
                        )
                    )

                    continue

                merge_result(total_result, batch_result)

                print_volume_items(
                    command=self,
                    item_results=item_results,
                    dry_run=dry_run,
                )

                print_batch_summary(
                    command=self,
                    result=batch_result,
                    dry_run=dry_run,
                )

                batch_index += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Run complete."))
        print_total_summary(
            command=self,
            result=total_result,
            dry_run=dry_run,
        )
        self.stdout.write(f"API/web errors seen: {api_errors_seen}")
        self.stdout.write(f"API/web error retries: {api_error_retries}")

        if dry_run:
            self.stdout.write("Dry run only. No database changes were saved.")
        elif stopped_by_api_error:
            self.stdout.write("Stopped early because Comic Vine returned an API/web error.")
        elif max_batches is not None and len(batches) >= max_batches:
            self.stdout.write("Stopped at the batch cap. Run again to continue.")
        else:
            close_old_connections()
            remaining_count = get_matching_volume_count(volume_ids=volume_ids)

            if volume_ids:
                self.stdout.write("Finished the selected volume IDs.")
            else:
                self.stdout.write(f"Volumes still needing list-data refresh: {remaining_count}")


def get_selected_volumes(*, volume_ids, volume_limit):
    if volume_ids:
        queryset = ComicVineVolume.objects.filter(comicvine_id__in=volume_ids).order_by("id")
    else:
        queryset = get_volumes_needing_list_data_refresh_queryset()

    if volume_limit is not None:
        queryset = queryset[:volume_limit]

    return list(queryset)


def get_matching_volume_count(*, volume_ids):
    if volume_ids:
        return ComicVineVolume.objects.filter(comicvine_id__in=volume_ids).count()

    return get_volumes_needing_list_data_refresh_queryset().count()


def process_volume_batch(*, session, api_key, local_volume_batch, dry_run):
    result = build_empty_result()
    item_results = []

    local_volumes_by_comicvine_id = {
        local_volume.comicvine_id: local_volume
        for local_volume in local_volume_batch
    }

    requested_volume_ids = list(local_volumes_by_comicvine_id.keys())

    response_data = fetch_volumes_by_ids(
        session,
        api_key,
        volume_ids=requested_volume_ids,
        fields=VOLUME_LIST_FIELDS,
    )

    result["api_requests_made"] += 1

    remote_volumes = response_data.get("results") or []
    remote_volumes_by_comicvine_id = {
        remote_volume.get("id"): remote_volume
        for remote_volume in remote_volumes
        if remote_volume.get("id")
    }

    result["volumes_returned_by_comicvine"] += len(remote_volumes_by_comicvine_id)

    unexpected_ids = sorted(
        set(remote_volumes_by_comicvine_id.keys()) - set(requested_volume_ids)
    )

    result["unexpected_volumes_returned"] += len(unexpected_ids)

    for local_volume in local_volume_batch:
        result["volumes_checked"] += 1

        remote_volume = remote_volumes_by_comicvine_id.get(local_volume.comicvine_id)

        if not remote_volume:
            result["volumes_not_returned_by_comicvine"] += 1
            item_results.append(
                {
                    "action": "not_returned",
                    "local_volume": local_volume,
                    "remote_volume": None,
                    "update_fields": [],
                }
            )
            continue

        volume_data = build_volume_list_data(remote_volume)
        update_fields = get_volume_list_update_fields(
            local_volume=local_volume,
            volume_data=volume_data,
            overwrite_existing=False,
        )

        if dry_run:
            saved_update_fields = update_fields
        else:
            _action, _volume, saved_update_fields = save_volume_list_data(
                remote_volume,
                overwrite_existing=False,
                dry_run=False,
            )

        if saved_update_fields:
            result["volumes_updated"] += 1
            record_field_updates(result, saved_update_fields)
            item_action = "updated"
        else:
            result["volumes_refreshed"] += 1
            item_action = "refreshed"

        item_results.append(
            {
                "action": item_action,
                "local_volume": local_volume,
                "remote_volume": remote_volume,
                "update_fields": saved_update_fields,
            }
        )

    return result, item_results


def build_empty_result():
    return {
        "api_requests_made": 0,
        "volumes_checked": 0,
        "volumes_returned_by_comicvine": 0,
        "volumes_updated": 0,
        "volumes_refreshed": 0,
        "volumes_not_returned_by_comicvine": 0,
        "unexpected_volumes_returned": 0,
        "field_update_counts": {},
    }


def merge_result(total_result, batch_result):
    for key, value in batch_result.items():
        if key == "field_update_counts":
            for field_name, count in value.items():
                total_result[key][field_name] = total_result[key].get(field_name, 0) + count
        else:
            total_result[key] += value


def record_field_updates(result, update_fields):
    for field_name in update_fields:
        result["field_update_counts"][field_name] = (
            result["field_update_counts"].get(field_name, 0) + 1
        )


def print_volume_items(*, command, item_results, dry_run):
    command.stdout.write("")
    command.stdout.write("Volumes returned:")

    if not item_results:
        command.stdout.write("  None")
        return

    for item_result in item_results:
        action = format_action(item_result["action"], dry_run=dry_run)
        line = format_volume_line(item_result)
        command.stdout.write(f"  {action} {line}")


def format_action(action, *, dry_run):
    if dry_run:
        if action == "updated":
            return "[WOULD UPDATE]"
        if action == "refreshed":
            return "[WOULD REFRESH]"
        if action == "not_returned":
            return "[NOT RETURNED]"
        return "[WOULD SKIP]"

    if action == "updated":
        return "[UPDATED]"
    if action == "refreshed":
        return "[REFRESHED]"
    if action == "not_returned":
        return "[NOT RETURNED]"
    return "[SKIPPED]"


def format_volume_line(item_result):
    local_volume = item_result["local_volume"]
    remote_volume = item_result["remote_volume"]
    update_fields = item_result["update_fields"]

    if remote_volume:
        volume_name = clean_text(remote_volume.get("name")) or local_volume.name
        publisher = clean_text((remote_volume.get("publisher") or {}).get("name"))
        start_year = clean_text(remote_volume.get("start_year"))
        count_of_issues = remote_volume.get("count_of_issues")
    else:
        volume_name = local_volume.name
        publisher = local_volume.publisher
        start_year = local_volume.start_year
        count_of_issues = local_volume.count_of_issues

    details = []

    if publisher:
        details.append(f"publisher {publisher}")

    if start_year:
        details.append(f"start {start_year}")

    if count_of_issues is not None:
        details.append(f"{count_of_issues} issues")

    details_text = ", ".join(details) if details else "no extra summary data"

    if update_fields:
        update_text = f"; filled {len(update_fields)} fields"
    else:
        update_text = ""

    return (
        f"{volume_name} "
        f"(volume {local_volume.comicvine_id}, {details_text}{update_text})"
    )


def print_batch_summary(*, command, result, dry_run):
    prefix = "Would " if dry_run else ""

    command.stdout.write("")
    command.stdout.write("Batch summary:")
    command.stdout.write(f"  API requests made: {result['api_requests_made']}")
    command.stdout.write(f"  Volumes checked: {result['volumes_checked']}")
    command.stdout.write(f"  Volumes returned by Comic Vine: {result['volumes_returned_by_comicvine']}")
    command.stdout.write(f"  {prefix}volumes updated: {result['volumes_updated']}")
    command.stdout.write(f"  {prefix}volumes refreshed with no data changes: {result['volumes_refreshed']}")
    command.stdout.write(f"  Volumes not returned by Comic Vine: {result['volumes_not_returned_by_comicvine']}")

    if result["unexpected_volumes_returned"]:
        command.stdout.write(
            f"  Unexpected volumes returned: {result['unexpected_volumes_returned']}"
        )


def print_total_summary(*, command, result, dry_run):
    prefix = "Would " if dry_run else ""

    command.stdout.write("Total summary:")
    command.stdout.write(f"  API requests made: {result['api_requests_made']}")
    command.stdout.write(f"  Volumes checked: {result['volumes_checked']}")
    command.stdout.write(f"  Volumes returned by Comic Vine: {result['volumes_returned_by_comicvine']}")
    command.stdout.write(f"  {prefix}volumes updated: {result['volumes_updated']}")
    command.stdout.write(f"  {prefix}volumes refreshed with no data changes: {result['volumes_refreshed']}")
    command.stdout.write(f"  Volumes not returned by Comic Vine: {result['volumes_not_returned_by_comicvine']}")

    if result["unexpected_volumes_returned"]:
        command.stdout.write(
            f"  Unexpected volumes returned: {result['unexpected_volumes_returned']}"
        )

    if result["field_update_counts"]:
        command.stdout.write("")
        command.stdout.write("Field update counts:")

        for field_name, count in sorted(result["field_update_counts"].items()):
            command.stdout.write(f"  {field_name}: {count}")


def parse_volume_ids(raw_value):
    if not raw_value:
        return []

    volume_ids = []

    for raw_id in raw_value.split(","):
        raw_id = raw_id.strip()

        if not raw_id:
            continue

        try:
            volume_id = int(raw_id)
        except ValueError as error:
            raise CommandError(f"Invalid volume ID: {raw_id}") from error

        if volume_id < 1:
            raise CommandError(f"Volume ID must be greater than 0: {volume_id}")

        volume_ids.append(volume_id)

    return volume_ids


def validate_command_options(
    *,
    batch_size,
    max_batches,
    volume_limit,
    request_delay,
    api_error_retry_delay,
):
    if batch_size < 1:
        raise CommandError("--batch-size must be at least 1.")

    if batch_size > 100:
        raise CommandError("--batch-size cannot be above 100.")

    if max_batches is not None and max_batches < 1:
        raise CommandError("--max-batches must be at least 1 when provided.")

    if volume_limit is not None and volume_limit < 1:
        raise CommandError("--volume-limit must be at least 1 when provided.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")

    if api_error_retry_delay < 0:
        raise CommandError("--api-error-retry-delay cannot be negative.")


def format_seconds(seconds):
    seconds = int(seconds)
    minutes = seconds // 60

    if seconds == DEFAULT_API_ERROR_RETRY_DELAY:
        return "90 minutes"

    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"

    if seconds % 60 == 0:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    return f"{seconds} seconds"


def sleep_if_needed(delay):
    if delay > 0:
        time.sleep(delay)

    close_old_connections()