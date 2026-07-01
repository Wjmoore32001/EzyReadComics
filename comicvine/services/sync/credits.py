from django.db import transaction

from comicvine.api.parsing import clean_text, split_comicvine_role_string, to_optional_int
from comicvine.models import (
    ComicVineCreditRole,
    ComicVineIssuePersonCredit,
    ComicVinePerson,
    ComicVineVolumePersonCredit,
)
from comicvine.services.sync.results import CreditSyncResult


def get_or_create_person_from_credit(remote_person):
    person_id = to_optional_int(remote_person.get("id"))

    if person_id is None:
        return None, False, False

    person_name = clean_text(remote_person.get("name"))

    if not person_name:
        person_name = f"Unknown Comic Vine Person {person_id}"

    defaults = {
        "name": person_name,
        "api_detail_url": clean_text(remote_person.get("api_detail_url")),
        "comicvine_url": clean_text(remote_person.get("site_detail_url")),
    }

    person, created = ComicVinePerson.objects.get_or_create(
        comicvine_id=person_id,
        defaults=defaults,
    )

    updated = False

    if not created:
        update_fields = []

        for field_name, new_value in defaults.items():
            if new_value and getattr(person, field_name) != new_value:
                setattr(person, field_name, new_value)
                update_fields.append(field_name)

        if update_fields:
            person.save(update_fields=update_fields)
            updated = True

    return person, created, updated


def get_or_create_role(role_name):
    role_name = clean_text(role_name).lower()

    if not role_name:
        return None, False

    role, created = ComicVineCreditRole.objects.get_or_create(name=role_name)

    return role, created


def sync_issue_person_credits(issue, remote_person_credits, *, dry_run=False):
    result = CreditSyncResult()

    # Missing field means "Comic Vine did not give us this data in the response."
    # That must not delete existing local credits.
    #
    # Present empty list means "Comic Vine says there are no credits."
    # That is allowed to sync/delete existing local credits.
    if remote_person_credits is None:
        result.missing_remote_fields_skipped += 1
        return result

    desired_credit_keys = set()

    for remote_person_credit in remote_person_credits:
        result.remote_items_seen += 1

        person_id = to_optional_int(remote_person_credit.get("id"))
        role_names = split_comicvine_role_string(remote_person_credit.get("role"))

        if person_id is None or not role_names:
            result.skipped_items += 1
            continue

        for role_name in role_names:
            desired_credit_keys.add((person_id, role_name))

    existing_credit_keys = set(
        ComicVineIssuePersonCredit.objects.filter(issue=issue)
        .select_related("person", "role")
        .values_list("person__comicvine_id", "role__name")
    )

    if dry_run:
        result.credits_created = len(desired_credit_keys - existing_credit_keys)
        result.credits_deleted = len(existing_credit_keys - desired_credit_keys)
        result.credits_kept = len(existing_credit_keys & desired_credit_keys)
        return result

    with transaction.atomic():
        existing_credits = (
            ComicVineIssuePersonCredit.objects.select_for_update()
            .filter(issue=issue)
            .select_related("person", "role")
        )

        for existing_credit in existing_credits:
            key = (
                existing_credit.person.comicvine_id,
                existing_credit.role.name,
            )

            if key not in desired_credit_keys:
                existing_credit.delete()
                result.credits_deleted += 1

        for remote_person_credit in remote_person_credits:
            person_id = to_optional_int(remote_person_credit.get("id"))
            role_names = split_comicvine_role_string(remote_person_credit.get("role"))

            if person_id is None or not role_names:
                continue

            person, person_created, person_updated = get_or_create_person_from_credit(
                remote_person_credit
            )

            if person is None:
                continue

            if person_created:
                result.people_created += 1
            elif person_updated:
                result.people_updated += 1

            for role_name in role_names:
                role, role_created = get_or_create_role(role_name)

                if role is None:
                    continue

                if role_created:
                    result.roles_created += 1

                credit, created = ComicVineIssuePersonCredit.objects.get_or_create(
                    issue=issue,
                    person=person,
                    role=role,
                    defaults={
                        "api_detail_url": clean_text(remote_person_credit.get("api_detail_url")),
                        "comicvine_url": clean_text(remote_person_credit.get("site_detail_url")),
                    },
                )

                if created:
                    result.credits_created += 1
                else:
                    result.credits_kept += 1

                    update_fields = []

                    api_detail_url = clean_text(remote_person_credit.get("api_detail_url"))
                    comicvine_url = clean_text(remote_person_credit.get("site_detail_url"))

                    if api_detail_url and credit.api_detail_url != api_detail_url:
                        credit.api_detail_url = api_detail_url
                        update_fields.append("api_detail_url")

                    if comicvine_url and credit.comicvine_url != comicvine_url:
                        credit.comicvine_url = comicvine_url
                        update_fields.append("comicvine_url")

                    if update_fields:
                        credit.save(update_fields=update_fields)

    return result


