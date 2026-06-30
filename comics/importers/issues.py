import time

from django.db import transaction
from django.db.models import Q

from comics.comicvine.client import fetch_volumes_by_ids
from comics.comicvine.fields import VOLUME_LIST_FIELDS
from comics.comicvine.parsing import (
    choose_display_image_url,
    clean_text,
    has_usable_value,
    image_data_from_remote,
    is_missing_value,
    parse_comicvine_datetime,
    to_optional_int,
)
from comics.importers.results import VolumeBatchRefreshResult, VolumeListSaveResult
from comics.models import ComicVolume


VOLUME_LIST_UPDATE_FIELDS = [
    "name",
    "publisher",
    "publisher_comicvine_id",
    "publisher_api_detail_url",
    "start_year",
    "count_of_issues",
    "date_added",
    "date_last_updated",
    "comicvine_url",
    "api_detail_url",
    "aliases",
    "deck",
    "description",
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
    "display_image_url",
    "display_image_source",
    "first_issue_comicvine_id",
    "first_issue_number",
    "first_issue_name",
    "first_issue_api_url",
    "last_issue_comicvine_id",
    "last_issue_number",
    "last_issue_name",
    "last_issue_api_url",
]


def build_minimal_volume_data_from_embedded_volume(remote_volume):
    remote_volume = remote_volume or {}

    comicvine_id = to_optional_int(remote_volume.get("id"))

    if comicvine_id is None:
        return None

    name = clean_text(remote_volume.get("name"))

    if not name:
        name = f"Unknown Comic Vine Volume {comicvine_id}"

    return {
        "comicvine_id": comicvine_id,
        "name": name,
        "comicvine_url": clean_text(remote_volume.get("site_detail_url")),
        "api_detail_url": clean_text(remote_volume.get("api_detail_url")),
    }


def get_or_create_volume_from_embedded_data(remote_volume, *, dry_run=False):
    volume_data = build_minimal_volume_data_from_embedded_volume(remote_volume)

    if not volume_data:
        return None, False, []

    existing_volume = ComicVolume.objects.filter(
        comicvine_id=volume_data["comicvine_id"]
    ).first()

    if existing_volume:
        update_fields = get_minimal_volume_update_fields(existing_volume, volume_data)

        if update_fields and not dry_run:
            with transaction.atomic():
                locked_volume = ComicVolume.objects.select_for_update().get(
                    id=existing_volume.id
                )
                update_fields = get_minimal_volume_update_fields(locked_volume, volume_data)

                for field_name in update_fields:
                    setattr(locked_volume, field_name, volume_data[field_name])

                if update_fields:
                    locked_volume.save(update_fields=update_fields)
                    existing_volume = locked_volume

        return existing_volume, False, update_fields

    if dry_run:
        return None, True, []

    with transaction.atomic():
        volume = ComicVolume.objects.create(**volume_data)

    return volume, True, []


def get_minimal_volume_update_fields(local_volume, volume_data):
    update_fields = []

    for field_name in ["name", "comicvine_url", "api_detail_url"]:
        new_value = volume_data.get(field_name)

        if not has_usable_value(new_value):
            continue

        current_value = getattr(local_volume, field_name)

        if is_missing_value(current_value):
            update_fields.append(field_name)

    return update_fields


