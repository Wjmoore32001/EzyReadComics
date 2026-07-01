from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from comicvine.api.client import ComicVineAPIError, fetch_issue_detail
from comicvine.api.fields import ISSUE_DETAIL_FIELDS, ISSUE_DETAIL_RELATIONSHIP_FIELDS
from comicvine.api.parsing import to_optional_int
from comicvine.models import ComicVineIssue
from comicvine.services.sync.credits import sync_issue_person_credits
from comicvine.services.sync.issues import save_issue_list_data
from comicvine.services.sync.relationships import sync_issue_relationships


EXPECTED_DETAIL_SYNC_FIELDS = sorted(
    set(ISSUE_DETAIL_RELATIONSHIP_FIELDS + ["associated_images"])
)


def select_issues_to_hydrate(*, issue_ids, limit):
    if issue_ids:
        queryset = ComicVineIssue.objects.filter(
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
        ComicVineIssue.objects.filter(comicvine_id__isnull=False)
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
        locked_issue = ComicVineIssue.objects.select_for_update().get(id=issue.id)

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