from django.contrib import admin

from ingestion.models import (
    ComicVineVolumeCandidate,
    MarvelCatalogIssueSource,
    MarvelCatalogRunSource,
    MarvelCatalogVolumeSource,
    MarvelIngestionGroup,
    MarvelVolumeContainment,
)


class ComicVineVolumeCandidateInline(admin.TabularInline):
    model = ComicVineVolumeCandidate
    extra = 0
    fields = [
        "comicvine_volume",
        "title",
        "source_issue_count",
        "source_date_type",
        "first_issue_date",
        "last_issue_date",
        "analysis_status",
        "catalog_status",
        "suggested_kind",
        "proposed_parent_run_candidate",
    ]
    readonly_fields = [
        "comicvine_volume",
        "title",
        "source_issue_count",
        "source_date_type",
        "first_issue_date",
        "last_issue_date",
        "analysis_status",
        "catalog_status",
        "suggested_kind",
        "proposed_parent_run_candidate",
    ]
    can_delete = False
    show_change_link = True


class MarvelVolumeContainmentInline(admin.TabularInline):
    model = MarvelVolumeContainment
    extra = 0
    fields = [
        "run_candidate",
        "collected_volume_candidate",
        "date_type",
        "collected_first_issue_date",
        "collected_last_issue_date",
        "status",
        "determination_source",
    ]
    readonly_fields = [
        "run_candidate",
        "collected_volume_candidate",
        "date_type",
        "collected_first_issue_date",
        "collected_last_issue_date",
        "status",
        "determination_source",
    ]
    can_delete = False
    show_change_link = True


