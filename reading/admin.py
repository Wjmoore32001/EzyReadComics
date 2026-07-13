from django.contrib import admin

from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


@admin.register(FollowedRun)
class FollowedRunAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "run",
        "publisher",
        "status",
        "followed_at",
        "updated_at",
    ]
    list_filter = [
        "status",
        "run__publisher",
        "followed_at",
        "updated_at",
    ]
    search_fields = [
        "user__username",
        "run__title",
        "run__publisher__name",
    ]
    autocomplete_fields = [
        "user",
        "run",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "user",
            "run",
            "run__publisher",
        )

    def publisher(self, obj):
        return obj.run.publisher.name


@admin.register(IssueProgress)
class IssueProgressAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "issue",
        "run",
        "publisher",
        "status",
        "saved_at",
        "updated_at",
    ]
    list_filter = [
        "status",
        "issue__run__publisher",
        "saved_at",
        "updated_at",
    ]
    search_fields = [
        "user__username",
        "issue__issue_number",
        "issue__title",
        "issue__run__title",
        "issue__run__publisher__name",
    ]
    autocomplete_fields = [
        "user",
        "issue",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "user",
            "issue",
            "issue__run",
            "issue__run__publisher",
        )

    def run(self, obj):
        return obj.issue.run

    def publisher(self, obj):
        return obj.issue.run.publisher.name


@admin.register(VolumeProgress)
class VolumeProgressAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "volume",
        "run",
        "publisher",
        "status",
        "saved_at",
        "updated_at",
    ]
    list_filter = [
        "status",
        "volume__publisher",
        "volume__run",
        "saved_at",
        "updated_at",
    ]
    search_fields = [
        "user__username",
        "volume__title",
        "volume__volume_number",
        "volume__run__title",
        "volume__publisher__name",
    ]
    autocomplete_fields = [
        "user",
        "volume",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "user",
            "volume",
            "volume__run",
            "volume__publisher",
        )

    def run(self, obj):
        return obj.volume.run

    def publisher(self, obj):
        return obj.volume.publisher.name


@admin.register(OneShotProgress)
class OneShotProgressAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "one_shot",
        "publisher",
        "status",
        "saved_at",
        "updated_at",
    ]
    list_filter = [
        "status",
        "one_shot__publisher",
        "saved_at",
        "updated_at",
    ]
    search_fields = [
        "user__username",
        "one_shot__title",
        "one_shot__publisher__name",
    ]
    autocomplete_fields = [
        "user",
        "one_shot",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "user",
            "one_shot",
            "one_shot__publisher",
        )

    def publisher(self, obj):
        return obj.one_shot.publisher.name