from django.db import models


class ComicVolume(models.Model):
    IMAGE_SOURCE_UNKNOWN = "unknown"
    IMAGE_SOURCE_FIRST_ISSUE = "first_issue"
    IMAGE_SOURCE_COMICVINE_VOLUME = "comicvine_volume"
    IMAGE_SOURCE_MANUAL = "manual"

    IMAGE_SOURCE_CHOICES = [
        (IMAGE_SOURCE_UNKNOWN, "Unknown"),
        (IMAGE_SOURCE_FIRST_ISSUE, "First issue"),
        (IMAGE_SOURCE_COMICVINE_VOLUME, "Comic Vine volume"),
        (IMAGE_SOURCE_MANUAL, "Manual"),
    ]

    RUN_STATUS_UNKNOWN = "unknown"
    RUN_STATUS_LIKELY_ONGOING = "likely_ongoing"
    RUN_STATUS_LIKELY_ENDED = "likely_ended"
    RUN_STATUS_MANUAL_ONGOING = "manual_ongoing"
    RUN_STATUS_MANUAL_ENDED = "manual_ended"

    RUN_STATUS_CHOICES = [
        (RUN_STATUS_UNKNOWN, "Unknown"),
        (RUN_STATUS_LIKELY_ONGOING, "Likely ongoing"),
        (RUN_STATUS_LIKELY_ENDED, "Likely ended"),
        (RUN_STATUS_MANUAL_ONGOING, "Manual ongoing"),
        (RUN_STATUS_MANUAL_ENDED, "Manual ended"),
    ]

    RUN_STATUS_SOURCE_UNKNOWN = "unknown"
    RUN_STATUS_SOURCE_DATE_WINDOW = "date_window"
    RUN_STATUS_SOURCE_MANUAL = "manual"

    RUN_STATUS_SOURCE_CHOICES = [
        (RUN_STATUS_SOURCE_UNKNOWN, "Unknown"),
        (RUN_STATUS_SOURCE_DATE_WINDOW, "Date window"),
        (RUN_STATUS_SOURCE_MANUAL, "Manual"),
    ]

    comicvine_id = models.PositiveIntegerField(unique=True)

    name = models.CharField(max_length=500)
    publisher = models.CharField(max_length=255, blank=True)
    publisher_comicvine_id = models.PositiveIntegerField(null=True, blank=True)
    publisher_api_detail_url = models.URLField(max_length=500, blank=True)

    start_year = models.CharField(max_length=20, blank=True)
    count_of_issues = models.PositiveIntegerField(null=True, blank=True)

    date_added = models.DateTimeField(null=True, blank=True)
    date_last_updated = models.DateTimeField(null=True, blank=True)

    comicvine_url = models.URLField(max_length=500, blank=True)
    api_detail_url = models.URLField(max_length=500, blank=True)

    aliases = models.TextField(blank=True)
    deck = models.TextField(blank=True)
    description = models.TextField(blank=True)

    comicvine_image_icon_url = models.URLField(max_length=500, blank=True)
    comicvine_image_medium_url = models.URLField(max_length=500, blank=True)
    comicvine_image_screen_url = models.URLField(max_length=500, blank=True)
    comicvine_image_screen_large_url = models.URLField(max_length=500, blank=True)
    comicvine_image_small_url = models.URLField(max_length=500, blank=True)
    comicvine_image_super_url = models.URLField(max_length=500, blank=True)
    comicvine_image_thumb_url = models.URLField(max_length=500, blank=True)
    comicvine_image_tiny_url = models.URLField(max_length=500, blank=True)
    comicvine_image_original_url = models.URLField(max_length=500, blank=True)
    comicvine_image_tags = models.CharField(max_length=500, blank=True)

    display_image_url = models.URLField(max_length=500, blank=True)
    display_image_source = models.CharField(
        max_length=30,
        choices=IMAGE_SOURCE_CHOICES,
        default=IMAGE_SOURCE_UNKNOWN,
    )

    first_issue_comicvine_id = models.PositiveIntegerField(null=True, blank=True)
    first_issue_number = models.CharField(max_length=50, blank=True)
    first_issue_name = models.CharField(max_length=500, blank=True)
    first_issue_api_url = models.URLField(max_length=500, blank=True)

    last_issue_comicvine_id = models.PositiveIntegerField(null=True, blank=True)
    last_issue_number = models.CharField(max_length=50, blank=True)
    last_issue_name = models.CharField(max_length=500, blank=True)
    last_issue_api_url = models.URLField(max_length=500, blank=True)

    list_data_refreshed_at = models.DateTimeField(null=True, blank=True)

    detail_hydration_attempted_at = models.DateTimeField(null=True, blank=True)
    detail_hydrated_at = models.DateTimeField(null=True, blank=True)
    latest_local_issue_store_date = models.DateField(null=True, blank=True)

    run_status = models.CharField(
        max_length=30,
        choices=RUN_STATUS_CHOICES,
        default=RUN_STATUS_UNKNOWN,
    )
    run_status_source = models.CharField(
        max_length=30,
        choices=RUN_STATUS_SOURCE_CHOICES,
        default=RUN_STATUS_SOURCE_UNKNOWN,
    )
    run_status_checked_at = models.DateTimeField(null=True, blank=True)
    manual_final_issue_store_date = models.DateField(null=True, blank=True)
    manual_status_notes = models.TextField(blank=True)

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
    issue_title = models.CharField(max_length=500, blank=True)

    cover_date = models.DateField(null=True, blank=True)
    store_date = models.DateField(null=True, blank=True)

    date_added = models.DateTimeField(null=True, blank=True)
    date_last_updated = models.DateTimeField(null=True, blank=True)

    comicvine_url = models.URLField(max_length=500, blank=True)
    api_detail_url = models.URLField(max_length=500, blank=True)

    aliases = models.TextField(blank=True)
    deck = models.TextField(blank=True)
    description = models.TextField(blank=True)
    has_staff_review = models.BooleanField(default=False)

    detail_hydration_attempted_at = models.DateTimeField(null=True, blank=True)
    detail_hydrated_at = models.DateTimeField(null=True, blank=True)

    comicvine_image_icon_url = models.URLField(max_length=500, blank=True)
    comicvine_image_medium_url = models.URLField(max_length=500, blank=True)
    comicvine_image_screen_url = models.URLField(max_length=500, blank=True)
    comicvine_image_screen_large_url = models.URLField(max_length=500, blank=True)
    comicvine_image_small_url = models.URLField(max_length=500, blank=True)
    comicvine_image_super_url = models.URLField(max_length=500, blank=True)
    comicvine_image_thumb_url = models.URLField(max_length=500, blank=True)
    comicvine_image_tiny_url = models.URLField(max_length=500, blank=True)
    comicvine_image_original_url = models.URLField(max_length=500, blank=True)
    comicvine_image_tags = models.CharField(max_length=500, blank=True)

    notes = models.TextField(blank=True)

    def __str__(self):
        volume_name = self.volume.name if self.volume else "Unknown Volume"
        return f"{volume_name} #{self.issue_number}"


