from django.db import models

from catalog.models import ComicRun, ComicVolume
from comicvine.models import ComicVineVolume


class ComicVineVolumeCandidate(models.Model):
    KIND_UNKNOWN = "unknown"
    KIND_RUN = "run"
    KIND_COLLECTED_VOLUME = "collected_volume"
    KIND_IGNORE = "ignore"

    KIND_CHOICES = [
        (KIND_UNKNOWN, "Unknown"),
        (KIND_RUN, "Run"),
        (KIND_COLLECTED_VOLUME, "Collected volume"),
        (KIND_IGNORE, "Ignore"),
    ]

    REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
    REVIEW_STATUS_CONFIRMED = "confirmed"
    REVIEW_STATUS_REJECTED = "rejected"
    REVIEW_STATUS_IGNORED = "ignored"

    REVIEW_STATUS_CHOICES = [
        (REVIEW_STATUS_NEEDS_REVIEW, "Needs review"),
        (REVIEW_STATUS_CONFIRMED, "Confirmed"),
        (REVIEW_STATUS_REJECTED, "Rejected"),
        (REVIEW_STATUS_IGNORED, "Ignored"),
    ]

    comicvine_volume = models.OneToOneField(
        ComicVineVolume,
        on_delete=models.PROTECT,
        related_name="ingestion_candidate",
    )

    publisher_name = models.CharField(max_length=255, blank=True, db_index=True)
    title = models.CharField(max_length=500, db_index=True)
    start_year = models.CharField(max_length=20, blank=True, db_index=True)

    source_issue_count = models.PositiveIntegerField(null=True, blank=True)

    first_issue_date = models.DateField(null=True, blank=True)
    last_issue_date = models.DateField(null=True, blank=True)

    first_issue_number = models.CharField(max_length=50, blank=True)
    last_issue_number = models.CharField(max_length=50, blank=True)

    suggested_kind = models.CharField(
        max_length=30,
        choices=KIND_CHOICES,
        default=KIND_UNKNOWN,
    )
    reviewed_kind = models.CharField(
        max_length=30,
        choices=KIND_CHOICES,
        default=KIND_UNKNOWN,
    )

    review_status = models.CharField(
        max_length=30,
        choices=REVIEW_STATUS_CHOICES,
        default=REVIEW_STATUS_NEEDS_REVIEW,
        db_index=True,
    )
    review_reason = models.CharField(max_length=500, blank=True)

    catalog_run = models.ForeignKey(
        ComicRun,
        on_delete=models.PROTECT,
        related_name="comicvine_volume_candidates",
        null=True,
        blank=True,
    )
    catalog_volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.PROTECT,
        related_name="comicvine_volume_candidates",
        null=True,
        blank=True,
    )

    analyzed_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "publisher_name",
            "title",
            "start_year",
            "comicvine_volume__comicvine_id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["catalog_run"],
                condition=models.Q(catalog_run__isnull=False),
                name="unique_candidate_catalog_run",
            ),
            models.UniqueConstraint(
                fields=["catalog_volume"],
                condition=models.Q(catalog_volume__isnull=False),
                name="unique_candidate_catalog_volume",
            ),
        ]

    def __str__(self):
        return (
            f"{self.publisher_name} — {self.title} "
            f"({self.start_year or 'unknown year'}) "
            f"[{self.review_status}]"
        )