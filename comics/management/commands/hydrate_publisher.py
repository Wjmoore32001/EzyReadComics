import os
import time
from dataclasses import dataclass

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from comics.management.commands import hydrate_issues as issue_hydrator
from comics.management.commands import hydrate_volumes as volume_hydrator
from comics.models import ComicIssue, ComicVolume


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
USER_AGENT = "EzyReadComics publisher hydrator"
ISSUE_PAGE_LIMIT = 100


@dataclass
class PublisherOption:
    publisher: str
    volume_count: int
    issue_count: int
    volumes_needing_detail_count: int
    issues_needing_detail_count: int
    volumes_needing_issue_completion_count: int


@dataclass
class PublisherHydrationSummary:
    volumes_found: int = 0
    volumes_checked: int = 0
    volumes_hydrated: int = 0
    volumes_skipped_detail_current: int = 0
    volumes_without_usable_detail: int = 0

    volumes_issue_count_already_matched: int = 0
    volumes_issue_count_mismatched: int = 0
    issue_list_pages_fetched: int = 0
    issues_created_from_lists: int = 0
    issues_updated_from_lists: int = 0
    issue_list_items_skipped_missing_data: int = 0
    issue_list_items_skipped_wrong_volume: int = 0

    stale_issue_links_found: int = 0
    stale_issue_links_repaired: int = 0
    stale_issue_links_left_alone: int = 0

    issues_checked_for_detail: int = 0
    issues_hydrated: int = 0
    issues_without_usable_detail: int = 0
    issue_person_credits_synced: int = 0

    api_requests_made: int = 0


class Command(BaseCommand):
    help = (
        "Hydrate all local volumes for one publisher, pull missing issues for those volumes, "
        "then hydrate those issues."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--publisher",
            help="Publisher name to hydrate. If omitted, an interactive numbered list is shown.",
        )
        parser.add_argument(
            "--publisher-number",
            type=int,
            help="Publisher list number to select without typing the publisher name.",
        )
        parser.add_argument(
            "--list-only",
            action="store_true",
            help="Only list local publishers and counts. Do not hydrate anything.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and print what would happen without saving database changes.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt.",
        )
        parser.add_argument(
            "--request-delay",
            type=float,
            default=0,
            help="Seconds to pause after each Comic Vine request. Defaults to 0.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError("COMICVINE_API_KEY is not set. Add it to your .env file.")

        request_delay = options["request_delay"]
        dry_run = options["dry_run"]

        validate_options(request_delay=request_delay)

        publisher_options = get_publisher_options()

        if not publisher_options:
            self.stdout.write(self.style.WARNING("No local publishers were found."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        print_publisher_options(self, publisher_options)

        if options["list_only"]:
            return

        selected_publisher = select_publisher(
            command=self,
            publisher_options=publisher_options,
            publisher_name=options["publisher"],
            publisher_number=options["publisher_number"],
        )

        volumes = list(
            ComicVolume.objects.filter(publisher__iexact=selected_publisher)
            .order_by("name", "start_year", "comicvine_id")
        )

        if not volumes:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f'No local volumes were found for publisher "{selected_publisher}".'
                )
            )
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Selected publisher"))
        self.stdout.write(f"Publisher: {selected_publisher}")
        self.stdout.write(f"Local volumes found: {len(volumes)}")
        self.stdout.write(
            "This will hydrate local volumes, complete each volume issue list when counts do not match, "
            "then hydrate the local issues for those volumes."
        )

        if not dry_run and not options["yes"]:
            confirmation = input("Continue? Enter y to run: ").strip().lower()

            if confirmation != "y":
                self.stdout.write(self.style.WARNING("Cancelled."))
                return

        summary = PublisherHydrationSummary(volumes_found=len(volumes))

        try:
            with requests.Session() as session:
                session.headers.update({"User-Agent": USER_AGENT})

                for volume in volumes:
                    process_volume_for_publisher(
                        command=self,
                        session=session,
                        api_key=api_key,
                        volume=volume,
                        request_delay=request_delay,
                        dry_run=dry_run,
                        summary=summary,
                    )

        except KeyboardInterrupt:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Cancelled. Any active database transaction was rolled back by Django."
                )
            )
            raise

        print_summary(self, summary)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def validate_options(request_delay):
    if request_delay < 0:
        raise CommandError("request-delay cannot be negative.")


