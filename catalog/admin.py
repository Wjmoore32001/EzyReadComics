from django.contrib import admin

from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicPublisher,
    ComicRun,
    ComicRunCredit,
    ComicVolume,
    ComicVolumeCredit,
    ComicVolumeIssue,
    CreditPerson,
    CreditRole,
)


class ComicRunCreditInline(admin.TabularInline):
    model = ComicRunCredit
    extra = 0
    autocomplete_fields = ["person", "role"]


class ComicIssueCreditInline(admin.TabularInline):
    model = ComicIssueCredit
    extra = 0
    autocomplete_fields = ["person", "role"]


class ComicVolumeIssueInline(admin.TabularInline):
    model = ComicVolumeIssue
    extra = 0
    autocomplete_fields = ["issue"]


class ComicVolumeCreditInline(admin.TabularInline):
    model = ComicVolumeCredit
    extra = 0
    autocomplete_fields = ["person", "role"]


@admin.register(ComicPublisher)
class ComicPublisherAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "slug",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "name",
        "slug",
    ]
    prepopulated_fields = {
        "slug": ["name"],
    }


@admin.register(ComicRun)
class ComicRunAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "publisher",
        "start_year",
        "first_issue_date",
        "last_issue_date",
        "status",
        "issue_count",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "publisher",
        "status",
        "start_year",
    ]
    search_fields = [
        "title",
        "publisher__name",
        "description",
    ]
    autocomplete_fields = [
        "publisher",
    ]
    inlines = [
        ComicRunCreditInline,
    ]


@admin.register(ComicIssue)
class ComicIssueAdmin(admin.ModelAdmin):
    list_display = [
        "run",
        "issue_number",
        "title",
        "published_date",
        "cover_date",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "run__publisher",
        "published_date",
        "cover_date",
    ]
    search_fields = [
        "run__title",
        "issue_number",
        "title",
        "description",
    ]
    autocomplete_fields = [
        "run",
    ]
    inlines = [
        ComicIssueCreditInline,
    ]


@admin.register(ComicVolume)
class ComicVolumeAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "volume_number",
        "publisher",
        "run",
        "release_date",
        "issue_count",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "publisher",
        "run",
        "release_date",
    ]
    search_fields = [
        "title",
        "volume_number",
        "publisher__name",
        "run__title",
        "description",
    ]
    autocomplete_fields = [
        "publisher",
        "run",
    ]
    inlines = [
        ComicVolumeIssueInline,
        ComicVolumeCreditInline,
    ]


@admin.register(ComicVolumeIssue)
class ComicVolumeIssueAdmin(admin.ModelAdmin):
    list_display = [
        "volume",
        "issue",
        "issue_order",
    ]
    list_filter = [
        "volume__publisher",
        "volume__run",
    ]
    search_fields = [
        "volume__title",
        "issue__run__title",
        "issue__issue_number",
        "issue__title",
    ]
    autocomplete_fields = [
        "volume",
        "issue",
    ]


@admin.register(CreditPerson)
class CreditPersonAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "name",
    ]


@admin.register(CreditRole)
class CreditRoleAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "display_order",
        "show_by_default",
    ]
    list_filter = [
        "show_by_default",
    ]
    search_fields = [
        "name",
    ]


@admin.register(ComicRunCredit)
class ComicRunCreditAdmin(admin.ModelAdmin):
    list_display = [
        "run",
        "person",
        "role",
        "credit_order",
    ]
    list_filter = [
        "role",
        "run__publisher",
    ]
    search_fields = [
        "run__title",
        "person__name",
        "role__name",
    ]
    autocomplete_fields = [
        "run",
        "person",
        "role",
    ]


@admin.register(ComicIssueCredit)
class ComicIssueCreditAdmin(admin.ModelAdmin):
    list_display = [
        "issue",
        "person",
        "role",
        "credit_order",
    ]
    list_filter = [
        "role",
        "issue__run__publisher",
    ]
    search_fields = [
        "issue__run__title",
        "issue__issue_number",
        "issue__title",
        "person__name",
        "role__name",
    ]
    autocomplete_fields = [
        "issue",
        "person",
        "role",
    ]


@admin.register(ComicVolumeCredit)
class ComicVolumeCreditAdmin(admin.ModelAdmin):
    list_display = [
        "volume",
        "person",
        "role",
        "credit_order",
    ]
    list_filter = [
        "role",
        "volume__publisher",
    ]
    search_fields = [
        "volume__title",
        "person__name",
        "role__name",
    ]
    autocomplete_fields = [
        "volume",
        "person",
        "role",
    ]