class ComicPerson(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=500)
    api_detail_url = models.URLField(max_length=500, blank=True)
    comicvine_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ComicVineNamedEntity(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=500)
    api_detail_url = models.URLField(max_length=500, blank=True)
    comicvine_url = models.URLField(max_length=500, blank=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class ComicCharacter(ComicVineNamedEntity):
    pass


class ComicTeam(ComicVineNamedEntity):
    pass


class ComicLocation(ComicVineNamedEntity):
    pass


class ComicConcept(ComicVineNamedEntity):
    pass


class ComicObject(ComicVineNamedEntity):
    pass


class ComicStoryArc(ComicVineNamedEntity):
    pass


class ComicCreditRole(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ComicIssuePersonCredit(models.Model):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="person_credits",
    )
    person = models.ForeignKey(
        ComicPerson,
        on_delete=models.CASCADE,
        related_name="issue_credits",
    )
    role = models.ForeignKey(
        ComicCreditRole,
        on_delete=models.PROTECT,
        related_name="issue_credits",
    )
    api_detail_url = models.URLField(max_length=500, blank=True)
    comicvine_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["issue", "role", "person"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "person", "role"],
                name="unique_issue_person_role_credit",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.person} ({self.role})"


class ComicVolumePersonCredit(models.Model):
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.CASCADE,
        related_name="person_credits",
    )
    person = models.ForeignKey(
        ComicPerson,
        on_delete=models.CASCADE,
        related_name="volume_credits",
    )
    credit_count = models.PositiveIntegerField(null=True, blank=True)
    api_detail_url = models.URLField(max_length=500, blank=True)
    comicvine_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["volume", "person"]
        constraints = [
            models.UniqueConstraint(
                fields=["volume", "person"],
                name="unique_volume_person_credit",
            )
        ]

    def __str__(self):
        if self.credit_count is not None:
            return f"{self.volume} — {self.person} ({self.credit_count})"

        return f"{self.volume} — {self.person}"


