from django.db import models

class ComicIssue(models.Model):
    series_title = models.CharField(max_length=200)
    issue_number = models.CharField(max_length=20)
    issue_title = models.CharField(max_length=200, blank=True)
    publisher = models.CharField(max_length=100, blank=True)
    release_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.series_title} #{self.issue_number}"