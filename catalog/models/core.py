import re

from django.db import models
from django.utils import timezone


class ImageUrlFields(models.Model):
    DISPLAY_IMAGE_SOURCE_UNKNOWN = "unknown"
    DISPLAY_IMAGE_SOURCE_SOURCE_DATA = "source_data"
    DISPLAY_IMAGE_SOURCE_MANUAL = "manual"

    DISPLAY_IMAGE_SOURCE_CHOICES = [
        (DISPLAY_IMAGE_SOURCE_UNKNOWN, "Unknown"),
        (DISPLAY_IMAGE_SOURCE_SOURCE_DATA, "Source data"),
        (DISPLAY_IMAGE_SOURCE_MANUAL, "Manual"),
    ]

    image_icon_url = models.URLField(max_length=500, blank=True)
    image_medium_url = models.URLField(max_length=500, blank=True)
    image_screen_url = models.URLField(max_length=500, blank=True)
    image_screen_large_url = models.URLField(max_length=500, blank=True)
    image_small_url = models.URLField(max_length=500, blank=True)
    image_super_url = models.URLField(max_length=500, blank=True)
    image_thumb_url = models.URLField(max_length=500, blank=True)
    image_tiny_url = models.URLField(max_length=500, blank=True)
    image_original_url = models.URLField(max_length=500, blank=True)
    image_tags = models.CharField(max_length=500, blank=True)

    display_image_url = models.URLField(max_length=500, blank=True)
    display_image_source = models.CharField(
        max_length=30,
        choices=DISPLAY_IMAGE_SOURCE_CHOICES,
        default=DISPLAY_IMAGE_SOURCE_UNKNOWN,
    )

    class Meta:
        abstract = True


class ComicPublisher(models.Model):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ComicRun(ImageUrlFields):
    STATUS_UNKNOWN = "unknown"
    STATUS_UPCOMING = "upcoming"
    STATUS_ONGOING = "ongoing"
    STATUS_ENDED = "ended"

    STATUS_CHOICES = [
        (STATUS_UNKNOWN, "Unknown"),
        (STATUS_UPCOMING, "Upcoming"),
        (STATUS_ONGOING, "Ongoing"),
        (STATUS_ENDED, "Ended"),
    ]

    publisher = models.ForeignKey(
        ComicPublisher,
        on_delete=models.PROTECT,
        related_name="runs",
    )

    title = models.CharField(max_length=500)
    start_year = models.CharField(max_length=20, blank=True)

    official_source_key = models.CharField(max_length=500, blank=True, db_index=True)
    official_source_url = models.URLField(max_length=500, blank=True)

    first_issue_date = models.DateField(null=True, blank=True)
    last_issue_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_UNKNOWN,
    )

    issue_count = models.PositiveIntegerField(null=True, blank=True)

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["publisher__name", "title", "start_year"]

    def __str__(self):
        if self.start_year:
            return f"{self.title} ({self.start_year})"

        return self.title


class ComicIssue(ImageUrlFields):
    OFFICIAL_DETAIL_STATUS_UNKNOWN = "unknown"
    OFFICIAL_DETAIL_STATUS_COMPLETE = "complete"
    OFFICIAL_DETAIL_STATUS_INCOMPLETE = "incomplete"

    OFFICIAL_DETAIL_STATUS_CHOICES = [
        (OFFICIAL_DETAIL_STATUS_UNKNOWN, "Unknown"),
        (OFFICIAL_DETAIL_STATUS_COMPLETE, "Complete"),
        (OFFICIAL_DETAIL_STATUS_INCOMPLETE, "Incomplete"),
    ]

    run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="issues",
    )

    issue_number = models.CharField(max_length=50)

    official_source_key = models.CharField(max_length=500, blank=True, db_index=True)
    official_source_url = models.URLField(max_length=500, blank=True)

    # Kept for legacy/manual data only. New ingestion should leave this blank.
    title = models.CharField(max_length=500, blank=True)

    # Kept for possible future/debug display only. Main app UI should use published_date.
    cover_date = models.DateField(null=True, blank=True)

    published_date = models.DateField(null=True, blank=True)

    is_released = models.BooleanField(default=True, db_index=True)

    description = models.TextField(blank=True)

    official_detail_status = models.CharField(
        max_length=20,
        choices=OFFICIAL_DETAIL_STATUS_CHOICES,
        default=OFFICIAL_DETAIL_STATUS_UNKNOWN,
        db_index=True,
    )
    official_detail_checked_at = models.DateTimeField(null=True, blank=True)
    official_detail_missing_fields = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["run", "published_date", "issue_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "issue_number"],
                name="unique_comic_issue_number_per_run",
            )
        ]

    @property
    def store_date(self):
        """
        Temporary compatibility alias.

        The actual model field is published_date now. This lets simple Python code
        that still reads issue.store_date keep working while old commands/templates
        are updated.
        """
        return self.published_date

    @store_date.setter
    def store_date(self, value):
        self.published_date = value

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.sync_run_description_from_mainline_first_issue()

    def sync_run_description_from_mainline_first_issue(self):
        description = self.description.strip()

        if not self.run_id or not description:
            return

        if not is_mainline_first_issue_number(self.issue_number):
            return

        ComicRun.objects.filter(id=self.run_id).exclude(description=description).update(
            description=description,
            updated_at=timezone.now(),
        )

    def __str__(self):
        return f"{self.run} #{self.issue_number}"


