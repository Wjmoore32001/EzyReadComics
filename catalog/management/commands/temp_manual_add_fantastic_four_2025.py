from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import (
    ComicIssue,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)


PUBLISHER_DATA = {
    "name": "Marvel",
    "slug": "marvel",
}


RUN_DATA = {
    "title": "Fantastic Four",
    "start_year": "2025",
    "first_issue_date": date(2025, 7, 9),
    "last_issue_date": date(2026, 7, 1),
    "status": ComicRun.STATUS_ONGOING,
    "issue_count": 13,
    "description": (
        "The current ongoing Fantastic Four run from Marvel, beginning in 2025. "
        "Written by Ryan North with art by Humberto Ramos, this run launches a new era "
        "for Marvel's First Family."
    ),
}


VOLUME_DATA = {
    "title": "Fantastic Four Vol. 1: Save Everyone",
    "volume_number": "1",
    "first_issue_number": "1",
    "last_issue_number": "5",
    "release_date": date(2026, 3, 11),
    "issue_count": 5,
    "description": (
        "The first collected volume of the 2025 Fantastic Four run by Ryan North and "
        "Humberto Ramos, collecting Fantastic Four #1-5."
    ),
}


ISSUES = [
    {
        "issue_number": "1",
        "title": "The Uncommon Era",
        "cover_date": date(2025, 9, 1),
        "store_date": date(2025, 7, 9),
        "description": (
            "A new era for Marvel's First Family begins when a fight with Doom sends "
            "Reed, Sue, Ben, and Johnny to different eras of Earth's history."
        ),
    },
    {
        "issue_number": "2",
        "title": "",
        "cover_date": date(2025, 10, 1),
        "store_date": date(2025, 8, 13),
        "description": (
            "Sue is stranded at the end of Earth's history while Reed waits in Earth's "
            "past, and Doom reveals the secret behind his apparent invincibility."
        ),
    },
    {
        "issue_number": "3",
        "title": "",
        "cover_date": date(2025, 11, 1),
        "store_date": date(2025, 9, 17),
        "description": (
            "Doom's secret has been revealed, and the Fantastic Four head into his hidden "
            "Antarctic lair to face their next challenge."
        ),
    },
    {
        "issue_number": "4",
        "title": "Basic Obedience",
        "cover_date": date(2025, 12, 1),
        "store_date": date(2025, 10, 22),
        "description": (
            "Alicia Masters returns home and realizes the Fantastic Four's new dog is not "
            "what everyone else thinks it is."
        ),
    },
    {
        "issue_number": "5",
        "title": "Bad Blood",
        "cover_date": date(2026, 1, 1),
        "store_date": date(2025, 11, 12),
        "description": (
            "Sue Storm gets pulled into a murder mystery when Felicia Hardy, the Black Cat, "
            "arrives at the Baxter Building accused of murder."
        ),
    },
    {
        "issue_number": "6",
        "title": "The Invincible Woman, Part One: The Unobservable Universe",
        "cover_date": date(2026, 2, 1),
        "store_date": date(2025, 12, 3),
        "description": (
            "The Invincible Woman story begins as an alien threat targets Earth, the Wizard "
            "moves against the Baxter Building, and the Future Foundation begins to take shape."
        ),
    },
    {
        "issue_number": "7",
        "title": "The Invincible Woman, Part Two: All Mankind's Concern",
        "cover_date": date(2026, 3, 1),
        "store_date": date(2026, 1, 21),
        "description": (
            "The Fantastic Four discover that Sue Storm has become one of the most wanted "
            "people in the universe, putting both her and Earth in danger."
        ),
    },
    {
        "issue_number": "8",
        "title": "The Invincible Woman, Part Three: Strange Secret Origin",
        "cover_date": date(2026, 4, 1),
        "store_date": date(2026, 2, 18),
        "description": (
            "The Invincible Woman story looks back to Susan Storm's earliest days as the "
            "Invisible Girl and the mistakes that shaped what came after."
        ),
    },
    {
        "issue_number": "9",
        "title": "The Invincible Woman, Part Four: The Mud and the Stars",
        "cover_date": date(2026, 5, 1),
        "store_date": date(2026, 3, 25),
        "description": (
            "The Fantastic Four continue their mission in space as Galactus faces the threat "
            "of the Invincible Woman and Earth is left vulnerable."
        ),
    },
    {
        "issue_number": "10",
        "title": "The Invincible Woman, Part Five: Earth Versus the Invincible Woman",
        "cover_date": date(2026, 7, 1),
        "store_date": date(2026, 5, 6),
        "description": (
            "The Invincible Woman arc reaches its finale as Earth faces invasion and the "
            "Fantastic Four and S.H.I.E.L.D. try to stop the threat."
        ),
    },
    {
        "issue_number": "11",
        "title": "Future's Foundation; The Digger in the Dark",
        "cover_date": date(2026, 7, 1),
        "store_date": date(2026, 5, 20),
        "description": (
            "The new Future Foundation is introduced while Doom's technology spreads into "
            "the wider world and the Fantastic Four face the return of Crimeasaurus Rex."
        ),
    },
    {
        "issue_number": "12",
        "title": "Sī Fuerīs Rōmae",
        "cover_date": date(2026, 8, 1),
        "store_date": date(2026, 6, 3),
        "description": (
            "Johnny and Reed travel back to Ancient Rome to stop an alien invasion that "
            "threatens to erase history."
        ),
    },
    {
        "issue_number": "13",
        "title": "",
        "cover_date": date(2026, 9, 1),
        "store_date": date(2026, 7, 1),
        "description": (
            "Johnny convinces Sue to help with a risky plan involving his powers, her "
            "invisibility, and a Ghost Rider-style scheme that can go badly wrong."
        ),
    },
]


