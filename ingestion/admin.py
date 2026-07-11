from django.contrib import admin

from ingestion.models import (
    ComicVineCollectedEditionCandidate,
    ComicVineCollectedEditionIssue,
    ComicVineVolumeCandidate,
    MarvelCatalogIssueSource,
    MarvelCatalogRunSource,
    MarvelCatalogVolumeSource,
)


class ComicVineCollectedEditionIssueInline(admin.TabularInline):
    model = ComicVineCollectedEditionIssue
    extra = 0
    fields = [
        "issue_order",
        "primary_run",
        "source_run_candidate",
        "source_issue",
        "reference_text",
    ]
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(ComicVineVolumeCandidate)
class ComicVineVolumeCandidateAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "publisher_name",
        "start_year",
        "source_issue_count",
        "first_issue_date",
        "last_issue_date",
        "analysis_status",
        "catalog_status",
        "review_status",
        "catalog_run",
        "analyzed_at",
        "source_changed_at",
    ]
    list_filter = [
        "publisher_name",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "review_status",
        "source_date_type",
        "start_year",
        "analysis_version",
    ]
    search_fields = [
        "title",
        "normalized_title",
        "publisher_name",
        "start_year",
        "analysis_reason",
        "review_reason",
        "comicvine_volume__name",
        "comicvine_volume__comicvine_id",
        "catalog_run__title",
    ]
    raw_id_fields = ["comicvine_volume", "catalog_run"]
    readonly_fields = [
        "publisher_name",
        "title",
        "normalized_title",
        "start_year",
        "source_issue_count",
        "source_date_type",
        "first_issue_date",
        "last_issue_date",
        "first_issue_number",
        "last_issue_number",
        "source_volume_date_last_updated",
        "source_fingerprint",
        "analysis_version",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "analysis_reason",
        "analyzed_at",
        "source_changed_at",
        "catalog_applied_at",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (
            "Comic Vine run source",
            {
                "fields": [
                    "comicvine_volume",
                    "publisher_name",
                    "title",
                    "normalized_title",
                    "start_year",
                    "source_issue_count",
                    "source_date_type",
                    "first_issue_date",
                    "last_issue_date",
                    "first_issue_number",
                    "last_issue_number",
                    "source_volume_date_last_updated",
                    "source_fingerprint",
                ]
            },
        ),
        (
            "Analysis",
            {
                "fields": [
                    "analysis_version",
                    "analysis_status",
                    "catalog_status",
                    "determination_source",
                    "analysis_reason",
                    "analyzed_at",
                    "source_changed_at",
                    "catalog_applied_at",
                ]
            },
        ),
        (
            "Review and catalog",
            {
                "fields": [
                    "review_status",
                    "review_reason",
                    "reviewed_at",
                    "catalog_run",
                ]
            },
        ),
        (
            "Audit",
            {"fields": ["created_at", "updated_at"]},
        ),
    ]


