from django.db import models

from catalog.models import ComicIssue, ComicRun, ComicVolume
from comicvine.models import ComicVineIssue, ComicVineVolume


class ComicVineVolumeCandidate(models.Model):
    ANALYSIS_VERSION_CURRENT = 3

    ANALYSIS_STATUS_NOT_ANALYZED = "not_analyzed"
    ANALYSIS_STATUS_CONFIRMED_RUN = "confirmed_run"
    ANALYSIS_STATUS_COLLECTION_CONTAINER = "collection_container"
    ANALYSIS_STATUS_UNRESOLVED = "unresolved"
    ANALYSIS_STATUS_CONFLICT = "conflict"
    ANALYSIS_STATUS_INSUFFICIENT_DATA = "insufficient_data"

    ANALYSIS_STATUS_CHOICES = [
        (ANALYSIS_STATUS_NOT_ANALYZED, "Not analyzed"),
        (ANALYSIS_STATUS_CONFIRMED_RUN, "Confirmed run"),
        (ANALYSIS_STATUS_COLLECTION_CONTAINER, "Collection container"),
        (ANALYSIS_STATUS_UNRESOLVED, "Unresolved"),
        (ANALYSIS_STATUS_CONFLICT, "Conflict"),
        (ANALYSIS_STATUS_INSUFFICIENT_DATA, "Insufficient data"),
    ]

    CATALOG_STATUS_NOT_READY = "not_ready"
    CATALOG_STATUS_READY_TO_APPLY = "ready_to_apply"
    CATALOG_STATUS_APPLIED = "applied"
    CATALOG_STATUS_UPDATE_AVAILABLE = "update_available"
    CATALOG_STATUS_BLOCKED = "blocked"

    CATALOG_STATUS_CHOICES = [
        (CATALOG_STATUS_NOT_READY, "Not ready"),
        (CATALOG_STATUS_READY_TO_APPLY, "Ready to apply"),
        (CATALOG_STATUS_APPLIED, "Applied"),
        (CATALOG_STATUS_UPDATE_AVAILABLE, "Update available"),
        (CATALOG_STATUS_BLOCKED, "Blocked"),
    ]

    DETERMINATION_SOURCE_NOT_DETERMINED = "not_determined"
    DETERMINATION_SOURCE_ALGORITHM = "algorithm"
    DETERMINATION_SOURCE_MANUAL = "manual"

    DETERMINATION_SOURCE_CHOICES = [
        (DETERMINATION_SOURCE_NOT_DETERMINED, "Not determined"),
        (DETERMINATION_SOURCE_ALGORITHM, "Algorithm"),
        (DETERMINATION_SOURCE_MANUAL, "Manual"),
    ]

    DATE_TYPE_UNKNOWN = "unknown"
    DATE_TYPE_STORE_DATE = "store_date"
    DATE_TYPE_COVER_DATE = "cover_date"
    DATE_TYPE_BEST_AVAILABLE = "best_available"

    DATE_TYPE_CHOICES = [
        (DATE_TYPE_UNKNOWN, "Unknown"),
        (DATE_TYPE_STORE_DATE, "Store date"),
        (DATE_TYPE_COVER_DATE, "Cover date"),
        (DATE_TYPE_BEST_AVAILABLE, "Best available date"),
    ]

    REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
    REVIEW_STATUS_CONFIRMED = "confirmed"
    REVIEW_STATUS_REJECTED = "rejected"

    REVIEW_STATUS_CHOICES = [
        (REVIEW_STATUS_NEEDS_REVIEW, "Needs review"),
        (REVIEW_STATUS_CONFIRMED, "Confirmed"),
        (REVIEW_STATUS_REJECTED, "Rejected"),
    ]

    comicvine_volume = models.OneToOneField(
        ComicVineVolume,
        on_delete=models.PROTECT,
        related_name="ingestion_candidate",
    )

    publisher_name = models.CharField(max_length=255, blank=True, db_index=True)
    title = models.CharField(max_length=500, db_index=True)
    normalized_title = models.CharField(max_length=500, blank=True, db_index=True)
    start_year = models.CharField(max_length=20, blank=True, db_index=True)

    source_issue_count = models.PositiveIntegerField(null=True, blank=True)
    source_date_type = models.CharField(
        max_length=30,
        choices=DATE_TYPE_CHOICES,
        default=DATE_TYPE_UNKNOWN,
        db_index=True,
    )
    first_issue_date = models.DateField(null=True, blank=True)
    last_issue_date = models.DateField(null=True, blank=True)
    first_issue_number = models.CharField(max_length=50, blank=True)
    last_issue_number = models.CharField(max_length=50, blank=True)

    source_volume_date_last_updated = models.DateTimeField(null=True, blank=True)
    source_fingerprint = models.CharField(max_length=128, blank=True)

    analysis_version = models.PositiveIntegerField(default=ANALYSIS_VERSION_CURRENT)
    analysis_status = models.CharField(
        max_length=40,
        choices=ANALYSIS_STATUS_CHOICES,
        default=ANALYSIS_STATUS_NOT_ANALYZED,
        db_index=True,
    )
    catalog_status = models.CharField(
        max_length=40,
        choices=CATALOG_STATUS_CHOICES,
        default=CATALOG_STATUS_NOT_READY,
        db_index=True,
    )
    determination_source = models.CharField(
        max_length=40,
        choices=DETERMINATION_SOURCE_CHOICES,
        default=DETERMINATION_SOURCE_NOT_DETERMINED,
        db_index=True,
    )
    analysis_reason = models.CharField(max_length=500, blank=True)

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

    analyzed_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)
    catalog_applied_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "publisher_name",
            "normalized_title",
            "start_year",
            "comicvine_volume__comicvine_id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["catalog_run"],
                condition=models.Q(catalog_run__isnull=False),
                name="unique_candidate_catalog_run",
            )
        ]

    def __str__(self):
        return (
            f"{self.publisher_name} — {self.title} "
            f"({self.start_year or 'unknown year'}) "
            f"[{self.analysis_status}]"
        )


