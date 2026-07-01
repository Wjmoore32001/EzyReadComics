import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, transaction
from django.db.models import F, Q
from django.utils import timezone
from requests.exceptions import RequestException

from comics.comicvine.client import (
    ComicVineAPIError,
    create_comicvine_session,
    fetch_volume_detail,
    get_comicvine_api_key,
)
from comics.comicvine.fields import VOLUME_DETAIL_FIELDS
from comics.comicvine.parsing import to_optional_int
from comics.importers.credits import sync_volume_person_credits
from comics.importers.volumes import save_volume_list_data
from comics.models import ComicVolume


USER_AGENT = "EzyReadComics bulk_hydrate_volume_details"

DEFAULT_API_ERROR_RETRY_DELAY = 90 * 60

EXPECTED_DETAIL_SYNC_FIELDS = ["people"]


class Command(BaseCommand):
    help = (
        "Hydrate local Comic Vine volume details. "
        "One Comic Vine /volume/ detail call per local volume. "
        "Stores volume list updates and volume people."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--volume-id",
            type=int,
            action="append",
            dest="volume_ids",
            help=(
                "Plain Comic Vine volume ID to hydrate. "
                "Can be used multiple times. If omitted, hydrates volumes needing detail hydration."
            ),
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help=(
                "Maximum number of volumes to process this run. "
                "Dry runs default to 1 if no limit is provided."
            ),
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=3.0,
            help="Seconds to wait between successful detail API calls. Defaults to 3.",
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
        volume_ids = options["volume_ids"] or []
        limit = options["limit"]
        request_delay = options["request_delay"]
        api_error_retry_delay = options["api_error_retry_delay"]
        dry_run = options["dry_run"]

        # Dry runs should never trap you in a 90-minute retry pause.
        stop_on_api_error = options["stop_on_api_error"] or dry_run

        if dry_run and limit is None and not volume_ids:
            limit = 1

        validate_options(
            volume_ids=volume_ids,
            limit=limit,
            request_delay=request_delay,
            api_error_retry_delay=api_error_retry_delay,
        )

        close_old_connections()

        volumes, matching_count = select_volumes_to_hydrate(
            volume_ids=volume_ids,
            limit=limit,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Bulk hydrate Comic Vine volume details"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")

        if volume_ids:
            self.stdout.write(f"Target volume IDs: {', '.join(str(volume_id) for volume_id in volume_ids)}")
        else:
            self.stdout.write("Selection: local volumes needing detail hydration")

        self.stdout.write(f"Volumes matching selection: {matching_count}")
        self.stdout.write(f"Volumes selected this run: {len(volumes)}")

        if stop_on_api_error:
            self.stdout.write("API/web error handling: stop immediately")
        else:
            self.stdout.write(
                f"API/web error handling: pause {api_error_retry_delay} seconds, then retry"
            )

        if not volumes:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("No volumes selected."))
            return

        api_key = get_comicvine_api_key()
        run_result = build_empty_run_result()

        with create_comicvine_session(USER_AGENT) as session:
            volume_index = 0

            while volume_index < len(volumes):
                close_old_connections()

                volume = volumes[volume_index]
                volume_number_in_run = volume_index + 1

                if volume_number_in_run > 1:
                    sleep_if_needed(request_delay)

                self.stdout.write("")
                self.stdout.write("=" * 80)
                self.stdout.write(f"Volume {volume_number_in_run} of {len(volumes)}")
                self.stdout.write(format_volume_line(volume))
                self.stdout.write("=" * 80)

                try:
                    item_result = hydrate_single_volume_detail(
                        session=session,
                        api_key=api_key,
                        volume=volume,
                        dry_run=dry_run,
                    )
                except (ComicVineAPIError, RequestException) as error:
                    run_result["api_errors_seen"] += 1

                    self.stdout.write("")
                    self.stdout.write(self.style.ERROR("Comic Vine/API/web error."))
                    self.stdout.write(str(error))
                    self.stdout.write("")

                    if stop_on_api_error:
                        run_result["stopped_by_api_error"] = True
                        self.stdout.write(
                            "Progress from completed volumes was saved. "
                            "The current volume was not marked hydrated. "
                            "Run this command again later to continue."
                        )
                        break

                    run_result["api_error_retries"] += 1

                    self.stdout.write(
                        "Progress from completed volumes was saved. "
                        "The current volume was not marked hydrated."
                    )
                    self.stdout.write(
                        f"Pausing for {format_seconds(api_error_retry_delay)} before retrying "
                        f"{format_volume_line(volume)}."
                    )

                    sleep_if_needed(api_error_retry_delay)

                    self.stdout.write("")
                    self.stdout.write(
                        self.style.WARNING(
                            "Retrying after API/web error. Press Ctrl+C to stop the command."
                        )
                    )

                    # Do not advance volume_index. Retry the same volume.
                    continue

                record_volume_item_result(run_result, item_result)
                print_volume_item_result(
                    command=self,
                    item_result=item_result,
                    dry_run=dry_run,
                )

                volume_index += 1

        print_volume_run_summary(
            command=self,
            run_result=run_result,
            dry_run=dry_run,
        )