class ComicOneShot(ImageUrlFields):
    publisher = models.ForeignKey(
        ComicPublisher,
        on_delete=models.PROTECT,
        related_name="one_shots",
    )

    title = models.CharField(max_length=500)
    start_year = models.CharField(max_length=20, blank=True)

    official_source_key = models.CharField(max_length=500, blank=True, db_index=True)
    official_source_url = models.URLField(max_length=500, blank=True)

    published_date = models.DateField(null=True, blank=True)

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["publisher__name", "title", "start_year", "published_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["publisher", "title", "start_year"],
                name="unique_comic_one_shot_per_publisher_title_year",
            )
        ]

    def __str__(self):
        if self.start_year:
            return f"{self.title} ({self.start_year})"

        return self.title


class ComicVolume(ImageUrlFields):
    publisher = models.ForeignKey(
        ComicPublisher,
        on_delete=models.PROTECT,
        related_name="volumes",
    )
    run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="volumes",
    )

    title = models.CharField(max_length=500, blank=True)
    volume_number = models.CharField(max_length=50, blank=True)

    official_source_key = models.CharField(max_length=500, blank=True, db_index=True)
    official_source_url = models.URLField(max_length=500, blank=True)

    first_issue_number = models.CharField(max_length=50, blank=True)
    last_issue_number = models.CharField(max_length=50, blank=True)

    release_date = models.DateField(null=True, blank=True)
    issue_count = models.PositiveIntegerField(null=True, blank=True)

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["publisher__name", "run", "volume_number", "release_date", "title"]

    @property
    def display_title(self):
        volume_title = self.title.strip()

        if volume_title:
            return volume_title

        if self.run_id and self.run:
            run_title = self.run.title.strip()
            volume_number = self.volume_number.strip()

            if volume_number:
                return f"{run_title} Vol. {volume_number}"

            return run_title

        return ""

    def __str__(self):
        return self.display_title


class ComicVolumeRun(models.Model):
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.CASCADE,
        related_name="volume_runs",
    )
    run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="collected_volume_links",
    )

    first_issue_number = models.CharField(max_length=50, blank=True)
    last_issue_number = models.CharField(max_length=50, blank=True)
    issue_numbers_text = models.CharField(max_length=500, blank=True)

    item_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["volume", "item_order", "run__title", "run__start_year"]
        constraints = [
            models.UniqueConstraint(
                fields=["volume", "run"],
                name="unique_comic_volume_run",
            )
        ]

    def __str__(self):
        issue_text = self.issue_numbers_text.strip()

        if issue_text:
            return f"{self.volume} contains {self.run} #{issue_text}"

        return f"{self.volume} contains {self.run}"


class ComicVolumeIssue(models.Model):
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.CASCADE,
        related_name="volume_issues",
    )
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="collected_in",
    )

    issue_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["volume", "issue_order", "issue__published_date", "issue__issue_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["volume", "issue"],
                name="unique_comic_volume_issue",
            )
        ]

    def __str__(self):
        return f"{self.volume} contains {self.issue}"


class ComicVolumeOneShot(models.Model):
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.CASCADE,
        related_name="volume_one_shots",
    )
    one_shot = models.ForeignKey(
        ComicOneShot,
        on_delete=models.CASCADE,
        related_name="collected_in",
    )

    item_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["volume", "item_order", "one_shot__published_date", "one_shot__title"]
        constraints = [
            models.UniqueConstraint(
                fields=["volume", "one_shot"],
                name="unique_comic_volume_one_shot",
            )
        ]

    def __str__(self):
        return f"{self.volume} contains {self.one_shot}"


def is_first_issue_number(value):
    return is_mainline_first_issue_number(value)


def is_mainline_first_issue_number(value):
    value = str(value or "").strip()

    if not value:
        return False

    if looks_like_special_issue_number(value):
        return False

    value = re.sub(r"^\s*issue\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*no\.?\s*", "", value, flags=re.IGNORECASE)

    while value.startswith("#"):
        value = value[1:].strip()

    return value == "1"


def looks_like_special_issue_number(value):
    value = f" {str(value or '').strip().casefold()} "
    return any(
        marker in value
        for marker in [
            " annual ",
            " annual #",
            " noir edition ",
            " noir edition #",
            " ark m ",
            " ark m #",
            ": ark ",
            ": ark m",
            " special ",
            " special #",
        ]
    )