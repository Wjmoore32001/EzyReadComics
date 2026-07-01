ISSUE_LIST_FIELDS = [
    "aliases",
    "api_detail_url",
    "associated_images",
    "cover_date",
    "date_added",
    "date_last_updated",
    "deck",
    "description",
    "has_staff_review",
    "id",
    "image",
    "issue_number",
    "name",
    "site_detail_url",
    "store_date",
    "volume",
]

ISSUE_DETAIL_RELATIONSHIP_FIELDS = [
    "character_credits",
    "character_died_in",
    "concept_credits",
    "first_appearance_characters",
    "first_appearance_concepts",
    "first_appearance_locations",
    "first_appearance_objects",
    "first_appearance_storyarcs",
    "first_appearance_teams",
    "location_credits",
    "object_credits",
    "person_credits",
    "story_arc_credits",
    "team_credits",
    "team_disbanded_in",
]

ISSUE_DETAIL_FIELDS = list(
    dict.fromkeys(
        ISSUE_LIST_FIELDS
        + ISSUE_DETAIL_RELATIONSHIP_FIELDS
    )
)

VOLUME_LIST_FIELDS = [
    "aliases",
    "api_detail_url",
    "count_of_issues",
    "date_added",
    "date_last_updated",
    "deck",
    "description",
    "first_issue",
    "id",
    "image",
    "last_issue",
    "name",
    "publisher",
    "site_detail_url",
    "start_year",
]

VOLUME_DETAIL_FIELDS = list(
    dict.fromkeys(
        VOLUME_LIST_FIELDS
        + [
            "people",
        ]
    )
)