class ComicVineCollectedEditionCandidate(models.Model):
    ANALYSIS_VERSION_CURRENT = 3

    ANALYSIS_STATUS_NOT_ANALYZED = "not_analyzed"
    ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME = "confirmed_collected_volume"
    ANALYSIS_STATUS_UNRESOLVED = "unresolved"
    ANALYSIS_STATUS_CONFLICT = "conflict"
    ANALYSIS_STATUS_INSUFFICIENT_DATA = "insufficient_data"

    ANALYSIS_STATUS_CHOICES = [
        (ANALYSIS_STATUS_NOT_ANALYZED, "Not analyzed"),
        (
            ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME,
            "Confirmed collected volume",
        ),
        (ANALYSIS_STATUS_UNRESOLVED, "Unresolved"),
        (ANALYSIS_STATUS_CONFLICT, "Conflict"),
        (ANALYSIS_STATUS_INSUFFICIENT_DATA, "Insufficient data"),
    ]

    CATALOG_STATUS_NOT_READY = "not_ready"
    CATALOG_STATUS_READY_TO_APPLY = "ready_to_apply"
    CATALOG_STATUS_APPLIED = "applied"
    CATALOG_STATUS_UPDATE_AVAILABLE = "update_available"
    CATALOG_STATUS_BLOCKED = "blocked"

    CATALOG_STATUS_CHOICES = [
        (CATALOG_STATUS_NOT_READY, "Not ready"),
        (CATALOG_STATUS_READY_TO_APPLY, "Ready to apply"),
        (CATALOG_STATUS_APPLIED, "Applied"),
        (CATALOG_STATUS_UPDATE_AVAILABLE, "Update available"),
        (CATALOG_STATUS_BLOCKED, "Blocked"),
    ]

    DETERMINATION_SOURCE_NOT_DETERMINED = "not_determined"
    DETERMINATION_SOURCE_ALGORITHM = "algorithm"
    DETERMINATION_SOURCE_MANUAL = "manual"

    DETERMINATION_SOURCE_CHOICES = [
        (DETERMINATION_SOURCE_NOT_DETERMINED, "Not determined"),
        (DETERMINATION_SOURCE_ALGORITHM, "Algorithm"),
        (DETERMINATION_SOURCE_MANUAL, "Manual"),
    ]

    REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
    REVIEW_STATUS_CONFIRMED = "confirmed"
    REVIEW_STATUS_REJECTED = "rejected"

    REVIEW_STATUS_CHOICES = [
        (REVIEW_STATUS_NEEDS_REVIEW, "Needs review"),
        (REVIEW_STATUS_CONFIRMED, "Confirmed"),
        (REVIEW_STATUS_REJECTED, "Rejected"),
    ]

    comicvine_issue = models.OneToOneField(
        ComicVineIssue,
        on_delete=models.PROTECT,
        related_name="collected_edition_candidate",
    )
    source_collection_volume = models.ForeignKey(
        ComicVineVolume,
        on_delete=models.PROTECT,
        related_name="collected_edition_candidates",
    )
    proposed_parent_run_candidate = models.ForeignKey(
        ComicVineVolumeCandidate,
        on_delete=models.PROTECT,
        related_name="proposed_collected_editions",
        null=True,
        blank=True,
    )

    publisher_name = models.CharField(max_length=255, blank=True, db_index=True)
    source_title = models.CharField(max_length=500, blank=True)
    volume_number = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=500, blank=True)
    release_date = models.DateField(null=True, blank=True)

    collecting_text = models.TextField(blank=True)
    unresolved_reference_text = models.TextField(blank=True)
    source_reference_count = models.PositiveIntegerField(default=0)
    source_issue_count = models.PositiveIntegerField(default=0)
    primary_first_issue_number = models.CharField(max_length=50, blank=True)
    primary_last_issue_number = models.CharField(max_length=50, blank=True)

    source_issue_date_last_updated = models.DateTimeField(null=True, blank=True)
    source_fingerprint = models.CharField(max_length=128, blank=True)

    analysis_version = models.PositiveIntegerField(default=ANALYSIS_VERSION_CURRENT)
    analysis_status = models.CharField(
        max_length=40,
        choices=ANALYSIS_STATUS_CHOICES,
        default=ANALYSIS_STATUS_NOT_ANALYZED,
        db_index=True,
    )
    catalog_status = models.CharField(
        max_length=40,
        choices=CATALOG_STATUS_CHOICES,
        default=CATALOG_STATUS_NOT_READY,
        db_index=True,
    )
    determination_source = models.CharField(
        max_length=40,
        choices=DETERMINATION_SOURCE_CHOICES,
        default=DETERMINATION_SOURCE_NOT_DETERMINED,
        db_index=True,
    )
    analysis_reason = models.CharField(max_length=500, blank=True)

    review_status = models.CharField(
        max_length=30,
        choices=REVIEW_STATUS_CHOICES,
        default=REVIEW_STATUS_NEEDS_REVIEW,
        db_index=True,
    )
    review_reason = models.CharField(max_length=500, blank=True)

    catalog_volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.PROTECT,
        related_name="comicvine_collected_edition_candidates",
        null=True,
        blank=True,
    )

    analyzed_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)
    catalog_applied_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "publisher_name",
            "source_collection_volume__name",
            "release_date",
            "volume_number",
            "comicvine_issue__comicvine_id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["catalog_volume"],
                condition=models.Q(catalog_volume__isnull=False),
                name="unique_collected_candidate_catalog_volume",
            )
        ]

    def __str__(self):
        display_title = self.source_title or self.source_collection_volume.name
        return f"{self.publisher_name} — {display_title} [{self.analysis_status}]"


