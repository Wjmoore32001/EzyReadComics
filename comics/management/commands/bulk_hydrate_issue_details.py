import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, transaction
from django.db.models import F, Q
from django.utils import timezone
from requests.exceptions import RequestException

from comics.comicvine.client import (
    ComicVineAPIError,
    create_comicvine_session,
    fetch_issue_detail,
    get_comicvine_api_key,
)
from comics.comicvine.fields import ISSUE_DETAIL_FIELDS, ISSUE_DETAIL_RELATIONSHIP_FIELDS
from comics.comicvine.parsing import to_optional_int
from comics.importers.credits import sync_issue_person_credits
from comics.importers.issues import save_issue_list_data
from comics.importers.relationships import sync_issue_relationships
from comics.models import ComicIssue


USER_AGENT = "EzyReadComics bulk_hydrate_issue_details"

DEFAULT_API_ERROR_RETRY_DELAY = 90 * 60

EXPECTED_DETAIL_SYNC_FIELDS = sorted(
    set(ISSUE_DETAIL_RELATIONSHIP_FIELDS + ["associated_images"])
)


class Command(BaseCommand):
    help = (
        "Hydrate local Comic Vine issue details. "
        "One Comic Vine /issue/ detail call per local issue. "
        "Stores issue list updates, person credits, relationships, and associated images."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--issue-id",
            type=int,
            action="append",
            dest="issue_ids",
            help=(
                "Plain Comic Vine issue ID to hydrate. "
                "Can be used multiple times. If omitted, hydrates issues needing detail hydration."
            ),
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help=(
                "Maximum number of issues to process this run. "
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
        issue_ids = options["issue_ids"] or []
        limit = options["limit"]
        request_delay = options["request_delay"]
        api_error_retry_delay = options["api_error_retry_delay"]
        dry_run = options["dry_run"]

        # Dry runs should never trap you in a 90-minute retry pause.
        stop_on_api_error = options["stop_on_api_error"] or dry_run

        if dry_run and limit is None and not issue_ids:
            limit = 1

        validate_options(
            issue_ids=issue_ids,
            limit=limit,
            request_delay=request_delay,
            api_error_retry_delay=api_error_retry_delay,
        )

        close_old_connections()

        issues, matching_count = select_issues_to_hydrate(
            issue_ids=issue_ids,
            limit=limit,
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Bulk hydrate Comic Vine issue details"))
        self.stdout.write(f"Mode: {'dry run' if dry_run else 'writing to database'}")

        if issue_ids:
            self.stdout.write(f"Target issue IDs: {', '.join(str(issue_id) for issue_id in issue_ids)}")
        else:
            self.stdout.write("Selection: local issues needing detail hydration")

        self.stdout.write(f"Issues matching selection: {matching_count}")
        self.stdout.write(f"Issues selected this run: {len(issues)}")

        if stop_on_api_error:
            self.stdout.write("API/web error handling: stop immediately")
        else:
            self.stdout.write(
                f"API/web error handling: pause {api_error_retry_delay} seconds, then retry"
            )

        if not issues:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("No issues selected."))
            return

        api_key = get_comicvine_api_key()
        run_result = build_empty_run_result()

        with create_comicvine_session(USER_AGENT) as session:
            issue_index = 0

            while issue_index < len(issues):
                close_old_connections()

                issue = issues[issue_index]
                issue_number_in_run = issue_index + 1

                if issue_number_in_run > 1:
                    sleep_if_needed(request_delay)

                self.stdout.write("")
                self.stdout.write("=" * 80)
                self.stdout.write(f"Issue {issue_number_in_run} of {len(issues)}")
                self.stdout.write(format_issue_line(issue))
                self.stdout.write("=" * 80)

                try:
                    item_result = hydrate_single_issue_detail(
                        session=session,
                        api_key=api_key,
                        issue=issue,
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
                            "Progress from completed issues was saved. "
                            "The current issue was not marked hydrated. "
                            "Run this command again later to continue."
                        )
                        break

                    run_result["api_error_retries"] += 1

                    self.stdout.write(
                        "Progress from completed issues was saved. "
                        "The current issue was not marked hydrated."
                    )
                    self.stdout.write(
                        f"Pausing for {format_seconds(api_error_retry_delay)} before retrying "
                        f"{format_issue_line(issue)}."
                    )

                    sleep_if_needed(api_error_retry_delay)

                    self.stdout.write("")
                    self.stdout.write(
                        self.style.WARNING(
                            "Retrying after API/web error. Press Ctrl+C to stop the command."
                        )
                    )

                    # Do not advance issue_index. Retry the same issue.
                    continue

                record_issue_item_result(run_result, item_result)
                print_issue_item_result(
                    command=self,
                    item_result=item_result,
                    dry_run=dry_run,
                )

                issue_index += 1

        print_issue_run_summary(
            command=self,
            run_result=run_result,
            dry_run=dry_run,
        )


def select_issues_to_hydrate(*, issue_ids, limit):
    if issue_ids:
        queryset = ComicIssue.objects.filter(
            comicvine_id__in=issue_ids,
        ).select_related("volume").order_by("comicvine_id")
    else:
        queryset = get_issues_needing_detail_hydration_queryset().select_related("volume")

    matching_count = queryset.count()

    if limit is not None:
        queryset = queryset[:limit]

    return list(queryset), matching_count


def get_issues_needing_detail_hydration_queryset():
    needs_hydration_filter = (
        Q(detail_hydrated_at__isnull=True)
        | Q(date_last_updated__gt=F("detail_hydrated_at"))
    )

    return (
        ComicIssue.objects.filter(comicvine_id__isnull=False)
        .filter(needs_hydration_filter)
        .order_by("id")
    )


def hydrate_single_issue_detail(*, session, api_key, issue, dry_run):
    response_data = fetch_issue_detail(
        session,
        api_key,
        issue_id=issue.comicvine_id,
        fields=ISSUE_DETAIL_FIELDS,
    )

    remote_issue_detail = get_detail_result(response_data, label="issue")
    remote_issue_id = to_optional_int(remote_issue_detail.get("id"))

    if remote_issue_id != issue.comicvine_id:
        raise ComicVineAPIError(
            f"Comic Vine returned issue id {remote_issue_id}, "
            f"but local issue expected {issue.comicvine_id}."
        )

    return save_issue_detail_data(
        issue=issue,
        remote_issue_detail=remote_issue_detail,
        dry_run=dry_run,
    )


def save_issue_detail_data(*, issue, remote_issue_detail, dry_run):
    remote_issue_for_list_save = dict(remote_issue_detail)

    # Let sync_issue_relationships handle associated_images once.
    # save_issue_list_data can update normal issue fields without also
    # deleting/recreating associated images.
    remote_issue_for_list_save.pop("associated_images", None)

    remote_person_credits = get_remote_list_for_exact_sync(
        remote_issue_detail,
        "person_credits",
    )
    missing_or_malformed_fields = get_missing_or_malformed_detail_sync_fields(
        remote_issue_detail
    )

    if dry_run:
        (
            list_action,
            _saved_issue,
            list_update_fields,
            volume_created,
            volume_update_fields,
            _image_result,
        ) = save_issue_list_data(
            remote_issue_for_list_save,
            overwrite_existing=True,
            create_missing=False,
            dry_run=True,
        )

        credit_result = sync_issue_person_credits(
            issue,
            remote_person_credits,
            dry_run=True,
        )
        relationship_result = sync_issue_relationships(
            issue,
            remote_issue_detail,
            dry_run=True,
        )

        return {
            "action": "hydrated",
            "issue": issue,
            "list_action": list_action,
            "list_update_fields": list_update_fields,
            "volume_created": volume_created,
            "volume_update_fields": volume_update_fields,
            "credit_result": credit_result,
            "relationship_result": relationship_result,
            "missing_or_malformed_fields": missing_or_malformed_fields,
            "marked_hydrated": False,
        }

    with transaction.atomic():
        locked_issue = ComicIssue.objects.select_for_update().get(id=issue.id)

        (
            list_action,
            saved_issue,
            list_update_fields,
            volume_created,
            volume_update_fields,
            _image_result,
        ) = save_issue_list_data(
            remote_issue_for_list_save,
            overwrite_existing=True,
            create_missing=False,
            dry_run=False,
        )

        if saved_issue is None:
            locked_issue.detail_hydration_attempted_at = timezone.now()
            locked_issue.save(update_fields=["detail_hydration_attempted_at"])

            return {
                "action": "skipped",
                "issue": locked_issue,
                "list_action": list_action,
                "list_update_fields": list_update_fields,
                "volume_created": volume_created,
                "volume_update_fields": volume_update_fields,
                "credit_result": None,
                "relationship_result": None,
                "missing_or_malformed_fields": missing_or_malformed_fields,
                "marked_hydrated": False,
            }

        credit_result = sync_issue_person_credits(
            saved_issue,
            remote_person_credits,
            dry_run=False,
        )
        relationship_result = sync_issue_relationships(
            saved_issue,
            remote_issue_detail,
            dry_run=False,
        )

        now = timezone.now()
        saved_issue.detail_hydration_attempted_at = now

        update_fields = ["detail_hydration_attempted_at"]
        marked_hydrated = False

        if not missing_or_malformed_fields:
            saved_issue.detail_hydrated_at = now
            update_fields.append("detail_hydrated_at")
            marked_hydrated = True

        saved_issue.save(update_fields=update_fields)

    return {
        "action": "hydrated",
        "issue": saved_issue,
        "list_action": list_action,
        "list_update_fields": list_update_fields,
        "volume_created": volume_created,
        "volume_update_fields": volume_update_fields,
        "credit_result": credit_result,
        "relationship_result": relationship_result,
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
        "issue_fields_updated": {},
        "volumes_created": 0,
        "volumes_updated": 0,
        "missing_or_malformed_fields": {},
        "credits": {
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
        "relationships": {
            "remote_items_seen": 0,
            "entities_created": 0,
            "entities_updated": 0,
            "links_created": 0,
            "links_deleted": 0,
            "links_kept": 0,
            "associated_images_created": 0,
            "associated_images_deleted": 0,
            "skipped_items": 0,
            "missing_remote_fields_skipped": 0,
        },
        "stopped_by_api_error": False,
        "api_errors_seen": 0,
        "api_error_retries": 0,
    }


def record_issue_item_result(run_result, item_result):
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

    if item_result["volume_created"]:
        run_result["volumes_created"] += 1

    if item_result["volume_update_fields"]:
        run_result["volumes_updated"] += 1

    for field_name in item_result["list_update_fields"]:
        run_result["issue_fields_updated"][field_name] = (
            run_result["issue_fields_updated"].get(field_name, 0) + 1
        )

    for field_name in item_result["missing_or_malformed_fields"]:
        run_result["missing_or_malformed_fields"][field_name] = (
            run_result["missing_or_malformed_fields"].get(field_name, 0) + 1
        )

    merge_credit_result(run_result["credits"], item_result["credit_result"])
    merge_relationship_result(run_result["relationships"], item_result["relationship_result"])


def merge_credit_result(target, source):
    if source is None:
        return

    for field_name in target.keys():
        target[field_name] += getattr(source, field_name)


def merge_relationship_result(target, source):
    if source is None:
        return

    for field_name in target.keys():
        target[field_name] += getattr(source, field_name)


def print_issue_item_result(*, command, item_result, dry_run):
    if item_result["action"] == "hydrated":
        action = "[WOULD HYDRATE]" if dry_run else "[HYDRATED]"
    else:
        action = "[WOULD SKIP]" if dry_run else "[SKIPPED]"

    command.stdout.write(f"{action} {format_issue_line(item_result['issue'])}")
    command.stdout.write(f"  Issue list action: {format_list_action(item_result['list_action'], dry_run=dry_run)}")

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
            f"  Issue fields updated: {', '.join(item_result['list_update_fields'])}"
        )

    credit_result = item_result["credit_result"]

    if credit_result:
        command.stdout.write(
            "  Person credits: "
            f"remote {credit_result.remote_items_seen}, "
            f"created {credit_result.credits_created}, "
            f"deleted {credit_result.credits_deleted}, "
            f"kept {credit_result.credits_kept}, "
            f"people created {credit_result.people_created}, "
            f"people updated {credit_result.people_updated}, "
            f"roles created {credit_result.roles_created}, "
            f"skipped {credit_result.skipped_items}, "
            f"missing fields skipped {credit_result.missing_remote_fields_skipped}"
        )

    relationship_result = item_result["relationship_result"]

    if relationship_result:
        command.stdout.write(
            "  Relationships/images: "
            f"remote {relationship_result.remote_items_seen}, "
            f"entities created {relationship_result.entities_created}, "
            f"entities updated {relationship_result.entities_updated}, "
            f"links created {relationship_result.links_created}, "
            f"links deleted {relationship_result.links_deleted}, "
            f"links kept {relationship_result.links_kept}, "
            f"images created {relationship_result.associated_images_created}, "
            f"images deleted {relationship_result.associated_images_deleted}, "
            f"skipped {relationship_result.skipped_items}, "
            f"missing fields skipped {relationship_result.missing_remote_fields_skipped}"
        )


def print_issue_run_summary(*, command, run_result, dry_run):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Run summary:"))
    command.stdout.write(f"  Issues processed: {run_result['items_seen']}")
    command.stdout.write(f"  Issues hydrated: {run_result['items_hydrated']}")
    command.stdout.write(f"  Issues marked hydrated: {run_result['items_marked_hydrated']}")
    command.stdout.write(f"  Issues attempted but not marked hydrated: {run_result['items_not_marked_hydrated']}")
    command.stdout.write(f"  Issues skipped: {run_result['items_skipped']}")
    command.stdout.write(f"  API/web errors seen: {run_result['api_errors_seen']}")
    command.stdout.write(f"  API/web error retries: {run_result['api_error_retries']}")
    command.stdout.write(f"  Issue list created: {run_result['list_created']}")
    command.stdout.write(f"  Issue list updated: {run_result['list_updated']}")
    command.stdout.write(f"  Issue list unchanged: {run_result['list_unchanged']}")
    command.stdout.write(f"  Issue list skipped: {run_result['list_skipped']}")
    command.stdout.write(f"  Embedded volumes created: {run_result['volumes_created']}")
    command.stdout.write(f"  Embedded volumes updated: {run_result['volumes_updated']}")

    if run_result["issue_fields_updated"]:
        command.stdout.write("  Issue field update counts:")

        for field_name, count in sorted(run_result["issue_fields_updated"].items()):
            command.stdout.write(f"    {field_name}: {count}")

    if run_result["missing_or_malformed_fields"]:
        command.stdout.write("")
        command.stdout.write("  Missing or malformed detail fields:")

        for field_name, count in sorted(run_result["missing_or_malformed_fields"].items()):
            command.stdout.write(f"    {field_name}: {count}")

    credits = run_result["credits"]

    command.stdout.write("")
    command.stdout.write("  Person credits:")
    command.stdout.write(f"    Remote items seen: {credits['remote_items_seen']}")
    command.stdout.write(f"    People created: {credits['people_created']}")
    command.stdout.write(f"    People updated: {credits['people_updated']}")
    command.stdout.write(f"    Roles created: {credits['roles_created']}")
    command.stdout.write(f"    Credits created: {credits['credits_created']}")
    command.stdout.write(f"    Credits deleted: {credits['credits_deleted']}")
    command.stdout.write(f"    Credits kept: {credits['credits_kept']}")
    command.stdout.write(f"    Skipped items: {credits['skipped_items']}")
    command.stdout.write(f"    Missing remote fields skipped: {credits['missing_remote_fields_skipped']}")

    relationships = run_result["relationships"]

    command.stdout.write("")
    command.stdout.write("  Relationships/images:")
    command.stdout.write(f"    Remote items seen: {relationships['remote_items_seen']}")
    command.stdout.write(f"    Entities created: {relationships['entities_created']}")
    command.stdout.write(f"    Entities updated: {relationships['entities_updated']}")
    command.stdout.write(f"    Links created: {relationships['links_created']}")
    command.stdout.write(f"    Links deleted: {relationships['links_deleted']}")
    command.stdout.write(f"    Links kept: {relationships['links_kept']}")
    command.stdout.write(f"    Associated images created: {relationships['associated_images_created']}")
    command.stdout.write(f"    Associated images deleted: {relationships['associated_images_deleted']}")
    command.stdout.write(f"    Skipped items: {relationships['skipped_items']}")
    command.stdout.write(
        f"    Missing remote fields skipped: {relationships['missing_remote_fields_skipped']}"
    )

    command.stdout.write("")

    if dry_run:
        command.stdout.write("Dry run only. No database changes were saved.")
    elif run_result["stopped_by_api_error"]:
        command.stdout.write("Stopped early because Comic Vine returned an API/web error.")
    else:
        command.stdout.write("Issue detail hydration run completed.")


def format_issue_line(issue):
    volume_name = issue.volume.name if issue.volume else "Unknown volume"
    issue_number = issue.issue_number or "?"
    comicvine_id = issue.comicvine_id or "unknown-id"

    return f"{volume_name} #{issue_number} (issue {comicvine_id})"


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


def validate_options(*, issue_ids, limit, request_delay, api_error_retry_delay):
    if limit is not None and limit < 1:
        raise CommandError("--limit must be at least 1 when provided.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")

    if api_error_retry_delay < 0:
        raise CommandError("--api-error-retry-delay cannot be negative.")

    for issue_id in issue_ids:
        if issue_id < 1:
            raise CommandError("--issue-id must be greater than 0.")


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