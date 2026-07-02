from django.db import models

from catalog.models.core import ComicIssue, ComicRun, ComicVolume


class CreditPerson(models.Model):
    name = models.CharField(max_length=500, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CreditRole(models.Model):
    name = models.CharField(max_length=100, unique=True)
    display_order = models.PositiveIntegerField(default=100)
    show_by_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class ComicRunCredit(models.Model):
    run = models.ForeignKey(
        ComicRun,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    person = models.ForeignKey(
        CreditPerson,
        on_delete=models.CASCADE,
        related_name="run_credits",
    )
    role = models.ForeignKey(
        CreditRole,
        on_delete=models.PROTECT,
        related_name="run_credits",
    )

    credit_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["run", "role__display_order", "credit_order", "person__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "person", "role"],
                name="unique_comic_run_person_role_credit",
            )
        ]

    def __str__(self):
        return f"{self.run} — {self.person} ({self.role})"


class ComicIssueCredit(models.Model):
    issue = models.ForeignKey(
        ComicIssue,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    person = models.ForeignKey(
        CreditPerson,
        on_delete=models.CASCADE,
        related_name="issue_credits",
    )
    role = models.ForeignKey(
        CreditRole,
        on_delete=models.PROTECT,
        related_name="issue_credits",
    )

    credit_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["issue", "role__display_order", "credit_order", "person__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "person", "role"],
                name="unique_comic_issue_person_role_credit",
            )
        ]

    def __str__(self):
        return f"{self.issue} — {self.person} ({self.role})"


class ComicVolumeCredit(models.Model):
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    person = models.ForeignKey(
        CreditPerson,
        on_delete=models.CASCADE,
        related_name="volume_credits",
    )
    role = models.ForeignKey(
        CreditRole,
        on_delete=models.PROTECT,
        related_name="volume_credits",
    )

    credit_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["volume", "role__display_order", "credit_order", "person__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["volume", "person", "role"],
                name="unique_comic_volume_person_role_credit",
            )
        ]

    def __str__(self):
        return f"{self.volume} — {self.person} ({self.role})"