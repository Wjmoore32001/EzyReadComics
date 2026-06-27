from django.db import models


class ComicVolume(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    publisher = models.CharField(max_length=100, blank=True)
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
    cover_date = models.DateField(null=True, blank=True)
    store_date = models.DateField(null=True, blank=True)
    comicvine_url = models.URLField(blank=True)
    image_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        volume_name = self.volume.name if self.volume else "Unknown Volume"
        return f"{volume_name} #{self.issue_number}"