def select_volumes_to_hydrate(*, volume_ids, limit):
    if volume_ids:
        queryset = ComicVolume.objects.filter(
            comicvine_id__in=volume_ids,
        ).order_by("comicvine_id")
    else:
        queryset = get_volumes_needing_detail_hydration_queryset()

    matching_count = queryset.count()

    if limit is not None:
        queryset = queryset[:limit]

    return list(queryset), matching_count


def get_volumes_needing_detail_hydration_queryset():
    needs_hydration_filter = (
        Q(detail_hydrated_at__isnull=True)
        | Q(date_last_updated__gt=F("detail_hydrated_at"))
    )

    return (
        ComicVolume.objects.filter(comicvine_id__isnull=False)
        .filter(needs_hydration_filter)
        .order_by("id")
    )


def hydrate_single_volume_detail(*, session, api_key, volume, dry_run):
    response_data = fetch_volume_detail(
        session,
        api_key,
        volume_id=volume.comicvine_id,
        fields=VOLUME_DETAIL_FIELDS,
    )

    remote_volume_detail = get_detail_result(response_data, label="volume")
    remote_volume_id = to_optional_int(remote_volume_detail.get("id"))

    if remote_volume_id != volume.comicvine_id:
        raise ComicVineAPIError(
            f"Comic Vine returned volume id {remote_volume_id}, "
            f"but local volume expected {volume.comicvine_id}."
        )

    return save_volume_detail_data(
        volume=volume,
        remote_volume_detail=remote_volume_detail,
        dry_run=dry_run,
    )


def save_volume_detail_data(*, volume, remote_volume_detail, dry_run):
    remote_people = get_remote_list_for_exact_sync(remote_volume_detail, "people")
    missing_or_malformed_fields = get_missing_or_malformed_detail_sync_fields(
        remote_volume_detail
    )

    if dry_run:
        list_action, _saved_volume, list_update_fields = save_volume_list_data(
            remote_volume_detail,
            overwrite_existing=True,
            dry_run=True,
        )

        people_result = sync_volume_person_credits(
            volume,
            remote_people,
            dry_run=True,
        )

        return {
            "action": "hydrated",
            "volume": volume,
            "list_action": list_action,
            "list_update_fields": list_update_fields,
            "people_result": people_result,
            "missing_or_malformed_fields": missing_or_malformed_fields,
            "marked_hydrated": False,
        }

    with transaction.atomic():
        locked_volume = ComicVolume.objects.select_for_update().get(id=volume.id)

        list_action, saved_volume, list_update_fields = save_volume_list_data(
            remote_volume_detail,
            overwrite_existing=True,
            dry_run=False,
        )

        if saved_volume is None:
            locked_volume.detail_hydration_attempted_at = timezone.now()
            locked_volume.save(update_fields=["detail_hydration_attempted_at"])

            return {
                "action": "skipped",
                "volume": locked_volume,
                "list_action": list_action,
                "list_update_fields": list_update_fields,
                "people_result": None,
                "missing_or_malformed_fields": missing_or_malformed_fields,
                "marked_hydrated": False,
            }

        people_result = sync_volume_person_credits(
            saved_volume,
            remote_people,
            dry_run=False,
        )

        now = timezone.now()
        saved_volume.detail_hydration_attempted_at = now

        update_fields = ["detail_hydration_attempted_at"]
        marked_hydrated = False

        if not missing_or_malformed_fields:
            saved_volume.detail_hydrated_at = now
            update_fields.append("detail_hydrated_at")
            marked_hydrated = True

        saved_volume.save(update_fields=update_fields)

    return {
        "action": "hydrated",
        "volume": saved_volume,
        "list_action": list_action,
        "list_update_fields": list_update_fields,
        "people_result": people_result,
        "missing_or_malformed_fields": missing_or_malformed_fields,
        "marked_hydrated": marked_hydrated,
    }


