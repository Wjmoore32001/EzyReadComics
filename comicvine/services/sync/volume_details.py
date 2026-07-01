from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from comicvine.api.client import ComicVineAPIError, fetch_volume_detail
from comicvine.api.fields import VOLUME_DETAIL_FIELDS
from comicvine.api.parsing import to_optional_int
from comicvine.models import ComicVineVolume
from comicvine.services.sync.credits import sync_volume_person_credits
from comicvine.services.sync.volumes import save_volume_list_data


EXPECTED_DETAIL_SYNC_FIELDS = ["people"]


def select_volumes_to_hydrate(*, volume_ids, limit):
    if volume_ids:
        queryset = ComicVineVolume.objects.filter(
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
        ComicVineVolume.objects.filter(comicvine_id__isnull=False)
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
        locked_volume = ComicVineVolume.objects.select_for_update().get(id=volume.id)

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