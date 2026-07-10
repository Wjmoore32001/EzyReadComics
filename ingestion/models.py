from django.db import models

from catalog.models import ComicIssue, ComicRun, ComicVolume
from comicvine.models import ComicVineIssue, ComicVineVolume


class MarvelIngestionGroup(models.Model):
    ANALYSIS_VERSION_CURRENT = 1

    ANALYSIS_STATUS_NOT_ANALYZED = "not_analyzed"
    ANALYSIS_STATUS_CONFIRMED = "confirmed_by_rule"
    ANALYSIS_STATUS_UNRESOLVED = "unresolved"
    ANALYSIS_STATUS_CONFLICT = "conflict"
    ANALYSIS_STATUS_INSUFFICIENT_DATA = "insufficient_data"

    ANALYSIS_STATUS_CHOICES = [
        (ANALYSIS_STATUS_NOT_ANALYZED, "Not analyzed"),
        (ANALYSIS_STATUS_CONFIRMED, "Confirmed by rule"),
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

    publisher_name = models.CharField(max_length=255, default="Marvel", db_index=True)
    normalized_title = models.CharField(max_length=500, db_index=True)
    display_title = models.CharField(max_length=500, blank=True)

    source_volume_count = models.PositiveIntegerField(default=0)
    source_issue_count = models.PositiveIntegerField(default=0)

    first_issue_date = models.DateField(null=True, blank=True)
    last_issue_date = models.DateField(null=True, blank=True)

    source_volume_fingerprint = models.CharField(max_length=128, blank=True)
    source_issue_fingerprint = models.CharField(max_length=128, blank=True)

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

    catalog_run = models.ForeignKey(
        ComicRun,
        on_delete=models.PROTECT,
        related_name="marvel_ingestion_groups",
        null=True,
        blank=True,
    )

    analyzed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)
    catalog_applied_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "publisher_name",
            "normalized_title",
            "first_issue_date",
            "last_issue_date",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["publisher_name", "normalized_title"],
                name="unique_marvel_ingestion_group_title",
            )
        ]

    def __str__(self):
        return f"{self.publisher_name} — {self.display_title or self.normalized_title}"