def get_publisher_options():
    rows = (
        ComicVolume.objects.exclude(publisher__isnull=True)
        .exclude(publisher__exact="")
        .values("publisher")
        .annotate(volume_count=Count("id"))
        .order_by("publisher")
    )

    publisher_options = []

    for row in rows:
        publisher = (row["publisher"] or "").strip()

        if not publisher:
            continue

        volumes_queryset = ComicVolume.objects.filter(publisher__iexact=publisher)

        issue_count = ComicIssue.objects.filter(
            volume__publisher__iexact=publisher
        ).count()

        volumes_needing_detail_count = (
            volume_hydrator.get_volumes_needing_hydration_queryset()
            .filter(publisher__iexact=publisher)
            .count()
        )

        issues_needing_detail_count = (
            issue_hydrator.get_issues_needing_hydration_queryset()
            .filter(volume__publisher__iexact=publisher)
            .count()
        )

        volumes_needing_issue_completion_count = count_volumes_needing_issue_completion(
            volumes_queryset=volumes_queryset,
        )

        publisher_options.append(
            PublisherOption(
                publisher=publisher,
                volume_count=row["volume_count"],
                issue_count=issue_count,
                volumes_needing_detail_count=volumes_needing_detail_count,
                issues_needing_detail_count=issues_needing_detail_count,
                volumes_needing_issue_completion_count=volumes_needing_issue_completion_count,
            )
        )

    return publisher_options


def count_volumes_needing_issue_completion(volumes_queryset):
    count = 0

    for volume in volumes_queryset.only("id", "count_of_issues"):
        local_issue_count = ComicIssue.objects.filter(volume=volume).count()

        if volume.count_of_issues is None:
            count += 1
            continue

        if local_issue_count != volume.count_of_issues:
            count += 1

    return count


def print_publisher_options(command, publisher_options):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Local publishers"))
    command.stdout.write("----------------")

    for index, option in enumerate(publisher_options, start=1):
        command.stdout.write(
            f"{index}. {option.publisher} "
            f"| volumes: {option.volume_count} "
            f"| issues: {option.issue_count} "
            f"| volumes needing detail: {option.volumes_needing_detail_count} "
            f"| volumes needing issue completion: {option.volumes_needing_issue_completion_count} "
            f"| issues needing detail: {option.issues_needing_detail_count}"
        )

    command.stdout.write("")


def select_publisher(command, publisher_options, publisher_name, publisher_number):
    if publisher_name and publisher_number:
        raise CommandError("Use either --publisher or --publisher-number, not both.")

    if publisher_number is not None:
        if publisher_number < 1 or publisher_number > len(publisher_options):
            raise CommandError(
                f"publisher-number must be between 1 and {len(publisher_options)}."
            )

        return publisher_options[publisher_number - 1].publisher

    if publisher_name:
        for option in publisher_options:
            if option.publisher.lower() == publisher_name.lower():
                return option.publisher

        raise CommandError(
            f'Publisher "{publisher_name}" was not found in your local database.'
        )

    raw_choice = input("Select publisher number: ").strip()

    if not raw_choice.isdigit():
        raise CommandError("Publisher selection must be a number.")

    selected_number = int(raw_choice)

    if selected_number < 1 or selected_number > len(publisher_options):
        raise CommandError(
            f"Publisher selection must be between 1 and {len(publisher_options)}."
        )

    return publisher_options[selected_number - 1].publisher