def get_detail_result(response_data, *, label):
    remote_detail = response_data.get("results")

    if not isinstance(remote_detail, dict):
        raise ComicVineAPIError(
            f"Comic Vine {label} detail response did not contain a result object."
        )

    return remote_detail


def get_remote_list_for_exact_sync(remote_detail, field_name):
    if field_name not in remote_detail:
        return None

    value = remote_detail.get(field_name)

    if value is None:
        return []

    if isinstance(value, list):
        return value

    return None


def get_missing_or_malformed_detail_sync_fields(remote_detail):
    missing_or_malformed_fields = []

    for field_name in EXPECTED_DETAIL_SYNC_FIELDS:
        if field_name not in remote_detail:
            missing_or_malformed_fields.append(field_name)
            continue

        value = remote_detail.get(field_name)

        if value is not None and not isinstance(value, list):
            missing_or_malformed_fields.append(field_name)

    return missing_or_malformed_fields


def build_empty_run_result():
    return {
        "items_seen": 0,
        "items_hydrated": 0,
        "items_marked_hydrated": 0,
        "items_not_marked_hydrated": 0,
        "items_skipped": 0,
        "list_created": 0,
        "list_updated": 0,
        "list_unchanged": 0,
        "list_skipped": 0,
        "volume_fields_updated": {},
        "missing_or_malformed_fields": {},
        "people": {
            "remote_items_seen": 0,
            "people_created": 0,
            "people_updated": 0,
            "roles_created": 0,
            "credits_created": 0,
            "credits_deleted": 0,
            "credits_kept": 0,
            "skipped_items": 0,
            "missing_remote_fields_skipped": 0,
        },
        "stopped_by_api_error": False,
        "api_errors_seen": 0,
        "api_error_retries": 0,
    }


def record_volume_item_result(run_result, item_result):
    run_result["items_seen"] += 1

    if item_result["action"] == "hydrated":
        run_result["items_hydrated"] += 1
    else:
        run_result["items_skipped"] += 1

    if item_result["marked_hydrated"]:
        run_result["items_marked_hydrated"] += 1
    else:
        run_result["items_not_marked_hydrated"] += 1

    list_action = item_result["list_action"]

    if list_action == "created":
        run_result["list_created"] += 1
    elif list_action == "updated":
        run_result["list_updated"] += 1
    elif list_action == "unchanged":
        run_result["list_unchanged"] += 1
    else:
        run_result["list_skipped"] += 1

    for field_name in item_result["list_update_fields"]:
        run_result["volume_fields_updated"][field_name] = (
            run_result["volume_fields_updated"].get(field_name, 0) + 1
        )

    for field_name in item_result["missing_or_malformed_fields"]:
        run_result["missing_or_malformed_fields"][field_name] = (
            run_result["missing_or_malformed_fields"].get(field_name, 0) + 1
        )

    merge_people_result(run_result["people"], item_result["people_result"])


def merge_people_result(target, source):
    if source is None:
        return

    for field_name in target.keys():
        target[field_name] += getattr(source, field_name)


