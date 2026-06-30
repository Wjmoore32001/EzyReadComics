from django.db import transaction

from comics.comicvine.parsing import associated_image_data_from_remote, clean_text, to_optional_int
from comics.importers.results import RelationshipSyncResult
from comics.models import (
    ComicCharacter,
    ComicConcept,
    ComicIssueAssociatedImage,
    ComicIssueCharacterLink,
    ComicIssueConceptLink,
    ComicIssueLocationLink,
    ComicIssueObjectLink,
    ComicIssueRelationship,
    ComicIssueStoryArcLink,
    ComicIssueTeamLink,
    ComicLocation,
    ComicObject,
    ComicStoryArc,
    ComicTeam,
)


RELATIONSHIP_FIELD_MAP = [
    {
        "remote_field": "character_credits",
        "entity_model": ComicCharacter,
        "link_model": ComicIssueCharacterLink,
        "link_field_name": "character",
        "relation_type": ComicIssueRelationship.RELATION_CREDIT,
    },
    {
        "remote_field": "first_appearance_characters",
        "entity_model": ComicCharacter,
        "link_model": ComicIssueCharacterLink,
        "link_field_name": "character",
        "relation_type": ComicIssueRelationship.RELATION_FIRST_APPEARANCE,
    },
    {
        "remote_field": "character_died_in",
        "entity_model": ComicCharacter,
        "link_model": ComicIssueCharacterLink,
        "link_field_name": "character",
        "relation_type": ComicIssueRelationship.RELATION_DIED_IN,
    },
    {
        "remote_field": "team_credits",
        "entity_model": ComicTeam,
        "link_model": ComicIssueTeamLink,
        "link_field_name": "team",
        "relation_type": ComicIssueRelationship.RELATION_CREDIT,
    },
    {
        "remote_field": "first_appearance_teams",
        "entity_model": ComicTeam,
        "link_model": ComicIssueTeamLink,
        "link_field_name": "team",
        "relation_type": ComicIssueRelationship.RELATION_FIRST_APPEARANCE,
    },
    {
        "remote_field": "team_disbanded_in",
        "entity_model": ComicTeam,
        "link_model": ComicIssueTeamLink,
        "link_field_name": "team",
        "relation_type": ComicIssueRelationship.RELATION_DISBANDED_IN,
    },
    {
        "remote_field": "location_credits",
        "entity_model": ComicLocation,
        "link_model": ComicIssueLocationLink,
        "link_field_name": "location",
        "relation_type": ComicIssueRelationship.RELATION_CREDIT,
    },
    {
        "remote_field": "first_appearance_locations",
        "entity_model": ComicLocation,
        "link_model": ComicIssueLocationLink,
        "link_field_name": "location",
        "relation_type": ComicIssueRelationship.RELATION_FIRST_APPEARANCE,
    },
    {
        "remote_field": "concept_credits",
        "entity_model": ComicConcept,
        "link_model": ComicIssueConceptLink,
        "link_field_name": "concept",
        "relation_type": ComicIssueRelationship.RELATION_CREDIT,
    },
    {
        "remote_field": "first_appearance_concepts",
        "entity_model": ComicConcept,
        "link_model": ComicIssueConceptLink,
        "link_field_name": "concept",
        "relation_type": ComicIssueRelationship.RELATION_FIRST_APPEARANCE,
    },
    {
        "remote_field": "object_credits",
        "entity_model": ComicObject,
        "link_model": ComicIssueObjectLink,
        "link_field_name": "comic_object",
        "relation_type": ComicIssueRelationship.RELATION_CREDIT,
    },
    {
        "remote_field": "first_appearance_objects",
        "entity_model": ComicObject,
        "link_model": ComicIssueObjectLink,
        "link_field_name": "comic_object",
        "relation_type": ComicIssueRelationship.RELATION_FIRST_APPEARANCE,
    },
    {
        "remote_field": "story_arc_credits",
        "entity_model": ComicStoryArc,
        "link_model": ComicIssueStoryArcLink,
        "link_field_name": "story_arc",
        "relation_type": ComicIssueRelationship.RELATION_CREDIT,
    },
    {
        "remote_field": "first_appearance_storyarcs",
        "entity_model": ComicStoryArc,
        "link_model": ComicIssueStoryArcLink,
        "link_field_name": "story_arc",
        "relation_type": ComicIssueRelationship.RELATION_FIRST_APPEARANCE,
    },
]


def sync_issue_relationships(issue, remote_issue_detail, *, dry_run=False):
    result = RelationshipSyncResult()

    for relationship_config in RELATIONSHIP_FIELD_MAP:
        remote_field = relationship_config["remote_field"]

        # Safety rule:
        # If the field is missing entirely, do not delete existing local rows.
        # If the field is present as an empty list, then Comic Vine is saying
        # there are none, so syncing to empty is allowed.
        if remote_field not in remote_issue_detail:
            result.missing_remote_fields_skipped += 1
            continue

        sync_result = sync_single_issue_relationship_type(
            issue=issue,
            remote_items=remote_issue_detail.get(remote_field),
            entity_model=relationship_config["entity_model"],
            link_model=relationship_config["link_model"],
            link_field_name=relationship_config["link_field_name"],
            relation_type=relationship_config["relation_type"],
            dry_run=dry_run,
        )

        merge_relationship_results(result, sync_result)

    if "associated_images" in remote_issue_detail:
        image_result = sync_issue_associated_images(
            issue=issue,
            remote_images=remote_issue_detail.get("associated_images"),
            dry_run=dry_run,
        )

        merge_relationship_results(result, image_result)
    else:
        result.missing_remote_fields_skipped += 1

    return result