class ComicIssueRelationship(models.Model):
    RELATION_CREDIT = "credit"
    RELATION_FIRST_APPEARANCE = "first_appearance"
    RELATION_DIED_IN = "died_in"
    RELATION_DISBANDED_IN = "disbanded_in"

    RELATION_TYPE_CHOICES = [
        (RELATION_CREDIT, "Credit"),
        (RELATION_FIRST_APPEARANCE, "First appearance"),
        (RELATION_DIED_IN, "Died in"),
        (RELATION_DISBANDED_IN, "Disbanded in"),
    ]

    relation_type = models.CharField(
        max_length=30,
        choices=RELATION_TYPE_CHOICES,
        default=RELATION_CREDIT,
    )

    class Meta:
        abstract = True

    def get_relation_display_name(self):
        return self.get_relation_type_display()


class ComicIssueCharacterLink(ComicIssueRelationship):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="character_links",
    )
    character = models.ForeignKey(
        ComicCharacter,
        on_delete=models.CASCADE,
        related_name="issue_links",
    )

    class Meta:
        ordering = ["issue", "relation_type", "character"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "character", "relation_type"],
                name="unique_issue_character_relation",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.character} ({self.get_relation_display_name()})"


class ComicIssueTeamLink(ComicIssueRelationship):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="team_links",
    )
    team = models.ForeignKey(
        ComicTeam,
        on_delete=models.CASCADE,
        related_name="issue_links",
    )

    class Meta:
        ordering = ["issue", "relation_type", "team"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "team", "relation_type"],
                name="unique_issue_team_relation",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.team} ({self.get_relation_display_name()})"


class ComicIssueLocationLink(ComicIssueRelationship):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="location_links",
    )
    location = models.ForeignKey(
        ComicLocation,
        on_delete=models.CASCADE,
        related_name="issue_links",
    )

    class Meta:
        ordering = ["issue", "relation_type", "location"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "location", "relation_type"],
                name="unique_issue_location_relation",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.location} ({self.get_relation_display_name()})"


class ComicIssueConceptLink(ComicIssueRelationship):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="concept_links",
    )
    concept = models.ForeignKey(
        ComicConcept,
        on_delete=models.CASCADE,
        related_name="issue_links",
    )

    class Meta:
        ordering = ["issue", "relation_type", "concept"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "concept", "relation_type"],
                name="unique_issue_concept_relation",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.concept} ({self.get_relation_display_name()})"


class ComicIssueObjectLink(ComicIssueRelationship):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="object_links",
    )
    comic_object = models.ForeignKey(
        ComicObject,
        on_delete=models.CASCADE,
        related_name="issue_links",
    )

    class Meta:
        ordering = ["issue", "relation_type", "comic_object"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "comic_object", "relation_type"],
                name="unique_issue_object_relation",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.comic_object} ({self.get_relation_display_name()})"


class ComicIssueStoryArcLink(ComicIssueRelationship):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="story_arc_links",
    )
    story_arc = models.ForeignKey(
        ComicStoryArc,
        on_delete=models.CASCADE,
        related_name="issue_links",
    )

    class Meta:
        ordering = ["issue", "relation_type", "story_arc"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "story_arc", "relation_type"],
                name="unique_issue_story_arc_relation",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.story_arc} ({self.get_relation_display_name()})"


class ComicIssueAssociatedImage(models.Model):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="associated_images",
    )
    position = models.PositiveIntegerField(default=0)

    caption = models.CharField(max_length=500, blank=True)

    icon_url = models.URLField(max_length=500, blank=True)
    medium_url = models.URLField(max_length=500, blank=True)
    screen_url = models.URLField(max_length=500, blank=True)
    screen_large_url = models.URLField(max_length=500, blank=True)
    small_url = models.URLField(max_length=500, blank=True)
    super_url = models.URLField(max_length=500, blank=True)
    thumb_url = models.URLField(max_length=500, blank=True)
    tiny_url = models.URLField(max_length=500, blank=True)
    original_url = models.URLField(max_length=500, blank=True)
    image_tags = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["issue", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "position"],
                name="unique_issue_associated_image_position",
            )
        ]

    def __str__(self):
        return f"{self.issue} — associated image {self.position}"


class ComicVineDateScan(models.Model):
    ISSUE_DATE_ADDED = "issue_date_added"
    ISSUE_DATE_LAST_UPDATED = "issue_date_last_updated"
    VOLUME_DATE_ADDED = "volume_date_added"
    VOLUME_DATE_LAST_UPDATED = "volume_date_last_updated"

    SCAN_KIND_CHOICES = [
        (ISSUE_DATE_ADDED, "Issue date added"),
        (ISSUE_DATE_LAST_UPDATED, "Issue date last updated"),
        (VOLUME_DATE_ADDED, "Volume date added"),
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