def process_volume_for_publisher(
    command,
    session,
    api_key,
    volume,
    request_delay,
    dry_run,
    summary,
):
    summary.volumes_checked += 1

    command.stdout.write("")
    command.stdout.write("=" * 72)
    command.stdout.write(f"Volume: {volume.name}")
    command.stdout.write(f"Comic Vine Volume ID: {volume.comicvine_id}")

    if volume_needs_detail(volume):
        hydrate_one_volume(
            command=command,
            session=session,
            api_key=api_key,
            volume=volume,
            request_delay=request_delay,
            dry_run=dry_run,
            summary=summary,
        )
    else:
        summary.volumes_skipped_detail_current += 1
        command.stdout.write("Volume detail is already current locally.")

    if not dry_run:
        volume.refresh_from_db()

    complete_issue_list_for_volume_if_needed(
        command=command,
        session=session,
        api_key=api_key,
        volume=volume,
        request_delay=request_delay,
        dry_run=dry_run,
        summary=summary,
    )

    if not dry_run:
        volume.refresh_from_db()

    hydrate_issues_for_volume(
        command=command,
        session=session,
        api_key=api_key,
        volume=volume,
        request_delay=request_delay,
        dry_run=dry_run,
        summary=summary,
    )


def volume_needs_detail(volume):
    return (
        volume_hydrator.get_volumes_needing_hydration_queryset()
        .filter(pk=volume.pk)
        .exists()
    )


def hydrate_one_volume(
    command,
    session,
    api_key,
    volume,
    request_delay,
    dry_run,
    summary,
):
    attempted_at = timezone.now()

    command.stdout.write("Hydrating volume detail...")

    data = volume_hydrator.fetch_volume_detail(
        session=session,
        api_key=api_key,
        volume_id=volume.comicvine_id,
    )
    summary.api_requests_made += 1

    remote_volume = data.get("results") or {}

    if not remote_volume or not remote_volume.get("id"):
        summary.volumes_without_usable_detail += 1
        command.stdout.write(
            command.style.WARNING(
                "No usable volume detail returned. Not marking detail hydration attempted."
            )
        )
        sleep_after_request(request_delay)
        return

    volume_data = volume_hydrator.build_volume_data(
        local_volume=volume,
        remote_volume=remote_volume,
        attempted_at=attempted_at,
    )

    if not volume_hydrator.has_useful_volume_data(volume_data):
        summary.volumes_without_usable_detail += 1
        command.stdout.write(
            command.style.WARNING(
                "Volume detail was not useful. Not marking detail hydration attempted."
            )
        )
        sleep_after_request(request_delay)
        return

    remote_people = remote_volume.get("people") or []

    command.stdout.write(f"Volume detail found: {volume_data['name']}")
    command.stdout.write(f"Expected issue count from volume: {volume_data['count_of_issues']}")
    command.stdout.write(f"Volume people returned: {len(remote_people)}")

    if not dry_run:
        volume_hydrator.update_volume(
            local_volume=volume,
            volume_data=volume_data,
            remote_people=remote_people,
        )

    summary.volumes_hydrated += 1

    sleep_after_request(request_delay)