class ComicVineCollectedEditionIssue(models.Model):
    candidate = models.ForeignKey(
        ComicVineCollectedEditionCandidate,
        on_delete=models.CASCADE,
        related_name="source_issue_links",
    )
    source_issue = models.ForeignKey(
        ComicVineIssue,
        on_delete=models.PROTECT,
        related_name="collected_edition_memberships",
    )
    source_run_candidate = models.ForeignKey(
        ComicVineVolumeCandidate,
        on_delete=models.PROTECT,
        related_name="collected_edition_issue_links",
    )

    issue_order = models.PositiveIntegerField()
    primary_run = models.BooleanField(default=False)
    reference_text = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["candidate", "issue_order", "source_issue"]
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "source_issue"],
                name="unique_collected_candidate_source_issue",
            ),
            models.UniqueConstraint(
                fields=["candidate", "issue_order"],
                name="unique_collected_candidate_issue_order",
            ),
        ]

    def __str__(self):
        return f"{self.candidate} contains {self.source_issue}"


class MarvelCatalogRunSource(models.Model):
    catalog_run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="marvel_source_links",
    )
    comicvine_volume = models.OneToOneField(
        ComicVineVolume,
        on_delete=models.PROTECT,
        related_name="marvel_catalog_run_source",
    )
    candidate = models.OneToOneField(
        ComicVineVolumeCandidate,
        on_delete=models.PROTECT,
        related_name="catalog_run_source_link",
    )

    source_volume_date_last_updated = models.DateTimeField(null=True, blank=True)
    source_fingerprint = models.CharField(max_length=128, blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_processed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["catalog_run", "comicvine_volume"]

    def __str__(self):
        return f"{self.catalog_run} from Comic Vine volume {self.comicvine_volume.comicvine_id}"


class MarvelCatalogVolumeSource(models.Model):
    catalog_volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.CASCADE,
        related_name="marvel_source_links",
    )
    catalog_run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="marvel_collected_volume_source_links",
    )
    comicvine_issue = models.OneToOneField(
        ComicVineIssue,
        on_delete=models.PROTECT,
        related_name="marvel_catalog_volume_source",
    )
    candidate = models.OneToOneField(
        ComicVineCollectedEditionCandidate,
        on_delete=models.PROTECT,
        related_name="catalog_volume_source_link",
    )

    source_issue_date_last_updated = models.DateTimeField(null=True, blank=True)
    source_fingerprint = models.CharField(max_length=128, blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_processed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["catalog_run", "catalog_volume", "comicvine_issue"]

    def __str__(self):
        return (
            f"{self.catalog_volume} from Comic Vine issue "
            f"{self.comicvine_issue.comicvine_id}"
        )


class MarvelCatalogIssueSource(models.Model):
    catalog_issue = models.OneToOneField(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="marvel_source_link",
    )
    catalog_run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="marvel_issue_source_links",
    )
    comicvine_issue = models.OneToOneField(
        ComicVineIssue,
        on_delete=models.PROTECT,
        related_name="marvel_catalog_issue_source",
    )
    comicvine_volume = models.ForeignKey(
        ComicVineVolume,
        on_delete=models.PROTECT,
        related_name="marvel_catalog_issue_sources",
    )
    run_source = models.ForeignKey(
        MarvelCatalogRunSource,
        on_delete=models.PROTECT,
        related_name="issue_source_links",
        null=True,
        blank=True,
    )

    source_issue_date_last_updated = models.DateTimeField(null=True, blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_processed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["catalog_run", "catalog_issue", "comicvine_issue"]

    def __str__(self):
        return f"{self.catalog_issue} from Comic Vine issue {self.comicvine_issue.comicvine_id}"