def print_volume_item_result(*, command, item_result, dry_run):
    if item_result["action"] == "hydrated":
        action = "[WOULD HYDRATE]" if dry_run else "[HYDRATED]"
    else:
        action = "[WOULD SKIP]" if dry_run else "[SKIPPED]"

    command.stdout.write(f"{action} {format_volume_line(item_result['volume'])}")
    command.stdout.write(f"  Volume list action: {format_list_action(item_result['list_action'], dry_run=dry_run)}")

    if item_result["marked_hydrated"]:
        command.stdout.write("  Detail hydration marker: marked hydrated")
    elif item_result["missing_or_malformed_fields"]:
        command.stdout.write(
            "  Detail hydration marker: attempted only; missing/malformed fields: "
            f"{', '.join(item_result['missing_or_malformed_fields'])}"
        )
    else:
        command.stdout.write("  Detail hydration marker: not changed in dry run")

    if item_result["list_update_fields"]:
        command.stdout.write(
            f"  Volume fields updated: {', '.join(item_result['list_update_fields'])}"
        )

    people_result = item_result["people_result"]

    if people_result:
        command.stdout.write(
            "  Volume people: "
            f"remote {people_result.remote_items_seen}, "
            f"created {people_result.credits_created}, "
            f"deleted {people_result.credits_deleted}, "
            f"kept {people_result.credits_kept}, "
            f"people created {people_result.people_created}, "
            f"people updated {people_result.people_updated}, "
            f"skipped {people_result.skipped_items}, "
            f"missing fields skipped {people_result.missing_remote_fields_skipped}"
        )


def print_volume_run_summary(*, command, run_result, dry_run):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Run summary:"))
    command.stdout.write(f"  Volumes processed: {run_result['items_seen']}")
    command.stdout.write(f"  Volumes hydrated: {run_result['items_hydrated']}")
    command.stdout.write(f"  Volumes marked hydrated: {run_result['items_marked_hydrated']}")
    command.stdout.write(f"  Volumes attempted but not marked hydrated: {run_result['items_not_marked_hydrated']}")
    command.stdout.write(f"  Volumes skipped: {run_result['items_skipped']}")
    command.stdout.write(f"  API/web errors seen: {run_result['api_errors_seen']}")
    command.stdout.write(f"  API/web error retries: {run_result['api_error_retries']}")
    command.stdout.write(f"  Volume list created: {run_result['list_created']}")
    command.stdout.write(f"  Volume list updated: {run_result['list_updated']}")
    command.stdout.write(f"  Volume list unchanged: {run_result['list_unchanged']}")
    command.stdout.write(f"  Volume list skipped: {run_result['list_skipped']}")

    if run_result["volume_fields_updated"]:
        command.stdout.write("  Volume field update counts:")

        for field_name, count in sorted(run_result["volume_fields_updated"].items()):
            command.stdout.write(f"    {field_name}: {count}")

    if run_result["missing_or_malformed_fields"]:
        command.stdout.write("")
        command.stdout.write("  Missing or malformed detail fields:")

        for field_name, count in sorted(run_result["missing_or_malformed_fields"].items()):
            command.stdout.write(f"    {field_name}: {count}")

    people = run_result["people"]

    command.stdout.write("")
    command.stdout.write("  Volume people:")
    command.stdout.write(f"    Remote items seen: {people['remote_items_seen']}")
    command.stdout.write(f"    People created: {people['people_created']}")
    command.stdout.write(f"    People updated: {people['people_updated']}")
    command.stdout.write(f"    Credits created: {people['credits_created']}")
    command.stdout.write(f"    Credits deleted: {people['credits_deleted']}")
    command.stdout.write(f"    Credits kept: {people['credits_kept']}")
    command.stdout.write(f"    Skipped items: {people['skipped_items']}")
    command.stdout.write(f"    Missing remote fields skipped: {people['missing_remote_fields_skipped']}")

    command.stdout.write("")

    if dry_run:
        command.stdout.write("Dry run only. No database changes were saved.")
    elif run_result["stopped_by_api_error"]:
        command.stdout.write("Stopped early because Comic Vine returned an API/web error.")
    else:
        command.stdout.write("Volume detail hydration run completed.")


def format_volume_line(volume):
    publisher = f", {volume.publisher}" if volume.publisher else ""
    return f"{volume.name}{publisher} (volume {volume.comicvine_id})"


def format_list_action(action, *, dry_run):
    if dry_run:
        if action == "created":
            return "would create"
        if action == "updated":
            return "would update"
        if action == "unchanged":
            return "would stay unchanged"
        return "would skip"

    return action


def validate_options(*, volume_ids, limit, request_delay, api_error_retry_delay):
    if limit is not None and limit < 1:
        raise CommandError("--limit must be at least 1 when provided.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")

    if api_error_retry_delay < 0:
        raise CommandError("--api-error-retry-delay cannot be negative.")

    for volume_id in volume_ids:
        if volume_id < 1:
            raise CommandError("--volume-id must be greater than 0.")


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