def complete_issue_list_for_volume_if_needed(
    command,
    session,
    api_key,
    volume,
    request_delay,
    dry_run,
    summary,
):
    expected_issue_count = volume.count_of_issues
    local_issue_count = ComicIssue.objects.filter(volume=volume).count()

    command.stdout.write("")
    command.stdout.write("Issue list check")
    command.stdout.write(f"Expected issue count from volume: {expected_issue_count}")
    command.stdout.write(f"Local issue count for this volume: {local_issue_count}")

    if expected_issue_count is not None and local_issue_count == expected_issue_count:
        summary.volumes_issue_count_already_matched += 1
        command.stdout.write("Issue count matches. No issue-list API request needed.")
        return

    summary.volumes_issue_count_mismatched += 1

    command.stdout.write(
        command.style.WARNING(
            "Issue count does not match or expected count is unknown. "
            "Pulling full issue list for this volume."
        )
    )

    remote_issues, remote_total, pages_fetched = fetch_all_issues_for_volume(
        command=command,
        session=session,
        api_key=api_key,
        volume=volume,
        request_delay=request_delay,
    )

    summary.api_requests_made += pages_fetched
    summary.issue_list_pages_fetched += pages_fetched

    if not dry_run and remote_total is not None and volume.count_of_issues != remote_total:
        with transaction.atomic():
            volume.count_of_issues = remote_total
            volume.save(update_fields=["count_of_issues"])

    issue_list_result = save_issue_list_for_volume(
        volume=volume,
        remote_issues=remote_issues,
        dry_run=dry_run,
    )

    summary.issues_created_from_lists += issue_list_result["created"]
    summary.issues_updated_from_lists += issue_list_result["updated"]
    summary.issue_list_items_skipped_missing_data += issue_list_result["missing_data_skipped"]
    summary.issue_list_items_skipped_wrong_volume += issue_list_result["wrong_volume_skipped"]

    command.stdout.write("")
    command.stdout.write("Issue list import result:")
    command.stdout.write(f"Remote total issues for volume: {remote_total}")
    command.stdout.write(f"Issues created from list: {issue_list_result['created']}")
    command.stdout.write(f"Issues updated from list: {issue_list_result['updated']}")
    command.stdout.write(
        f"Issue-list items skipped because of missing data: {issue_list_result['missing_data_skipped']}"
    )
    command.stdout.write(
        f"Issue-list items skipped because they belonged to another volume: {issue_list_result['wrong_volume_skipped']}"
    )

    repair_result = repair_stale_issue_links_for_volume(
        command=command,
        session=session,
        api_key=api_key,
        volume=volume,
        remote_issue_ids=issue_list_result["remote_issue_ids"],
        request_delay=request_delay,
        dry_run=dry_run,
    )

    summary.stale_issue_links_found += repair_result["found"]
    summary.stale_issue_links_repaired += repair_result["repaired"]
    summary.stale_issue_links_left_alone += repair_result["left_alone"]
    summary.api_requests_made += repair_result["api_requests_made"]

    final_local_count = ComicIssue.objects.filter(volume=volume).count()

    command.stdout.write("")
    command.stdout.write("Post-import issue count:")
    command.stdout.write(f"Expected issue count: {remote_total}")
    command.stdout.write(f"Local issue count now: {final_local_count}")


def fetch_all_issues_for_volume(command, session, api_key, volume, request_delay):
    remote_issues = []
    offset = 0
    pages_fetched = 0
    remote_total = None

    while True:
        data = fetch_issue_list_page_for_volume(
            session=session,
            api_key=api_key,
            volume_id=volume.comicvine_id,
            limit=ISSUE_PAGE_LIMIT,
            offset=offset,
        )

        pages_fetched += 1

        if remote_total is None:
            remote_total = to_optional_int(data.get("number_of_total_results"))

        page_issues = data.get("results") or []

        command.stdout.write("")
        command.stdout.write(f"Issue page fetched: {pages_fetched}")
        command.stdout.write(f"Comic Vine issue filter: volume:{volume.comicvine_id}")
        command.stdout.write(f"Total remote issues for this volume: {remote_total}")
        command.stdout.write(f"Current offset: {offset}")
        command.stdout.write(f"Issues returned: {len(page_issues)}")

        remote_issues.extend(page_issues)

        if not page_issues:
            break

        offset += len(page_issues)

        if remote_total is not None and offset >= remote_total:
            break

        if len(page_issues) < ISSUE_PAGE_LIMIT:
            break

        sleep_after_request(request_delay)

    sleep_after_request(request_delay)

    return remote_issues, remote_total, pages_fetched


def fetch_issue_list_page_for_volume(session, api_key, volume_id, limit, offset):
    params = {
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "offset": offset,
        "filter": f"volume:{volume_id}",
        "field_list": ",".join(
            [
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
            ]
        ),
    }

    return volume_hydrator.fetch_comicvine_json(
        session=session,
        url=ISSUES_URL,
        params=params,
    )