class ComicVineVolumeCandidate(models.Model):
    ANALYSIS_VERSION_CURRENT = 1

    KIND_UNKNOWN = "unknown"
    KIND_RUN = "run"
    KIND_COLLECTED_VOLUME = "collected_volume"

    KIND_CHOICES = [
        (KIND_UNKNOWN, "Unknown"),
        (KIND_RUN, "Run"),
        (KIND_COLLECTED_VOLUME, "Collected volume"),
    ]

    ANALYSIS_STATUS_NOT_ANALYZED = "not_analyzed"
    ANALYSIS_STATUS_CONFIRMED_RUN = "confirmed_run"
    ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME = "confirmed_collected_volume"
    ANALYSIS_STATUS_UNRESOLVED = "unresolved"
    ANALYSIS_STATUS_CONFLICT = "conflict"
    ANALYSIS_STATUS_INSUFFICIENT_DATA = "insufficient_data"

    ANALYSIS_STATUS_CHOICES = [
        (ANALYSIS_STATUS_NOT_ANALYZED, "Not analyzed"),
        (ANALYSIS_STATUS_CONFIRMED_RUN, "Confirmed run"),
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

    DATE_TYPE_UNKNOWN = "unknown"
    DATE_TYPE_STORE_DATE = "store_date"
    DATE_TYPE_COVER_DATE = "cover_date"

    DATE_TYPE_CHOICES = [
        (DATE_TYPE_UNKNOWN, "Unknown"),
        (DATE_TYPE_STORE_DATE, "Store date"),
        (DATE_TYPE_COVER_DATE, "Cover date"),
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

    group = models.ForeignKey(
        MarvelIngestionGroup,
        on_delete=models.PROTECT,
        related_name="volume_candidates",
        null=True,
        blank=True,
    )

    proposed_parent_run_candidate = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="proposed_collected_volume_candidates",
        null=True,
        blank=True,
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
    source_issue_fingerprint = models.CharField(max_length=128, blank=True)

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
    catalog_volume = models.ForeignKey(
        ComicVolume,
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
            f"[{self.analysis_status}]"
        )


class MarvelVolumeContainment(models.Model):
    ANALYSIS_VERSION_CURRENT = 1

    STATUS_CONFIRMED_BY_RULE = "confirmed_by_rule"
    STATUS_UNRESOLVED = "unresolved"
    STATUS_CONFLICT = "conflict"
    STATUS_INVALIDATED_BY_SOURCE_CHANGE = "invalidated_by_source_change"

    STATUS_CHOICES = [
        (STATUS_CONFIRMED_BY_RULE, "Confirmed by rule"),
        (STATUS_UNRESOLVED, "Unresolved"),
        (STATUS_CONFLICT, "Conflict"),
        (
            STATUS_INVALIDATED_BY_SOURCE_CHANGE,
            "Invalidated by source change",
        ),
    ]

    DETERMINATION_SOURCE_ALGORITHM = "algorithm"
    DETERMINATION_SOURCE_MANUAL = "manual"

    DETERMINATION_SOURCE_CHOICES = [
        (DETERMINATION_SOURCE_ALGORITHM, "Algorithm"),
        (DETERMINATION_SOURCE_MANUAL, "Manual"),
    ]

    DATE_TYPE_STORE_DATE = "store_date"
    DATE_TYPE_COVER_DATE = "cover_date"

    DATE_TYPE_CHOICES = [
        (DATE_TYPE_STORE_DATE, "Store date"),
        (DATE_TYPE_COVER_DATE, "Cover date"),
    ]

    group = models.ForeignKey(
        MarvelIngestionGroup,
        on_delete=models.CASCADE,
        related_name="containment_relationships",
    )
    run_candidate = models.ForeignKey(
        ComicVineVolumeCandidate,
        on_delete=models.CASCADE,
        related_name="contained_volume_relationships",
    )
    collected_volume_candidate = models.ForeignKey(
        ComicVineVolumeCandidate,
        on_delete=models.CASCADE,
        related_name="contained_by_relationships",
    )

    date_type = models.CharField(max_length=30, choices=DATE_TYPE_CHOICES)

    run_first_issue_date = models.DateField()
    run_last_issue_date = models.DateField()
    collected_first_issue_date = models.DateField()
    collected_last_issue_date = models.DateField()

    analysis_version = models.PositiveIntegerField(default=ANALYSIS_VERSION_CURRENT)
    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        default=STATUS_CONFIRMED_BY_RULE,
        db_index=True,
    )
    determination_source = models.CharField(
        max_length=40,
        choices=DETERMINATION_SOURCE_CHOICES,
        default=DETERMINATION_SOURCE_ALGORITHM,
        db_index=True,
    )
    determination_reason = models.CharField(max_length=500, blank=True)

    run_source_issue_fingerprint = models.CharField(max_length=128, blank=True)
    collected_source_issue_fingerprint = models.CharField(max_length=128, blank=True)

    analyzed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)
    catalog_applied_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "group",
            "run_candidate",
            "collected_first_issue_date",
            "collected_last_issue_date",
            "collected_volume_candidate",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["run_candidate", "collected_volume_candidate"],
                name="unique_marvel_volume_containment_pair",
            )
        ]

    def __str__(self):
        return f"{self.collected_volume_candidate} inside {self.run_candidate}"


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
    source_issue_fingerprint = models.CharField(max_length=128, blank=True)

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
    comicvine_volume = models.OneToOneField(
        ComicVineVolume,
        on_delete=models.PROTECT,
        related_name="marvel_catalog_volume_source",
    )
    candidate = models.OneToOneField(
        ComicVineVolumeCandidate,
        on_delete=models.PROTECT,
        related_name="catalog_volume_source_link",
    )
    containment = models.ForeignKey(
        MarvelVolumeContainment,
        on_delete=models.PROTECT,
        related_name="catalog_volume_source_links",
        null=True,
        blank=True,
    )

    source_volume_date_last_updated = models.DateTimeField(null=True, blank=True)
    source_issue_fingerprint = models.CharField(max_length=128, blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_processed_at = models.DateTimeField(null=True, blank=True)
    source_changed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["catalog_run", "catalog_volume", "comicvine_volume"]

    def __str__(self):
        return (
            f"{self.catalog_volume} from Comic Vine volume "
            f"{self.comicvine_volume.comicvine_id}"
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