def sync_volume_person_credits(volume, remote_people, *, dry_run=False):
    result = CreditSyncResult()

    # Same safety rule as issue credits.
    # If the "people" field is missing from the volume detail response,
    # do not assume Comic Vine means the volume has no people.
    if remote_people is None:
        result.missing_remote_fields_skipped += 1
        return result

    desired_person_ids = set()

    for remote_person in remote_people:
        result.remote_items_seen += 1

        person_id = to_optional_int(remote_person.get("id"))

        if person_id is None:
            result.skipped_items += 1
            continue

        desired_person_ids.add(person_id)

    existing_person_ids = set(
        ComicVineVolumePersonCredit.objects.filter(volume=volume)
        .select_related("person")
        .values_list("person__comicvine_id", flat=True)
    )

    if dry_run:
        result.credits_created = len(desired_person_ids - existing_person_ids)
        result.credits_deleted = len(existing_person_ids - desired_person_ids)
        result.credits_kept = len(existing_person_ids & desired_person_ids)
        return result

    with transaction.atomic():
        existing_credits = (
            ComicVineVolumePersonCredit.objects.select_for_update()
            .filter(volume=volume)
            .select_related("person")
        )

        for existing_credit in existing_credits:
            if existing_credit.person.comicvine_id not in desired_person_ids:
                existing_credit.delete()
                result.credits_deleted += 1

        for remote_person in remote_people:
            person_id = to_optional_int(remote_person.get("id"))

            if person_id is None:
                continue

            person, person_created, person_updated = get_or_create_person_from_credit(
                remote_person
            )

            if person is None:
                continue

            if person_created:
                result.people_created += 1
            elif person_updated:
                result.people_updated += 1

            credit_count = get_volume_credit_count(remote_person)

            credit, created = ComicVineVolumePersonCredit.objects.get_or_create(
                volume=volume,
                person=person,
                defaults={
                    "credit_count": credit_count,
                    "api_detail_url": clean_text(remote_person.get("api_detail_url")),
                    "comicvine_url": clean_text(remote_person.get("site_detail_url")),
                },
            )

            if created:
                result.credits_created += 1
            else:
                result.credits_kept += 1

                update_fields = []

                api_detail_url = clean_text(remote_person.get("api_detail_url"))
                comicvine_url = clean_text(remote_person.get("site_detail_url"))

                if credit.credit_count != credit_count:
                    credit.credit_count = credit_count
                    update_fields.append("credit_count")

                if api_detail_url and credit.api_detail_url != api_detail_url:
                    credit.api_detail_url = api_detail_url
                    update_fields.append("api_detail_url")

                if comicvine_url and credit.comicvine_url != comicvine_url:
                    credit.comicvine_url = comicvine_url
                    update_fields.append("comicvine_url")

                if update_fields:
                    credit.save(update_fields=update_fields)

    return result


def get_volume_credit_count(remote_person):
    for field_name in [
        "count",
        "credit_count",
        "issue_count",
        "count_of_issues",
        "count_of_issue_appearances",
    ]:
        value = to_optional_int(remote_person.get(field_name))

        if value is not None:
            return value

    return None