def save_issue_list_for_volume(volume, remote_issues, dry_run):
    valid_remote_issues = []
    remote_issue_ids = set()
    missing_data_skipped = 0
    wrong_volume_skipped = 0

    for remote_issue in remote_issues:
        issue_id = to_optional_int(remote_issue.get("id"))
        remote_volume_id = issue_hydrator.get_volume_id(remote_issue.get("volume") or {})

        if not issue_id:
            missing_data_skipped += 1
            continue

        if remote_volume_id != volume.comicvine_id:
            wrong_volume_skipped += 1
            continue

        valid_remote_issues.append(remote_issue)
        remote_issue_ids.add(issue_id)

    existing_issue_ids = set(
        ComicIssue.objects.filter(
            comicvine_id__in=remote_issue_ids,
        ).values_list("comicvine_id", flat=True)
    )

    created_count = len(remote_issue_ids - existing_issue_ids)
    updated_count = len(remote_issue_ids.intersection(existing_issue_ids))

    if dry_run:
        return {
            "created": created_count,
            "updated": updated_count,
            "missing_data_skipped": missing_data_skipped,
            "wrong_volume_skipped": wrong_volume_skipped,
            "remote_issue_ids": remote_issue_ids,
        }

    with transaction.atomic():
        for remote_issue in valid_remote_issues:
            create_or_update_issue_from_list(
                volume=volume,
                remote_issue=remote_issue,
            )

    return {
        "created": created_count,
        "updated": updated_count,
        "missing_data_skipped": missing_data_skipped,
        "wrong_volume_skipped": wrong_volume_skipped,
        "remote_issue_ids": remote_issue_ids,
    }


def create_or_update_issue_from_list(volume, remote_issue):
    issue_id = to_optional_int(remote_issue.get("id"))
    image = remote_issue.get("image") or {}

    issue_defaults = {
        "volume": volume,
        "issue_number": remote_issue.get("issue_number") or "",
        "issue_title": remote_issue.get("name") or "",
        "cover_date": issue_hydrator.parse_comicvine_date(remote_issue.get("cover_date")),
        "store_date": issue_hydrator.parse_comicvine_date(remote_issue.get("store_date")),
        "date_added": issue_hydrator.parse_comicvine_datetime(remote_issue.get("date_added")),
        "date_last_updated": issue_hydrator.parse_comicvine_datetime(
            remote_issue.get("date_last_updated")
        ),
        "comicvine_url": remote_issue.get("site_detail_url") or "",
        "api_detail_url": remote_issue.get("api_detail_url") or "",
        "aliases": remote_issue.get("aliases") or "",
        "deck": remote_issue.get("deck") or "",
        "description": remote_issue.get("description") or "",
        "has_staff_review": bool(remote_issue.get("has_staff_review")),
        "comicvine_image_icon_url": image.get("icon_url") or "",
        "comicvine_image_medium_url": image.get("medium_url") or "",
        "comicvine_image_screen_url": image.get("screen_url") or "",
        "comicvine_image_screen_large_url": image.get("screen_large_url") or "",
        "comicvine_image_small_url": image.get("small_url") or "",
        "comicvine_image_super_url": image.get("super_url") or "",
        "comicvine_image_thumb_url": image.get("thumb_url") or "",
        "comicvine_image_tiny_url": image.get("tiny_url") or "",
        "comicvine_image_original_url": image.get("original_url") or "",
        "comicvine_image_tags": image.get("image_tags") or "",
    }

    local_issue = ComicIssue.objects.filter(comicvine_id=issue_id).first()

    if not local_issue:
        ComicIssue.objects.create(
            comicvine_id=issue_id,
            **issue_defaults,
        )
        return

    update_fields = []

    always_update_fields = [
        "volume",
        "issue_number",
        "issue_title",
        "cover_date",
        "store_date",
        "date_added",
        "date_last_updated",
        "comicvine_url",
        "api_detail_url",
        "has_staff_review",
        "comicvine_image_icon_url",
        "comicvine_image_medium_url",
        "comicvine_image_screen_url",
        "comicvine_image_screen_large_url",
        "comicvine_image_small_url",
        "comicvine_image_super_url",
        "comicvine_image_thumb_url",
        "comicvine_image_tiny_url",
        "comicvine_image_original_url",
        "comicvine_image_tags",
    ]

    fill_if_blank_fields = [
        "aliases",
        "deck",
        "description",
    ]

    for field_name in always_update_fields:
        new_value = issue_defaults[field_name]

        if getattr(local_issue, field_name) != new_value:
            setattr(local_issue, field_name, new_value)
            update_fields.append(field_name)

    for field_name in fill_if_blank_fields:
        new_value = issue_defaults[field_name]

        if not getattr(local_issue, field_name) and new_value:
            setattr(local_issue, field_name, new_value)
            update_fields.append(field_name)

    if update_fields:
        local_issue.save(update_fields=update_fields)