@admin.register(MarvelIngestionGroup)
class MarvelIngestionGroupAdmin(admin.ModelAdmin):
    list_display = [
        "display_title",
        "normalized_title",
        "publisher_name",
        "source_volume_count",
        "source_issue_count",
        "first_issue_date",
        "last_issue_date",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "analysis_version",
        "analyzed_at",
        "source_changed_at",
        "catalog_run",
    ]
    list_filter = [
        "publisher_name",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "analysis_version",
    ]
    search_fields = [
        "display_title",
        "normalized_title",
        "analysis_reason",
        "catalog_run__title",
    ]
    raw_id_fields = [
        "catalog_run",
    ]
    readonly_fields = [
        "publisher_name",
        "normalized_title",
        "display_title",
        "source_volume_count",
        "source_issue_count",
        "first_issue_date",
        "last_issue_date",
        "source_volume_fingerprint",
        "source_issue_fingerprint",
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
    inlines = [
        ComicVineVolumeCandidateInline,
        MarvelVolumeContainmentInline,
    ]


@admin.register(ComicVineVolumeCandidate)
class ComicVineVolumeCandidateAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "publisher_name",
        "normalized_title",
        "start_year",
        "source_issue_count",
        "source_date_type",
        "first_issue_date",
        "last_issue_date",
        "suggested_kind",
        "reviewed_kind",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "review_status",
        "group",
        "proposed_parent_run_candidate",
        "catalog_run",
        "catalog_volume",
        "analyzed_at",
        "source_changed_at",
        "reviewed_at",
    ]
    list_filter = [
        "publisher_name",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "suggested_kind",
        "reviewed_kind",
        "review_status",
        "source_date_type",
        "start_year",
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
        "catalog_volume__title",
    ]
    raw_id_fields = [
        "comicvine_volume",
        "group",
        "proposed_parent_run_candidate",
        "catalog_run",
        "catalog_volume",
    ]
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
        "source_issue_fingerprint",
        "suggested_kind",
        "analysis_version",
        "analysis_status",
        "catalog_status",
        "determination_source",
        "analysis_reason",
        "review_reason",
        "analyzed_at",
        "source_changed_at",
        "catalog_applied_at",
        "created_at",
        "updated_at",
    ]

    fieldsets = [
        (
            "Source Comic Vine volume",
            {
                "fields": [
                    "comicvine_volume",
                    "group",
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
                    "source_issue_fingerprint",
                ]
            },
        ),
        (
            "Deterministic analysis",
            {
                "fields": [
                    "suggested_kind",
                    "proposed_parent_run_candidate",
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
            "Manual review",
            {
                "fields": [
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
                    "created_at",
                    "updated_at",
                ]
            },
        ),
    ]


@admin.register(MarvelVolumeContainment)
class MarvelVolumeContainmentAdmin(admin.ModelAdmin):
    list_display = [
        "group",
        "run_candidate",
        "collected_volume_candidate",
        "date_type",
        "run_first_issue_date",
        "run_last_issue_date",
        "collected_first_issue_date",
        "collected_last_issue_date",
        "status",
        "determination_source",
        "analysis_version",
        "analyzed_at",
        "source_changed_at",
        "catalog_applied_at",
    ]
    list_filter = [
        "status",
        "determination_source",
        "date_type",
        "analysis_version",
    ]
    search_fields = [
        "group__display_title",
        "group__normalized_title",
        "run_candidate__title",
        "collected_volume_candidate__title",
        "determination_reason",
    ]
    raw_id_fields = [
        "group",
        "run_candidate",
        "collected_volume_candidate",
    ]
    readonly_fields = [
        "group",
        "run_candidate",
        "collected_volume_candidate",
        "date_type",
        "run_first_issue_date",
        "run_last_issue_date",
        "collected_first_issue_date",
        "collected_last_issue_date",
        "analysis_version",
        "status",
        "determination_source",
        "determination_reason",
        "run_source_issue_fingerprint",
        "collected_source_issue_fingerprint",
        "analyzed_at",
        "source_changed_at",
        "catalog_applied_at",
        "created_at",
        "updated_at",
    ]


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
        "candidate__title",
    ]
    raw_id_fields = [
        "catalog_run",
        "comicvine_volume",
        "candidate",
    ]
    readonly_fields = [
        "source_volume_date_last_updated",
        "source_issue_fingerprint",
        "confirmed_at",
        "last_processed_at",
        "source_changed_at",
        "created_at",
        "updated_at",
    ]


@admin.register(MarvelCatalogVolumeSource)
class MarvelCatalogVolumeSourceAdmin(admin.ModelAdmin):
    list_display = [
        "catalog_volume",
        "catalog_run",
        "comicvine_volume",
        "candidate",
        "containment",
        "confirmed_at",
        "last_processed_at",
        "source_changed_at",
    ]
    search_fields = [
        "catalog_volume__title",
        "catalog_run__title",
        "comicvine_volume__name",
        "comicvine_volume__comicvine_id",
        "candidate__title",
    ]
    raw_id_fields = [
        "catalog_volume",
        "catalog_run",
        "comicvine_volume",
        "candidate",
        "containment",
    ]
    readonly_fields = [
        "source_volume_date_last_updated",
        "source_issue_fingerprint",
        "confirmed_at",
        "last_processed_at",
        "source_changed_at",
        "created_at",
        "updated_at",
    ]


@admin.register(MarvelCatalogIssueSource)
class MarvelCatalogIssueSourceAdmin(admin.ModelAdmin):
    list_display = [
        "catalog_issue",
        "catalog_run",
        "comicvine_issue",
        "comicvine_volume",
        "run_source",
        "confirmed_at",
        "last_processed_at",
        "source_changed_at",
    ]
    search_fields = [
        "catalog_issue__issue_number",
        "catalog_issue__title",
        "catalog_issue__run__title",
        "catalog_run__title",
        "comicvine_issue__issue_number",
        "comicvine_issue__issue_title",
        "comicvine_issue__comicvine_id",
        "comicvine_volume__name",
        "comicvine_volume__comicvine_id",
    ]
    raw_id_fields = [
        "catalog_issue",
        "catalog_run",
        "comicvine_issue",
        "comicvine_volume",
        "run_source",
    ]
    readonly_fields = [
        "source_issue_date_last_updated",
        "confirmed_at",
        "last_processed_at",
        "source_changed_at",
        "created_at",
        "updated_at",
    ]