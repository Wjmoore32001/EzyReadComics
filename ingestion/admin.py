from django.contrib import admin

from ingestion.models import ComicVineVolumeCandidate


@admin.register(ComicVineVolumeCandidate)
class ComicVineVolumeCandidateAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "publisher_name",
        "start_year",
        "source_issue_count",
        "first_issue_date",
        "last_issue_date",
        "suggested_kind",
        "reviewed_kind",
        "review_status",
        "catalog_run",
        "catalog_volume",
        "analyzed_at",
        "reviewed_at",
    ]
    list_filter = [
        "publisher_name",
        "review_status",
        "suggested_kind",
        "reviewed_kind",
        "start_year",
    ]
    search_fields = [
        "title",
        "publisher_name",
        "start_year",
        "review_reason",
        "comicvine_volume__name",
        "comicvine_volume__comicvine_id",
        "catalog_run__title",
        "catalog_volume__title",
    ]
    raw_id_fields = [
        "comicvine_volume",
        "catalog_run",
        "catalog_volume",
    ]
    readonly_fields = [
        "publisher_name",
        "title",
        "start_year",
        "source_issue_count",
        "first_issue_date",
        "last_issue_date",
        "first_issue_number",
        "last_issue_number",
        "suggested_kind",
        "review_reason",
        "analyzed_at",
        "created_at",
        "updated_at",
    ]

    fieldsets = [
        (
            "Source Comic Vine volume",
            {
                "fields": [
                    "comicvine_volume",
                    "publisher_name",
                    "title",
                    "start_year",
                    "source_issue_count",
                    "first_issue_date",
                    "last_issue_date",
                    "first_issue_number",
                    "last_issue_number",
                ]
            },
        ),
        (
            "Review",
            {
                "fields": [
                    "suggested_kind",
                    "reviewed_kind",
                    "review_status",
                    "review_reason",
                    "reviewed_at",
                ]
            },
        ),
        (
            "Catalog links",
            {
                "fields": [
                    "catalog_run",
                    "catalog_volume",
                ]
            },
        ),
        (
            "Timestamps",
            {
                "fields": [
                    "analyzed_at",
                    "created_at",
                    "updated_at",
                ]
            },
        ),
    ]