def repair_stale_issue_links_for_volume(
    command,
    session,
    api_key,
    volume,
    remote_issue_ids,
    request_delay,
    dry_run,
):
    if not remote_issue_ids:
        return {
            "found": 0,
            "repaired": 0,
            "left_alone": 0,
            "api_requests_made": 0,
        }

    stale_issues = list(
        ComicIssue.objects.filter(
            volume=volume,
            comicvine_id__isnull=False,
        )
        .exclude(comicvine_id__in=remote_issue_ids)
        .order_by("comicvine_id")
    )

    found = len(stale_issues)
    repaired = 0
    left_alone = 0
    api_requests_made = 0

    if not stale_issues:
        return {
            "found": found,
            "repaired": repaired,
            "left_alone": left_alone,
            "api_requests_made": api_requests_made,
        }

    command.stdout.write("")
    command.stdout.write(
        command.style.WARNING(
            f"Found {found} local issue(s) linked to this volume that were not in the remote volume issue list."
        )
    )
    command.stdout.write("Checking those issue detail records to repair wrong volume links when possible.")

    for local_issue in stale_issues:
        data = issue_hydrator.fetch_issue_detail(
            session=session,
            api_key=api_key,
            issue_id=local_issue.comicvine_id,
        )
        api_requests_made += 1

        remote_issue = data.get("results") or {}

        if not remote_issue or not remote_issue.get("id"):
            left_alone += 1
            sleep_after_request(request_delay)
            continue

        remote_volume = remote_issue.get("volume") or {}
        remote_volume_id = issue_hydrator.get_volume_id(remote_volume)

        if remote_volume_id and remote_volume_id != volume.comicvine_id:
            attempted_at = timezone.now()
            issue_data = issue_hydrator.build_issue_data(
                local_issue=local_issue,
                remote_issue=remote_issue,
                attempted_at=attempted_at,
            )
            remote_people = remote_issue.get("person_credits") or []

            command.stdout.write(
                f"Repairing wrong volume link: issue {local_issue.comicvine_id} "
                f"moves from volume {volume.comicvine_id} to volume {remote_volume_id}."
            )

            if not dry_run:
                issue_hydrator.update_issue(
                    local_issue=local_issue,
                    issue_data=issue_data,
                    volume_data=remote_volume,
                    remote_people=remote_people,
                )

            repaired += 1
        else:
            left_alone += 1

        sleep_after_request(request_delay)

    return {
        "found": found,
        "repaired": repaired,
        "left_alone": left_alone,
        "api_requests_made": api_requests_made,
    }


def hydrate_issues_for_volume(
    command,
    session,
    api_key,
    volume,
    request_delay,
    dry_run,
    summary,
):
    issues_to_hydrate = list(
        issue_hydrator.get_issues_needing_hydration_queryset()
        .filter(volume=volume)
        .order_by("id")
    )

    command.stdout.write("")
    command.stdout.write("Issue detail hydration")
    command.stdout.write(f"Issues needing detail hydration for this volume: {len(issues_to_hydrate)}")

    if not issues_to_hydrate:
        command.stdout.write("No issue detail API requests needed for this volume.")
        return

    for local_issue in issues_to_hydrate:
        hydrate_one_issue(
            command=command,
            session=session,
            api_key=api_key,
            local_issue=local_issue,
            request_delay=request_delay,
            dry_run=dry_run,
            summary=summary,
        )


