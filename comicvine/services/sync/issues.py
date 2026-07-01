from django.db import transaction

from comicvine.api.parsing import (
    clean_text,
    has_usable_value,
    image_data_from_remote,
    is_missing_value,
    parse_comicvine_date,
    parse_comicvine_datetime,
    to_optional_int,
)
from comicvine.models import ComicVineIssue
from comicvine.services.sync.relationships import sync_issue_associated_images
from comicvine.services.sync.results import IssueListSaveResult, RelationshipSyncResult
from comicvine.services.sync.volumes import get_or_create_volume_from_embedded_data


ISSUE_LIST_UPDATE_FIELDS = [
    "volume",
    "issue_number",
    "issue_title",
    "cover_date",
    "store_date",
    "date_added",
    "date_last_updated",
    "comicvine_url",
    "api_detail_url",
    "aliases",
    "deck",
    "description",
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


def build_issue_list_data(remote_issue, *, volume=None):
    image_data = image_data_from_remote(remote_issue.get("image"))

    return {
        "comicvine_id": to_optional_int(remote_issue.get("id")),
        "volume": volume,
        "issue_number": clean_text(remote_issue.get("issue_number")),
        "issue_title": clean_text(remote_issue.get("name")),
        "cover_date": parse_comicvine_date(remote_issue.get("cover_date")),
        "store_date": parse_comicvine_date(remote_issue.get("store_date")),
        "date_added": parse_comicvine_datetime(remote_issue.get("date_added")),
        "date_last_updated": parse_comicvine_datetime(remote_issue.get("date_last_updated")),
        "comicvine_url": clean_text(remote_issue.get("site_detail_url")),
        "api_detail_url": clean_text(remote_issue.get("api_detail_url")),
        "aliases": clean_text(remote_issue.get("aliases")),
        "deck": clean_text(remote_issue.get("deck")),
        "description": clean_text(remote_issue.get("description")),
        "has_staff_review": bool(remote_issue.get("has_staff_review")),
        **image_data,
    }


def save_issue_list_data(
    remote_issue,
    *,
    overwrite_existing=True,
    create_missing=True,
    dry_run=False,
):
    comicvine_id = to_optional_int(remote_issue.get("id"))

    if comicvine_id is None:
        return "skipped", None, [], False, [], RelationshipSyncResult()

    volume, volume_created, volume_update_fields = get_or_create_volume_from_embedded_data(
        remote_issue.get("volume"),
        dry_run=dry_run,
    )

    issue_data = build_issue_list_data(remote_issue, volume=volume)

    local_issue = ComicVineIssue.objects.filter(comicvine_id=comicvine_id).first()

    if not local_issue:
        if not create_missing:
            return "skipped", None, [], volume_created, volume_update_fields, RelationshipSyncResult()

        if dry_run:
            image_result = build_dry_run_new_issue_associated_image_result(remote_issue)
            return "created", None, [], volume_created, volume_update_fields, image_result

        create_data = {
            "comicvine_id": comicvine_id,
            "issue_number": issue_data["issue_number"] or "",
        }

        for field_name in ISSUE_LIST_UPDATE_FIELDS:
            if field_name in issue_data and has_usable_value(issue_data[field_name]):
                create_data[field_name] = issue_data[field_name]

        with transaction.atomic():
            local_issue = ComicVineIssue.objects.create(**create_data)

        image_result = sync_associated_images_if_present(
            local_issue,
            remote_issue,
            dry_run=False,
        )

        return (
            "created",
            local_issue,
            list(create_data.keys()),
            volume_created,
            volume_update_fields,
            image_result,
        )

    update_fields = get_issue_list_update_fields(
        local_issue=local_issue,
        issue_data=issue_data,
        overwrite_existing=overwrite_existing,
    )

    if not update_fields:
        image_result = sync_associated_images_if_present(
            local_issue,
            remote_issue,
            dry_run=dry_run,
        )

        return (
            "unchanged",
            local_issue,
            [],
            volume_created,
            volume_update_fields,
            image_result,
        )

    if dry_run:
        image_result = sync_associated_images_if_present(
            local_issue,
            remote_issue,
            dry_run=True,
        )

        return (
            "updated",
            local_issue,
            update_fields,
            volume_created,
            volume_update_fields,
            image_result,
        )

    with transaction.atomic():
        locked_issue = ComicVineIssue.objects.select_for_update().get(id=local_issue.id)
        update_fields = get_issue_list_update_fields(
            local_issue=locked_issue,
            issue_data=issue_data,
            overwrite_existing=overwrite_existing,
        )

        if not update_fields:
            image_result = sync_associated_images_if_present(
                locked_issue,
                remote_issue,
                dry_run=False,
            )

            return (
                "unchanged",
                locked_issue,
                [],
                volume_created,
                volume_update_fields,
                image_result,
            )

        for field_name in update_fields:
            setattr(locked_issue, field_name, issue_data[field_name])

        locked_issue.save(update_fields=update_fields)

    image_result = sync_associated_images_if_present(
        locked_issue,
        remote_issue,
        dry_run=False,
    )

    return (
        "updated",
        locked_issue,
        update_fields,
        volume_created,
        volume_update_fields,
        image_result,
    )


def save_issues_from_list_data(
    remote_issues,
    *,
    overwrite_existing=True,
    create_missing=True,
    dry_run=False,
):
    result = IssueListSaveResult()

    for remote_issue in remote_issues or []:
        result.issues_seen += 1

        (
            action,
            _issue,
            update_fields,
            volume_created,
            volume_update_fields,
            image_result,
        ) = save_issue_list_data(
            remote_issue,
            overwrite_existing=overwrite_existing,
            create_missing=create_missing,
            dry_run=dry_run,
        )

        if volume_created:
            result.volumes_created += 1

        if volume_update_fields:
            result.volumes_updated += 1

        result.record_relationship_result(image_result)

        if action == "created":
            result.issues_created += 1
            result.record_issue_fields(update_fields)
        elif action == "updated":
            result.issues_updated += 1
            result.record_issue_fields(update_fields)
        elif action == "unchanged":
            result.issues_unchanged += 1
        else:
            result.issues_skipped += 1

    return result


def get_issue_list_update_fields(*, local_issue, issue_data, overwrite_existing):
    update_fields = []

    for field_name in ISSUE_LIST_UPDATE_FIELDS:
        if field_name not in issue_data:
            continue

        new_value = issue_data[field_name]

        if not has_usable_value(new_value):
            continue

        current_value = getattr(local_issue, field_name)

        if overwrite_existing:
            if current_value != new_value:
                update_fields.append(field_name)
        elif is_missing_value(current_value):
            update_fields.append(field_name)

    return update_fields


def sync_associated_images_if_present(issue, remote_issue, *, dry_run=False):
    if "associated_images" not in remote_issue:
        result = RelationshipSyncResult()
        result.missing_remote_fields_skipped += 1
        return result

    return sync_issue_associated_images(
        issue,
        remote_issue.get("associated_images"),
        dry_run=dry_run,
    )


def build_dry_run_new_issue_associated_image_result(remote_issue):
    result = RelationshipSyncResult()

    if "associated_images" not in remote_issue:
        result.missing_remote_fields_skipped += 1
        return result

    remote_images = remote_issue.get("associated_images")

    if remote_images is None:
        result.missing_remote_fields_skipped += 1
        return result

    # A new dry-run issue has no existing associated images to delete.
    for remote_image in remote_images:
        if has_usable_associated_image(remote_image):
            result.associated_images_created += 1
        else:
            result.skipped_items += 1

    return result


def has_usable_associated_image(remote_image):
    image = remote_image or {}

    return any(
        [
            clean_text(image.get("original_url")),
            clean_text(image.get("super_url")),
            clean_text(image.get("screen_large_url")),
            clean_text(image.get("medium_url")),
            clean_text(image.get("small_url")),
            clean_text(image.get("thumb_url")),
        ]
    )