def sync_single_issue_relationship_type(
    *,
    issue,
    remote_items,
    entity_model,
    link_model,
    link_field_name,
    relation_type,
    dry_run=False,
):
    result = RelationshipSyncResult()

    if remote_items is None:
        result.missing_remote_fields_skipped += 1
        return result

    desired_entity_ids = set()

    for remote_item in remote_items:
        result.remote_items_seen += 1

        entity_id = to_optional_int(remote_item.get("id"))

        if entity_id is None:
            result.skipped_items += 1
            continue

        desired_entity_ids.add(entity_id)

    existing_links = link_model.objects.filter(
        issue=issue,
        relation_type=relation_type,
    ).select_related(link_field_name)

    existing_entity_ids = {
        getattr(existing_link, link_field_name).comicvine_id
        for existing_link in existing_links
    }

    if dry_run:
        result.links_created = len(desired_entity_ids - existing_entity_ids)
        result.links_deleted = len(existing_entity_ids - desired_entity_ids)
        result.links_kept = len(existing_entity_ids & desired_entity_ids)
        return result

    with transaction.atomic():
        existing_links = link_model.objects.select_for_update().filter(
            issue=issue,
            relation_type=relation_type,
        ).select_related(link_field_name)

        for existing_link in existing_links:
            entity = getattr(existing_link, link_field_name)

            if entity.comicvine_id not in desired_entity_ids:
                existing_link.delete()
                result.links_deleted += 1

        for remote_item in remote_items:
            entity_id = to_optional_int(remote_item.get("id"))

            if entity_id is None:
                continue

            entity, entity_created, entity_updated = get_or_create_named_entity(
                entity_model,
                remote_item,
            )

            if entity is None:
                result.skipped_items += 1
                continue

            if entity_created:
                result.entities_created += 1
            elif entity_updated:
                result.entities_updated += 1

            link_kwargs = {
                "issue": issue,
                link_field_name: entity,
                "relation_type": relation_type,
            }

            _link, link_created = link_model.objects.get_or_create(**link_kwargs)

            if link_created:
                result.links_created += 1
            else:
                result.links_kept += 1

    return result


def get_or_create_named_entity(entity_model, remote_item):
    entity_id = to_optional_int(remote_item.get("id"))

    if entity_id is None:
        return None, False, False

    entity_name = clean_text(remote_item.get("name"))

    if not entity_name:
        entity_name = f"Unknown Comic Vine {entity_model.__name__} {entity_id}"

    defaults = {
        "name": entity_name,
        "api_detail_url": clean_text(remote_item.get("api_detail_url")),
        "comicvine_url": clean_text(remote_item.get("site_detail_url")),
    }

    entity, created = entity_model.objects.get_or_create(
        comicvine_id=entity_id,
        defaults=defaults,
    )

    updated = False

    if not created:
        update_fields = []

        for field_name, new_value in defaults.items():
            if new_value and getattr(entity, field_name) != new_value:
                setattr(entity, field_name, new_value)
                update_fields.append(field_name)

        if update_fields:
            entity.save(update_fields=update_fields)
            updated = True

    return entity, created, updated


def sync_issue_associated_images(issue, remote_images, *, dry_run=False):
    result = RelationshipSyncResult()

    # Safety rule:
    # Missing associated_images field means "do not touch existing images."
    # Present empty list means "delete existing associated images."
    if remote_images is None:
        result.missing_remote_fields_skipped += 1
        return result

    existing_count = ComicIssueAssociatedImage.objects.filter(issue=issue).count()

    if dry_run:
        result.associated_images_deleted = existing_count
        result.associated_images_created = count_usable_associated_images(remote_images)
        return result

    with transaction.atomic():
        deleted_count, _deleted_by_type = ComicIssueAssociatedImage.objects.filter(
            issue=issue
        ).delete()

        result.associated_images_deleted = deleted_count

        for position, remote_image in enumerate(remote_images, start=1):
            image_data = associated_image_data_from_remote(remote_image)

            if not associated_image_is_usable(image_data):
                result.skipped_items += 1
                continue

            ComicIssueAssociatedImage.objects.create(
                issue=issue,
                position=position,
                **image_data,
            )

            result.associated_images_created += 1

    return result


def associated_image_is_usable(image_data):
    return any(
        [
            image_data["original_url"],
            image_data["super_url"],
            image_data["screen_large_url"],
            image_data["medium_url"],
            image_data["small_url"],
            image_data["thumb_url"],
        ]
    )


def count_usable_associated_images(remote_images):
    usable_count = 0

    for remote_image in remote_images:
        image_data = associated_image_data_from_remote(remote_image)

        if associated_image_is_usable(image_data):
            usable_count += 1

    return usable_count


def merge_relationship_results(target, source):
    target.remote_items_seen += source.remote_items_seen
    target.entities_created += source.entities_created
    target.entities_updated += source.entities_updated
    target.links_created += source.links_created
    target.links_deleted += source.links_deleted
    target.links_kept += source.links_kept
    target.associated_images_created += source.associated_images_created
    target.associated_images_deleted += source.associated_images_deleted
    target.skipped_items += source.skipped_items
    target.missing_remote_fields_skipped += source.missing_remote_fields_skipped