def hydrate_one_issue(
    command,
    session,
    api_key,
    local_issue,
    request_delay,
    dry_run,
    summary,
):
    summary.issues_checked_for_detail += 1
    attempted_at = timezone.now()

    data = issue_hydrator.fetch_issue_detail(
        session=session,
        api_key=api_key,
        issue_id=local_issue.comicvine_id,
    )
    summary.api_requests_made += 1

    remote_issue = data.get("results") or {}

    if not remote_issue or not remote_issue.get("id"):
        summary.issues_without_usable_detail += 1
        command.stdout.write(
            command.style.WARNING(
                f"Issue {local_issue.comicvine_id} returned no usable detail. "
                "Not marking detail hydration attempted."
            )
        )
        sleep_after_request(request_delay)
        return

    issue_data = issue_hydrator.build_issue_data(
        local_issue=local_issue,
        remote_issue=remote_issue,
        attempted_at=attempted_at,
    )
    volume_data = remote_issue.get("volume") or {}
    remote_people = remote_issue.get("person_credits") or []

    command.stdout.write(
        f"Hydrating issue detail: {local_issue.comicvine_id} "
        f"| #{issue_data['issue_number']} "
        f"| {issue_data['issue_title']}"
    )

    if not dry_run:
        people_synced = issue_hydrator.update_issue(
            local_issue=local_issue,
            issue_data=issue_data,
            volume_data=volume_data,
            remote_people=remote_people,
        )
    else:
        people_synced = issue_hydrator.count_valid_person_credits(remote_people)

    summary.issues_hydrated += 1
    summary.issue_person_credits_synced += people_synced

    sleep_after_request(request_delay)


def to_optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sleep_after_request(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)


def print_summary(command, summary):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Publisher hydration summary:"))
    command.stdout.write(f"Volumes found for publisher: {summary.volumes_found}")
    command.stdout.write(f"Volumes checked: {summary.volumes_checked}")
    command.stdout.write(f"Volumes hydrated: {summary.volumes_hydrated}")
    command.stdout.write(f"Volumes skipped because detail was already current: {summary.volumes_skipped_detail_current}")
    command.stdout.write(f"Volumes without usable detail returned: {summary.volumes_without_usable_detail}")

    command.stdout.write("")
    command.stdout.write("Issue list completion:")
    command.stdout.write(f"Volumes where issue count already matched: {summary.volumes_issue_count_already_matched}")
    command.stdout.write(f"Volumes where issue count did not match or was unknown: {summary.volumes_issue_count_mismatched}")
    command.stdout.write(f"Issue-list pages fetched: {summary.issue_list_pages_fetched}")
    command.stdout.write(f"Issues created from lists: {summary.issues_created_from_lists}")
    command.stdout.write(f"Issues updated from lists: {summary.issues_updated_from_lists}")
    command.stdout.write(f"Issue-list items skipped missing data: {summary.issue_list_items_skipped_missing_data}")
    command.stdout.write(f"Issue-list items skipped wrong volume: {summary.issue_list_items_skipped_wrong_volume}")

    command.stdout.write("")
    command.stdout.write("Wrong-link repair:")
    command.stdout.write(f"Stale local issue links found: {summary.stale_issue_links_found}")
    command.stdout.write(f"Stale local issue links repaired: {summary.stale_issue_links_repaired}")
    command.stdout.write(f"Stale local issue links left alone: {summary.stale_issue_links_left_alone}")

    command.stdout.write("")
    command.stdout.write("Issue detail hydration:")
    command.stdout.write(f"Issues checked for detail: {summary.issues_checked_for_detail}")
    command.stdout.write(f"Issues hydrated: {summary.issues_hydrated}")
    command.stdout.write(f"Issues without usable detail returned: {summary.issues_without_usable_detail}")
    command.stdout.write(f"Issue person credits synced: {summary.issue_person_credits_synced}")

    command.stdout.write("")
    command.stdout.write(f"Comic Vine API requests made: {summary.api_requests_made}")