def build_volume_list_data(remote_volume):
    publisher = remote_volume.get("publisher") or {}
    first_issue = remote_volume.get("first_issue") or {}
    last_issue = remote_volume.get("last_issue") or {}

    image_data = image_data_from_remote(remote_volume.get("image"))
    display_image_url = choose_display_image_url(image_data)

    volume_data = {
        "comicvine_id": to_optional_int(remote_volume.get("id")),
        "name": clean_text(remote_volume.get("name")),
        "publisher": clean_text(publisher.get("name")),
        "publisher_comicvine_id": to_optional_int(publisher.get("id")),
        "publisher_api_detail_url": clean_text(publisher.get("api_detail_url")),
        "start_year": clean_text(remote_volume.get("start_year")),
        "count_of_issues": to_optional_int(remote_volume.get("count_of_issues")),
        "date_added": parse_comicvine_datetime(remote_volume.get("date_added")),
        "date_last_updated": parse_comicvine_datetime(remote_volume.get("date_last_updated")),
        "comicvine_url": clean_text(remote_volume.get("site_detail_url")),
        "api_detail_url": clean_text(remote_volume.get("api_detail_url")),
        "aliases": clean_text(remote_volume.get("aliases")),
        "deck": clean_text(remote_volume.get("deck")),
        "description": clean_text(remote_volume.get("description")),
        "first_issue_comicvine_id": to_optional_int(first_issue.get("id")),
        "first_issue_number": clean_text(first_issue.get("issue_number")),
        "first_issue_name": clean_text(first_issue.get("name")),
        "first_issue_api_url": clean_text(first_issue.get("api_detail_url")),
        "last_issue_comicvine_id": to_optional_int(last_issue.get("id")),
        "last_issue_number": clean_text(last_issue.get("issue_number")),
        "last_issue_name": clean_text(last_issue.get("name")),
        "last_issue_api_url": clean_text(last_issue.get("api_detail_url")),
        **image_data,
    }

    volume_data["display_image_url"] = display_image_url

    if display_image_url:
        volume_data["display_image_source"] = ComicVolume.IMAGE_SOURCE_COMICVINE_VOLUME
    else:
        volume_data["display_image_source"] = ComicVolume.IMAGE_SOURCE_UNKNOWN

    return volume_data


def save_volume_list_data(remote_volume, *, overwrite_existing=True, dry_run=False):
    volume_data = build_volume_list_data(remote_volume)
    comicvine_id = volume_data.get("comicvine_id")

    if comicvine_id is None:
        return "skipped", None, []

    local_volume = ComicVolume.objects.filter(comicvine_id=comicvine_id).first()

    if not local_volume:
        if dry_run:
            return "created", None, []

        create_data = {
            "comicvine_id": comicvine_id,
            "name": volume_data["name"] or f"Unknown Comic Vine Volume {comicvine_id}",
        }

        for field_name in VOLUME_LIST_UPDATE_FIELDS:
            if field_name in volume_data and has_usable_value(volume_data[field_name]):
                create_data[field_name] = volume_data[field_name]

        with transaction.atomic():
            local_volume = ComicVolume.objects.create(**create_data)

        return "created", local_volume, list(create_data.keys())

    update_fields = get_volume_list_update_fields(
        local_volume=local_volume,
        volume_data=volume_data,
        overwrite_existing=overwrite_existing,
    )

    if not update_fields:
        return "unchanged", local_volume, []

    if dry_run:
        return "updated", local_volume, update_fields

    with transaction.atomic():
        locked_volume = ComicVolume.objects.select_for_update().get(id=local_volume.id)
        update_fields = get_volume_list_update_fields(
            local_volume=locked_volume,
            volume_data=volume_data,
            overwrite_existing=overwrite_existing,
        )

        if not update_fields:
            return "unchanged", locked_volume, []

        for field_name in update_fields:
            setattr(locked_volume, field_name, volume_data[field_name])

        locked_volume.save(update_fields=update_fields)

    return "updated", locked_volume, update_fields


def save_volumes_from_list_data(
    remote_volumes,
    *,
    overwrite_existing=True,
    dry_run=False,
):
    result = VolumeListSaveResult()

    for remote_volume in remote_volumes or []:
        result.volumes_seen += 1

        action, _volume, update_fields = save_volume_list_data(
            remote_volume,
            overwrite_existing=overwrite_existing,
            dry_run=dry_run,
        )

        if action == "created":
            result.volumes_created += 1
            result.record_volume_fields(update_fields)
        elif action == "updated":
            result.volumes_updated += 1
            result.record_volume_fields(update_fields)
        elif action == "unchanged":
            result.volumes_unchanged += 1
        else:
            result.volumes_skipped += 1

    return result


def get_volume_list_update_fields(*, local_volume, volume_data, overwrite_existing):
    update_fields = []

    for field_name in VOLUME_LIST_UPDATE_FIELDS:
        if field_name not in volume_data:
            continue

        new_value = volume_data[field_name]

        if not has_usable_value(new_value):
            continue

        current_value = getattr(local_volume, field_name)

        if overwrite_existing:
            if current_value != new_value:
                update_fields.append(field_name)
        elif is_missing_value(current_value):
            update_fields.append(field_name)

    if "display_image_url" not in update_fields and "display_image_source" in update_fields:
        update_fields.remove("display_image_source")

    return update_fields


