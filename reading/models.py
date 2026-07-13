from django.conf import settings
from django.db import models

from catalog.models import ComicIssue, ComicOneShot, ComicRun, ComicVolume


class FollowedRun(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_READING = "reading"
    STATUS_READ = "read"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned to read"),
        (STATUS_READING, "Reading"),
        (STATUS_READ, "Read"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="followed_runs",
    )
    run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="user_followers",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PLANNED,
    )

    followed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-followed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "run"],
                name="unique_followed_run_per_user",
            )
        ]
        indexes = [
            models.Index(
                fields=["user", "-followed_at"],
                name="reading_fr_user_followed_idx",
            ),
            models.Index(
                fields=["user", "status"],
                name="reading_fr_user_status_idx",
            ),
            models.Index(
                fields=["run"],
                name="reading_fr_run_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} follows {self.run} - {self.get_status_display()}"


class IssueProgress(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_READING = "reading"
    STATUS_READ = "read"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned to read"),
        (STATUS_READING, "Reading"),
        (STATUS_READ, "Read"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="issue_progress",
    )
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="user_progress",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PLANNED,
    )

    saved_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "issue__run__publisher__name",
            "issue__run__title",
            "issue__published_date",
            "issue__issue_number",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "issue"],
                name="unique_user_issue_progress",
            )
        ]
        indexes = [
            models.Index(
                fields=["user", "status"],
                name="reading_ip_user_status_idx",
            ),
            models.Index(
                fields=["issue"],
                name="reading_ip_issue_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.issue} - {self.get_status_display()}"


class VolumeProgress(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_READING = "reading"
    STATUS_READ = "read"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned to read"),
        (STATUS_READING, "Reading"),
        (STATUS_READ, "Read"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="volume_progress",
    )
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.CASCADE,
        related_name="user_progress",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PLANNED,
    )

    saved_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "volume__publisher__name",
            "volume__run__title",
            "volume__volume_number",
            "volume__release_date",
            "volume__title",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "volume"],
                name="unique_user_volume_progress",
            )
        ]
        indexes = [
            models.Index(
                fields=["user", "status"],
                name="reading_vp_user_status_idx",
            ),
            models.Index(
                fields=["volume"],
                name="reading_vp_volume_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.volume} - {self.get_status_display()}"


class OneShotProgress(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_READING = "reading"
    STATUS_READ = "read"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned to read"),
        (STATUS_READING, "Reading"),
        (STATUS_READ, "Read"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="one_shot_progress",
    )
    one_shot = models.ForeignKey(
        ComicOneShot,
        on_delete=models.CASCADE,
        related_name="user_progress",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PLANNED,
    )

    saved_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "one_shot__publisher__name",
            "one_shot__published_date",
            "one_shot__title",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "one_shot"],
                name="unique_user_one_shot_progress",
            )
        ]
        indexes = [
            models.Index(
                fields=["user", "status"],
                name="reading_osp_user_status_idx",
            ),
            models.Index(
                fields=["one_shot"],
                name="reading_osp_one_shot_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.one_shot} - {self.get_status_display()}"