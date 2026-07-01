import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from requests.exceptions import RequestException

from comicvine.api.client import (
    ComicVineAPIError,
    create_comicvine_session,
    get_comicvine_api_key,
)
from comicvine.services.sync.issue_details import (
    hydrate_single_issue_detail,
    select_issues_to_hydrate,
)


USER_AGENT = "EzyReadComics bulk_hydrate_issue_details"

DEFAULT_API_ERROR_RETRY_DELAY = 90 * 60


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
            self.stdout.write(
                f"Target issue IDs: {', '.join(str(issue_id) for issue_id in issue_ids)}"
            )
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

    command.stdout.write(f"  list action: {item_result['list_action']}")

    if item_result["list_update_fields"]:
        command.stdout.write(
            f"  issue fields updated: {', '.join(item_result['list_update_fields'])}"
        )
    else:
        command.stdout.write("  issue fields updated: none")

    if item_result["volume_created"]:
        command.stdout.write("  minimal volume created: yes")

    if item_result["volume_update_fields"]:
        command.stdout.write(
            f"  minimal volume fields updated: {', '.join(item_result['volume_update_fields'])}"
        )

    credit_result = item_result["credit_result"]

    if credit_result:
        command.stdout.write(
            "  person credits: "
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
            "  relationships/images: "
            f"links created {relationship_result.links_created}, "
            f"links deleted {relationship_result.links_deleted}, "
            f"links kept {relationship_result.links_kept}, "
            f"entities created {relationship_result.entities_created}, "
            f"entities updated {relationship_result.entities_updated}, "
            f"images created {relationship_result.associated_images_created}, "
            f"images deleted {relationship_result.associated_images_deleted}, "
            f"skipped {relationship_result.skipped_items}, "
            f"missing fields skipped {relationship_result.missing_remote_fields_skipped}"
        )

    if item_result["missing_or_malformed_fields"]:
        command.stdout.write(
            command.style.WARNING(
                "  not marked hydrated because missing/malformed detail fields: "
                + ", ".join(item_result["missing_or_malformed_fields"])
            )
        )
    elif item_result["marked_hydrated"]:
        command.stdout.write("  marked hydrated: yes")
    else:
        command.stdout.write("  marked hydrated: no")


def print_issue_run_summary(*, command, run_result, dry_run):
    command.stdout.write("")
    command.stdout.write("=" * 80)

    if dry_run:
        command.stdout.write(command.style.WARNING("Dry run complete. No database changes were written."))
    else:
        command.stdout.write(command.style.SUCCESS("Issue detail hydration complete."))

    command.stdout.write("=" * 80)
    command.stdout.write(f"issues seen: {run_result['items_seen']}")
    command.stdout.write(f"issues hydrated: {run_result['items_hydrated']}")
    command.stdout.write(f"issues marked hydrated: {run_result['items_marked_hydrated']}")
    command.stdout.write(f"issues not marked hydrated: {run_result['items_not_marked_hydrated']}")
    command.stdout.write(f"issues skipped: {run_result['items_skipped']}")
    command.stdout.write("")
    command.stdout.write(f"list created: {run_result['list_created']}")
    command.stdout.write(f"list updated: {run_result['list_updated']}")
    command.stdout.write(f"list unchanged: {run_result['list_unchanged']}")
    command.stdout.write(f"list skipped: {run_result['list_skipped']}")
    command.stdout.write("")
    command.stdout.write(f"minimal volumes created: {run_result['volumes_created']}")
    command.stdout.write(f"minimal volumes updated: {run_result['volumes_updated']}")
    command.stdout.write("")
    command.stdout.write("credits:")
    print_nested_counts(command, run_result["credits"])
    command.stdout.write("")
    command.stdout.write("relationships/images:")
    print_nested_counts(command, run_result["relationships"])

    if run_result["issue_fields_updated"]:
        command.stdout.write("")
        command.stdout.write("issue field update counts:")
        print_nested_counts(command, run_result["issue_fields_updated"])

    if run_result["missing_or_malformed_fields"]:
        command.stdout.write("")
        command.stdout.write(command.style.WARNING("missing/malformed detail field counts:"))
        print_nested_counts(command, run_result["missing_or_malformed_fields"])

    if run_result["api_errors_seen"]:
        command.stdout.write("")
        command.stdout.write(f"API/web errors seen: {run_result['api_errors_seen']}")
        command.stdout.write(f"API/web retries: {run_result['api_error_retries']}")

        if run_result["stopped_by_api_error"]:
            command.stdout.write(command.style.WARNING("Stopped because of an API/web error."))


def print_nested_counts(command, counts):
    for key, value in counts.items():
        command.stdout.write(f"  {key}: {value}")


def format_issue_line(issue):
    volume_name = issue.volume.name if issue.volume else "Unknown Volume"

    return (
        f"{volume_name} #{issue.issue_number} "
        f"(Comic Vine issue ID: {issue.comicvine_id})"
    )


def validate_options(*, issue_ids, limit, request_delay, api_error_retry_delay):
    if limit is not None and limit < 1:
        raise CommandError("--limit must be at least 1.")

    if request_delay < 0:
        raise CommandError("--request-delay cannot be negative.")

    if api_error_retry_delay < 0:
        raise CommandError("--api-error-retry-delay cannot be negative.")

    for issue_id in issue_ids:
        if issue_id < 1:
            raise CommandError("--issue-id values must be greater than 0.")


def sleep_if_needed(delay):
    if delay > 0:
        time.sleep(delay)


def format_seconds(seconds):
    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds} seconds"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes} minutes"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if remaining_minutes:
        return f"{hours} hours {remaining_minutes} minutes"

    return f"{hours} hours"