@admin.register(ComicVineCollectedEditionCandidate)
class ComicVineCollectedEditionCandidateAdmin(admin.ModelAdmin):
    list_display = [
        "source_title",
        "publisher_name",
        "volume_number",
        "title",
        "release_date",
        "source_issue_count",
        "analysis_status",
        "catalog_status",
        "proposed_parent_run_candidate",
        "catalog_volume",
        "analyzed_at",
        "source_changed_at",
    ]
    list_filter = [
        "publisher_name",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "review_status",
        "analysis_version",
    ]
    search_fields = [
        "source_title",
        "title",
        "volume_number",
        "collecting_text",
        "unresolved_reference_text",
        "analysis_reason",
        "comicvine_issue__comicvine_id",
        "source_collection_volume__name",
        "source_collection_volume__comicvine_id",
        "proposed_parent_run_candidate__title",
        "catalog_volume__title",
    ]
    raw_id_fields = [
        "comicvine_issue",
        "source_collection_volume",
        "proposed_parent_run_candidate",
        "catalog_volume",
    ]
    readonly_fields = [
        "publisher_name",
        "source_title",
        "volume_number",
        "title",
        "release_date",
        "collecting_text",
        "unresolved_reference_text",
        "source_reference_count",
        "source_issue_count",
        "primary_first_issue_number",
        "primary_last_issue_number",
        "source_issue_date_last_updated",
        "source_fingerprint",
        "analysis_version",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "analysis_reason",
        "analyzed_at",
        "source_changed_at",
        "catalog_applied_at",
        "created_at",
        "updated_at",
    ]
    inlines = [ComicVineCollectedEditionIssueInline]
    fieldsets = [
        (
            "Comic Vine collected-edition source",
            {
                "fields": [
                    "comicvine_issue",
                    "source_collection_volume",
                    "publisher_name",
                    "source_title",
                    "volume_number",
                    "title",
                    "release_date",
                    "collecting_text",
                    "source_issue_date_last_updated",
                    "source_fingerprint",
                ]
            },
        ),
        (
            "Resolved contents",
            {
                "fields": [
                    "proposed_parent_run_candidate",
                    "source_reference_count",
                    "source_issue_count",
                    "primary_first_issue_number",
                    "primary_last_issue_number",
                    "unresolved_reference_text",
                ]
            },
        ),
        (
            "Analysis",
            {
                "fields": [
                    "analysis_version",
                    "analysis_status",
                    "catalog_status",
                    "determination_source",
                    "analysis_reason",
                    "analyzed_at",
                    "source_changed_at",
                    "catalog_applied_at",
                ]
            },
        ),
        (
            "Review and catalog",
            {
                "fields": [
                    "review_status",
                    "review_reason",
                    "reviewed_at",
                    "catalog_volume",
                ]
            },
        ),
        (
            "Audit",
            {"fields": ["created_at", "updated_at"]},
        ),
    ]


@admin.register(ComicVineCollectedEditionIssue)
class ComicVineCollectedEditionIssueAdmin(admin.ModelAdmin):
    list_display = [
        "candidate",
        "issue_order",
        "primary_run",
        "source_run_candidate",
        "source_issue",
    ]
    list_filter = ["primary_run"]
    search_fields = [
        "candidate__source_title",
        "source_run_candidate__title",
        "source_issue__comicvine_id",
        "source_issue__issue_number",
        "reference_text",
    ]
    raw_id_fields = ["candidate", "source_run_candidate", "source_issue"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MarvelCatalogRunSource)
class MarvelCatalogRunSourceAdmin(admin.ModelAdmin):
    list_display = [
        "catalog_run",
        "comicvine_volume",
        "candidate",
        "confirmed_at",
        "last_processed_at",
        "source_changed_at",
    ]
    search_fields = [
        "catalog_run__title",
        "comicvine_volume__name",
        "comicvine_volume__comicvine_id",
    ]
    raw_id_fields = ["catalog_run", "comicvine_volume", "candidate"]


@admin.register(MarvelCatalogIssueSource)
class MarvelCatalogIssueSourceAdmin(admin.ModelAdmin):
    list_display = [
        "catalog_issue",
        "catalog_run",
        "comicvine_issue",
        "comicvine_volume",
        "last_processed_at",
        "source_changed_at",
    ]
    search_fields = [
        "catalog_run__title",
        "catalog_issue__issue_number",
        "comicvine_issue__comicvine_id",
    ]
    raw_id_fields = [
        "catalog_issue",
        "catalog_run",
        "comicvine_issue",
        "comicvine_volume",
        "run_source",
    ]


@admin.register(MarvelCatalogVolumeSource)
class MarvelCatalogVolumeSourceAdmin(admin.ModelAdmin):
    list_display = [
        "catalog_volume",
        "catalog_run",
        "comicvine_issue",
        "candidate",
        "confirmed_at",
        "last_processed_at",
        "source_changed_at",
    ]
    search_fields = [
        "catalog_run__title",
        "catalog_volume__title",
        "comicvine_issue__comicvine_id",
    ]
    raw_id_fields = [
        "catalog_volume",
        "catalog_run",
        "comicvine_issue",
        "candidate",
    ]