VOLUME_ISSUE_ORDERS = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
}


def is_empty(value):
    return value is None or value == ""


def set_field(obj, field_name, value, overwrite=False):
    current_value = getattr(obj, field_name)

    if overwrite or is_empty(current_value):
        setattr(obj, field_name, value)
        return True

    return False


def save_if_changed(obj, changed_fields, dry_run):
    if not changed_fields:
        return False

    if not dry_run:
        obj.save(update_fields=sorted(set(changed_fields)))

    return True


class Command(BaseCommand):
    help = (
        "Temporary manual catalog seeder for Fantastic Four (2025). "
        "Adds hard-coded issues and links Fantastic Four Vol. 1 to issues #1-5."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created/updated without writing to the database.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing issue/run/volume fields instead of only filling blanks.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]

        created_counts = {
            "publishers": 0,
            "runs": 0,
            "volumes": 0,
            "issues": 0,
            "volume_issue_links": 0,
        }
        updated_counts = {
            "publishers": 0,
            "runs": 0,
            "volumes": 0,
            "issues": 0,
            "volume_issue_links": 0,
        }

        with transaction.atomic():
            publisher, publisher_created = self.get_or_create_publisher(dry_run)
            if publisher_created:
                created_counts["publishers"] += 1
            elif self.update_publisher(publisher, overwrite, dry_run):
                updated_counts["publishers"] += 1

            run, run_created = self.get_or_create_run(publisher, dry_run)
            if run_created:
                created_counts["runs"] += 1
            elif self.update_run(run, overwrite, dry_run):
                updated_counts["runs"] += 1

            volume, volume_created = self.get_or_create_volume(publisher, run, dry_run)
            if volume_created:
                created_counts["volumes"] += 1
            elif self.update_volume(volume, publisher, run, overwrite, dry_run):
                updated_counts["volumes"] += 1

            issues_by_number = {}
            for issue_data in ISSUES:
                issue, issue_created = self.get_or_create_issue(run, issue_data, dry_run)
                issues_by_number[issue.issue_number] = issue

                if issue_created:
                    created_counts["issues"] += 1
                elif self.update_issue(issue, issue_data, overwrite, dry_run):
                    updated_counts["issues"] += 1

            for issue_number, issue_order in VOLUME_ISSUE_ORDERS.items():
                issue = issues_by_number[issue_number]
                link_created, link_updated = self.create_or_update_volume_issue_link(
                    volume=volume,
                    issue=issue,
                    issue_order=issue_order,
                    dry_run=dry_run,
                )

                if link_created:
                    created_counts["volume_issue_links"] += 1
                elif link_updated:
                    updated_counts["volume_issue_links"] += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write("Manual Fantastic Four (2025) catalog seed complete")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Dry run: {'yes' if dry_run else 'no'}")
        self.stdout.write(f"Overwrite existing fields: {'yes' if overwrite else 'no'}")

        self.stdout.write("")
        self.stdout.write("Created")
        self.stdout.write("-" * 60)
        for label, count in created_counts.items():
            self.stdout.write(f"{label}: {count}")

        self.stdout.write("")
        self.stdout.write("Updated")
        self.stdout.write("-" * 60)
        for label, count in updated_counts.items():
            self.stdout.write(f"{label}: {count}")

    def get_or_create_publisher(self, dry_run):
        publisher = ComicPublisher.objects.filter(name=PUBLISHER_DATA["name"]).first()

        if publisher:
            return publisher, False

        publisher = ComicPublisher(
            name=PUBLISHER_DATA["name"],
            slug=PUBLISHER_DATA["slug"],
        )

        if not dry_run:
            publisher.save()

        return publisher, True

    def update_publisher(self, publisher, overwrite, dry_run):
        changed_fields = []

        if set_field(publisher, "slug", PUBLISHER_DATA["slug"], overwrite=overwrite):
            changed_fields.append("slug")

        return save_if_changed(publisher, changed_fields, dry_run)

    def get_or_create_run(self, publisher, dry_run):
        run = (
            ComicRun.objects.filter(
                publisher=publisher,
                title=RUN_DATA["title"],
                start_year=RUN_DATA["start_year"],
            )
            .order_by("id")
            .first()
        )

        if run:
            return run, False

        run = ComicRun(
            publisher=publisher,
            title=RUN_DATA["title"],
            start_year=RUN_DATA["start_year"],
            first_issue_date=RUN_DATA["first_issue_date"],
            last_issue_date=RUN_DATA["last_issue_date"],
            status=RUN_DATA["status"],
            issue_count=RUN_DATA["issue_count"],
            description=RUN_DATA["description"],
        )

        if not dry_run:
            run.save()

        return run, True

    def update_run(self, run, overwrite, dry_run):
        changed_fields = []

        for field_name in [
            "first_issue_date",
            "last_issue_date",
            "status",
            "issue_count",
            "description",
        ]:
            if set_field(run, field_name, RUN_DATA[field_name], overwrite=overwrite):
                changed_fields.append(field_name)

        return save_if_changed(run, changed_fields, dry_run)

    def get_or_create_volume(self, publisher, run, dry_run):
        volume = (
            ComicVolume.objects.filter(
                publisher=publisher,
                run=run,
                volume_number=VOLUME_DATA["volume_number"],
            )
            .order_by("id")
            .first()
        )

        if volume:
            return volume, False

        volume = ComicVolume(
            publisher=publisher,
            run=run,
            title=VOLUME_DATA["title"],
            volume_number=VOLUME_DATA["volume_number"],
            first_issue_number=VOLUME_DATA["first_issue_number"],
            last_issue_number=VOLUME_DATA["last_issue_number"],
            release_date=VOLUME_DATA["release_date"],
            issue_count=VOLUME_DATA["issue_count"],
            description=VOLUME_DATA["description"],
        )

        if not dry_run:
            volume.save()

        return volume, True

    def update_volume(self, volume, publisher, run, overwrite, dry_run):
        changed_fields = []

        if volume.publisher_id != publisher.id:
            volume.publisher = publisher
            changed_fields.append("publisher")

        if volume.run_id != run.id:
            volume.run = run
            changed_fields.append("run")

        for field_name in [
            "title",
            "volume_number",
            "first_issue_number",
            "last_issue_number",
            "release_date",
            "issue_count",
            "description",
        ]:
            if set_field(volume, field_name, VOLUME_DATA[field_name], overwrite=overwrite):
                changed_fields.append(field_name)

        return save_if_changed(volume, changed_fields, dry_run)

    def get_or_create_issue(self, run, issue_data, dry_run):
        issue = (
            ComicIssue.objects.filter(
                run=run,
                issue_number=issue_data["issue_number"],
            )
            .order_by("id")
            .first()
        )

        if issue:
            return issue, False

        issue = ComicIssue(
            run=run,
            issue_number=issue_data["issue_number"],
            title=issue_data["title"],
            cover_date=issue_data["cover_date"],
            store_date=issue_data["store_date"],
            description=issue_data["description"],
        )

        if not dry_run:
            issue.save()

        return issue, True

    def update_issue(self, issue, issue_data, overwrite, dry_run):
        changed_fields = []

        for field_name in [
            "title",
            "cover_date",
            "store_date",
            "description",
        ]:
            if set_field(issue, field_name, issue_data[field_name], overwrite=overwrite):
                changed_fields.append(field_name)

        return save_if_changed(issue, changed_fields, dry_run)

    def create_or_update_volume_issue_link(self, volume, issue, issue_order, dry_run):
        link = (
            ComicVolumeIssue.objects.filter(
                volume=volume,
                issue=issue,
            )
            .order_by("id")
            .first()
        )

        if link is None:
            link = ComicVolumeIssue(
                volume=volume,
                issue=issue,
                issue_order=issue_order,
            )

            if not dry_run:
                link.save()

            return True, False

        if link.issue_order == issue_order:
            return False, False

        link.issue_order = issue_order

        if not dry_run:
            link.save(update_fields=["issue_order"])

        return False, True