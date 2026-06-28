from django.db import models


class ComicVolume(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    publisher = models.CharField(max_length=100, blank=True)
    date_added = models.DateTimeField(null=True, blank=True)
    date_last_updated = models.DateTimeField(null=True, blank=True)
    comicvine_url = models.URLField(blank=True)

    def __str__(self):
        if self.publisher:
            return f"{self.name} ({self.publisher})"

        return self.name


class ComicIssue(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.PROTECT,
        related_name="issues",
        null=True,
        blank=True,
    )
    issue_number = models.CharField(max_length=50)
    issue_title = models.CharField(max_length=255, blank=True)
    date_added = models.DateTimeField(null=True, blank=True)
    date_last_updated = models.DateTimeField(null=True, blank=True)
    cover_date = models.DateField(null=True, blank=True)
    store_date = models.DateField(null=True, blank=True)
    comicvine_url = models.URLField(blank=True)
    image_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        volume_name = self.volume.name if self.volume else "Unknown Volume"
        return f"{volume_name} #{self.issue_number}"


class ComicVineDateScan(models.Model):
    ISSUE_DATE_ADDED = "issue_date_added"
    ISSUE_DATE_LAST_UPDATED = "issue_date_last_updated"
    VOLUME_DATE_LAST_UPDATED = "volume_date_last_updated"

    SCAN_KIND_CHOICES = [
        (ISSUE_DATE_ADDED, "Issue date added"),
        (ISSUE_DATE_LAST_UPDATED, "Issue date last updated"),
        (VOLUME_DATE_LAST_UPDATED, "Volume date last updated"),
    ]

    scan_kind = models.CharField(
        max_length=50,
        choices=SCAN_KIND_CHOICES,
        default=ISSUE_DATE_ADDED,
    )
    scan_date = models.DateField()
    next_offset = models.PositiveIntegerField(default=0)
    total_results = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["scan_kind", "-scan_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["scan_kind", "scan_date"],
                name="unique_comicvine_scan_kind_date",
            )
        ]

    def __str__(self):
        status = "complete" if self.completed else "incomplete"
        return f"{self.scan_kind}: {self.scan_date} ({status})"


class ComicVineSyncState(models.Model):
    name = models.CharField(max_length=50, unique=True, default="default")
    update_tracking_start_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.update_tracking_start_date:
            return f"Comic Vine sync state starting {self.update_tracking_start_date}"

        return "Comic Vine sync state"