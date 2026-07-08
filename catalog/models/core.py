from django.db import models


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
    STATUS_ONGOING = "ongoing"
    STATUS_ENDED = "ended"

    STATUS_CHOICES = [
        (STATUS_UNKNOWN, "Unknown"),
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
    run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="issues",
    )

    issue_number = models.CharField(max_length=50)
    title = models.CharField(max_length=500, blank=True)

    cover_date = models.DateField(null=True, blank=True)
    store_date = models.DateField(null=True, blank=True)

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["run", "store_date", "issue_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "issue_number"],
                name="unique_comic_issue_number_per_run",
            )
        ]

    def __str__(self):
        return f"{self.run} #{self.issue_number}"


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

    title = models.CharField(max_length=500)
    volume_number = models.CharField(max_length=50, blank=True)

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
        run_title = self.run.title.strip() if self.run_id and self.run else ""
        volume_title = self.title.strip()
        volume_number = self.volume_number.strip()

        if not run_title:
            return volume_title

        normalized_run_title = run_title.casefold()
        normalized_volume_title = volume_title.casefold()

        if normalized_volume_title.startswith(f"{normalized_run_title} vol"):
            return volume_title

        if normalized_volume_title == normalized_run_title:
            volume_title = ""

        display_title = run_title

        if volume_number:
            display_title = f"{display_title} Vol. {volume_number}"

        if volume_title:
            display_title = f"{display_title}: {volume_title}"

        return display_title

    def __str__(self):
        return self.display_title


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
        ordering = ["volume", "issue_order", "issue__store_date", "issue__issue_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["volume", "issue"],
                name="unique_comic_volume_issue",
            )
        ]

    def __str__(self):
        return f"{self.volume} contains {self.issue}"