def get_volumes_missing_list_data_queryset():
    missing_list_data_filter = (
        Q(publisher="")
        | Q(start_year="")
        | Q(count_of_issues__isnull=True)
        | Q(date_added__isnull=True)
        | Q(date_last_updated__isnull=True)
        | Q(comicvine_url="")
        | Q(api_detail_url="")
        | Q(first_issue_comicvine_id__isnull=True)
        | Q(last_issue_comicvine_id__isnull=True)
        | Q(comicvine_image_original_url="")
    )

    return ComicVolume.objects.filter(missing_list_data_filter).order_by("id")


def refresh_volumes_by_ids(
    *,
    session,
    api_key,
    volume_ids,
    overwrite_existing=False,
    dry_run=False,
):
    response_data = fetch_volumes_by_ids(
        session,
        api_key,
        volume_ids=volume_ids,
        fields=VOLUME_LIST_FIELDS,
    )

    remote_volumes = response_data.get("results") or []

    return save_volumes_from_list_data(
        remote_volumes,
        overwrite_existing=overwrite_existing,
        dry_run=dry_run,
    )


def refresh_missing_volume_list_data(
    *,
    session,
    api_key,
    volume_limit=None,
    batch_size=100,
    request_delay=0,
    dry_run=False,
    volume_ids=None,
    progress_callback=None,
):
    validate_volume_refresh_options(
        volume_limit=volume_limit,
        batch_size=batch_size,
        request_delay=request_delay,
    )

    if volume_ids:
        volumes_queryset = ComicVolume.objects.filter(
            comicvine_id__in=volume_ids,
        ).order_by("id")
    else:
        volumes_queryset = get_volumes_missing_list_data_queryset()

    volumes_matching_selection = volumes_queryset.count()

    if volume_limit is not None:
        local_volumes = list(volumes_queryset[:volume_limit])
    else:
        local_volumes = list(volumes_queryset)

    result = VolumeBatchRefreshResult(
        volumes_matching_selection=volumes_matching_selection,
        volumes_selected_this_run=len(local_volumes),
    )

    if not local_volumes:
        return result

    batches = chunk_list(local_volumes, batch_size)

    for batch_number, local_volume_batch in enumerate(batches, start=1):
        result.volume_batches_requested += 1

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

        result.api_requests_made += 1

        remote_volumes = response_data.get("results") or []
        remote_volumes_by_comicvine_id = {
            remote_volume.get("id"): remote_volume
            for remote_volume in remote_volumes
            if remote_volume.get("id")
        }

        result.volumes_returned_by_comicvine += len(remote_volumes_by_comicvine_id)

        unexpected_ids = sorted(
            set(remote_volumes_by_comicvine_id.keys()) - set(requested_volume_ids)
        )

        if unexpected_ids:
            result.unexpected_volumes_returned += len(unexpected_ids)

        for local_volume in local_volume_batch:
            result.volumes_checked += 1

            remote_volume = remote_volumes_by_comicvine_id.get(local_volume.comicvine_id)

            if not remote_volume:
                result.volumes_not_returned_by_comicvine += 1
                continue

            volume_data = build_volume_list_data(remote_volume)
            update_fields = get_volume_list_update_fields(
                local_volume=local_volume,
                volume_data=volume_data,
                overwrite_existing=False,
            )

            if not update_fields:
                result.volumes_unchanged += 1
                continue

            if dry_run:
                saved_update_fields = update_fields
            else:
                _action, _volume, saved_update_fields = save_volume_list_data(
                    remote_volume,
                    overwrite_existing=False,
                    dry_run=False,
                )

            if saved_update_fields:
                result.volumes_updated += 1
                result.record_field_updates(saved_update_fields)
            else:
                result.volumes_unchanged += 1

        if progress_callback:
            progress_callback(
                result=result,
                batch_number=batch_number,
                batch_count=len(batches),
            )

        sleep_if_needed(request_delay)

    return result


def validate_volume_refresh_options(volume_limit, batch_size, request_delay):
    if volume_limit is not None and volume_limit < 1:
        raise ValueError("volume_limit must be at least 1 when provided.")

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    if batch_size > 100:
        raise ValueError("batch_size cannot be above 100 for Comic Vine list requests.")

    if request_delay < 0:
        raise ValueError("request_delay cannot be negative.")


def chunk_list(values, chunk_size):
    return [
        values[index:index + chunk_size]
        for index in range(0, len(values), chunk_size)
    ]


def sleep_if_needed(request_delay):
    if request_delay > 0:
        time.sleep(request_delay)