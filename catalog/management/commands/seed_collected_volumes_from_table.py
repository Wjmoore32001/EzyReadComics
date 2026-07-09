from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from catalog.models import (
    ComicIssue,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeIssue,
)


def issue_range(first, last):
    return [str(number) for number in range(first, last + 1)]


def issue_list(*issue_numbers):
    return [str(issue_number) for issue_number in issue_numbers]


def normalize(value):
    return str(value or "").casefold().strip()


def build_display_preview(run_title, volume_title, volume_number):
    run_title = str(run_title or "").strip()
    volume_title = str(volume_title or "").strip()
    volume_number = str(volume_number or "").strip()

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


VOLUME_DATA = [
    {
        "publisher": "Marvel",
        "run_title": "X-Men",
        "run_start_year": "2024",
        "title": "Homecoming",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "7",
        "release_date": "2025-03-12",
        "issue_count": 7,
        "issue_refs": [
            {
                "run_title": "X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_range(1, 7),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "X-Men",
        "run_start_year": "2024",
        "title": "Raid on Graymalkin",
        "volume_number": "",
        "first_issue_number": "8",
        "last_issue_number": "10",
        "release_date": "2025-06-18",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_range(8, 10),
            },
            {
                "run_title": "Uncanny X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_range(7, 8),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "X-Men",
        "run_start_year": "2024",
        "title": "Hostile Takeover",
        "volume_number": "2",
        "first_issue_number": "11",
        "last_issue_number": "18",
        "release_date": "2025-08-20",
        "issue_count": 7,
        "issue_refs": [
            {
                "run_title": "X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_list(11, 12, 14, 15, 16, 17, 18),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "X-Men",
        "run_start_year": "2024",
        "title": "The Hellfire Vigil",
        "volume_number": "3",
        "first_issue_number": "19",
        "last_issue_number": "22",
        "release_date": "2025-12-17",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_range(19, 22),
            },
            {
                "run_title": "X-Men: Hellfire Vigil",
                "run_start_year": "2025",
                "issue_numbers": issue_list(1),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Uncanny X-Men",
        "run_start_year": "2024",
        "title": "Red Wave",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "6",
        "release_date": "2025-04-09",
        "issue_count": 6,
        "issue_refs": [
            {
                "run_title": "Uncanny X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_range(1, 6),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Uncanny X-Men",
        "run_start_year": "2024",
        "title": "The Dark Atery",
        "volume_number": "2",
        "first_issue_number": "9",
        "last_issue_number": "16",
        "release_date": "2025-08-06",
        "issue_count": 8,
        "issue_refs": [
            {
                "run_title": "Uncanny X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_range(9, 16),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Uncanny X-Men",
        "run_start_year": "2024",
        "title": "Murder Me, Mutina",
        "volume_number": "3",
        "first_issue_number": "17",
        "last_issue_number": "21",
        "release_date": "2025-12-17",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Uncanny X-Men",
                "run_start_year": "2024",
                "issue_numbers": issue_range(17, 21),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Fantastic Four",
        "run_start_year": "2025",
        "title": "Save Everyone",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "5",
        "release_date": "2026-03-11",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Fantastic Four",
                "run_start_year": "2025",
                "issue_numbers": issue_range(1, 5),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Wolverine",
        "run_start_year": "2024",
        "title": "In the Bones",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "5",
        "release_date": "2025-05-28",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Wolverine",
                "run_start_year": "2024",
                "issue_numbers": issue_range(1, 5),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Wolverine",
        "run_start_year": "2024",
        "title": "Call of the Adamantine",
        "volume_number": "2",
        "first_issue_number": "6",
        "last_issue_number": "10",
        "release_date": "2025-10-29",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Wolverine",
                "run_start_year": "2024",
                "issue_numbers": issue_range(6, 10),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Wolverine",
        "run_start_year": "2024",
        "title": "Mutant Protector",
        "volume_number": "3",
        "first_issue_number": "13",
        "last_issue_number": "16",
        "release_date": "2026-06-24",
        "issue_count": 4,
        "issue_refs": [
            {
                "run_title": "Wolverine",
                "run_start_year": "2024",
                "issue_numbers": issue_range(13, 16),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Captain America",
        "run_start_year": "2025",
        "title": "Our Secret Wars",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "5",
        "release_date": "2026-07-01",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Captain America",
                "run_start_year": "2025",
                "issue_numbers": issue_range(1, 5),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Red Hulk",
        "run_start_year": "2025",
        "title": "Prisoner of War",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "5",
        "release_date": "2025-10-22",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Red Hulk",
                "run_start_year": "2025",
                "issue_numbers": issue_range(1, 5),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Red Hulk",
        "run_start_year": "2025",
        "title": "Mission: Latveria",
        "volume_number": "2",
        "first_issue_number": "6",
        "last_issue_number": "10",
        "release_date": "2026-03-11",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Red Hulk",
                "run_start_year": "2025",
                "issue_numbers": issue_range(6, 10),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Ultimate Spider-Man",
        "run_start_year": "2024",
        "title": "Married with Children",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "6",
        "release_date": "2024-09-11",
        "issue_count": 6,
        "issue_refs": [
            {
                "run_title": "Ultimate Spider-Man",
                "run_start_year": "2024",
                "issue_numbers": issue_range(1, 6),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Ultimate Spider-Man",
        "run_start_year": "2024",
        "title": "The Paper",
        "volume_number": "2",
        "first_issue_number": "7",
        "last_issue_number": "12",
        "release_date": "2025-03-19",
        "issue_count": 6,
        "issue_refs": [
            {
                "run_title": "Ultimate Spider-Man",
                "run_start_year": "2024",
                "issue_numbers": issue_range(7, 12),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Ultimate Spider-Man",
        "run_start_year": "2024",
        "title": "Family Business",
        "volume_number": "3",
        "first_issue_number": "13",
        "last_issue_number": "18",
        "release_date": "2025-09-24",
        "issue_count": 6,
        "issue_refs": [
            {
                "run_title": "Ultimate Spider-Man",
                "run_start_year": "2024",
                "issue_numbers": issue_range(13, 18),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Ultimates",
        "run_start_year": "2024",
        "title": "Fix the World",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "6",
        "release_date": "2025-02-05",
        "issue_count": 7,
        "issue_refs": [
            {
                "run_title": "Ultimates",
                "run_start_year": "2024",
                "issue_numbers": issue_range(1, 6),
            },
            {
                "run_title": "Ultimate Universe",
                "run_start_year": "2023",
                "issue_numbers": issue_list(1),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Ultimates",
        "run_start_year": "2024",
        "title": "All Power to the People",
        "volume_number": "2",
        "first_issue_number": "7",
        "last_issue_number": "12",
        "release_date": "2025-09-17",
        "issue_count": 6,
        "issue_refs": [
            {
                "run_title": "Ultimates",
                "run_start_year": "2024",
                "issue_numbers": issue_range(7, 12),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Ultimates",
        "run_start_year": "2024",
        "title": "Rescue Mission",
        "volume_number": "3",
        "first_issue_number": "13",
        "last_issue_number": "18",
        "release_date": "2026-03-18",
        "issue_count": 7,
        "issue_refs": [
            {
                "run_title": "Ultimates",
                "run_start_year": "2024",
                "issue_numbers": issue_range(13, 18),
            },
            {
                "run_title": "Ultimate Hawkeye",
                "run_start_year": "2025",
                "issue_numbers": issue_list(1),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Iron Man",
        "run_start_year": "2024",
        "title": "The Stark-Roxxon War",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "5",
        "release_date": "2025-06-25",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Iron Man",
                "run_start_year": "2024",
                "issue_numbers": issue_range(1, 5),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Iron Man",
        "run_start_year": "2024",
        "title": "The Insurgent Iron Man",
        "volume_number": "2",
        "first_issue_number": "6",
        "last_issue_number": "10",
        "release_date": "2025-12-10",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Iron Man",
                "run_start_year": "2024",
                "issue_numbers": issue_range(6, 10),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Amazing Spider-Man",
        "run_start_year": "2025",
        "title": "Get Back Up",
        "volume_number": "1",
        "first_issue_number": "1",
        "last_issue_number": "5",
        "release_date": "2025-12-10",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Amazing Spider-Man",
                "run_start_year": "2025",
                "issue_numbers": issue_range(1, 5),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Amazing Spider-Man",
        "run_start_year": "2025",
        "title": "Through the Gates of Hell",
        "volume_number": "2",
        "first_issue_number": "6",
        "last_issue_number": "10",
        "release_date": "2026-03-04",
        "issue_count": 5,
        "issue_refs": [
            {
                "run_title": "Amazing Spider-Man",
                "run_start_year": "2025",
                "issue_numbers": issue_range(6, 10),
            },
        ],
    },
    {
        "publisher": "Marvel",
        "run_title": "Amazing Spider-Man",
        "run_start_year": "2025",
        "title": "Resolute",
        "volume_number": "3",
        "first_issue_number": "12",
        "last_issue_number": "21",
        "release_date": "2026-06-10",
        "issue_count": 6,
        "issue_refs": [
            {
                "run_title": "Amazing Spider-Man",
                "run_start_year": "2025",
                "issue_numbers": issue_list(12, 14, 16, 18, 20, 21),
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Temporary command to seed collected volumes and volume/issue links from the pasted Marvel collection table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change, then roll everything back.",
        )
        parser.add_argument(
            "--keep-extra-links",
            action="store_true",
            help="Do not remove existing issue links from these volumes when they are not in the table.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        remove_extra_links = not options["keep_extra_links"]

        stats = {
            "publishers_created": 0,
            "runs_created": 0,
            "runs_updated": 0,
            "issues_created": 0,
            "volumes_created": 0,
            "volumes_updated": 0,
            "volume_issue_links_created": 0,
            "volume_issue_links_updated": 0,
            "volume_issue_links_removed": 0,
            "duplicate_volume_matches": 0,
        }

        self.stdout.write("=" * 80)
        self.stdout.write("Seeding collected volumes from pasted table")
        self.stdout.write(f"Dry run: {'yes' if dry_run else 'no'}")
        self.stdout.write(f"Remove stale volume issue links: {'yes' if remove_extra_links else 'no'}")
        self.stdout.write("=" * 80)

        with transaction.atomic():
            for volume_data in VOLUME_DATA:
                self.seed_volume(
                    volume_data=volume_data,
                    stats=stats,
                    remove_extra_links=remove_extra_links,
                )

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write("Done.")
        self.stdout.write(f"  publishers created: {stats['publishers_created']}")
        self.stdout.write(f"  runs created: {stats['runs_created']}")
        self.stdout.write(f"  runs updated: {stats['runs_updated']}")
        self.stdout.write(f"  issues created: {stats['issues_created']}")
        self.stdout.write(f"  volumes created: {stats['volumes_created']}")
        self.stdout.write(f"  volumes updated: {stats['volumes_updated']}")
        self.stdout.write(f"  volume issue links created: {stats['volume_issue_links_created']}")
        self.stdout.write(f"  volume issue links updated: {stats['volume_issue_links_updated']}")
        self.stdout.write(f"  volume issue links removed: {stats['volume_issue_links_removed']}")

        if stats["duplicate_volume_matches"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Warning: {stats['duplicate_volume_matches']} volume lookup(s) matched more than one existing row. "
                    "The command updated the oldest matching row and left the others alone."
                )
            )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry run only. No database changes were saved."))

    def seed_volume(self, volume_data, stats, remove_extra_links):
        publisher = self.get_or_create_publisher(volume_data["publisher"], stats)

        primary_run = self.get_or_create_run(
            publisher=publisher,
            title=volume_data["run_title"],
            start_year=volume_data["run_start_year"],
            stats=stats,
        )

        volume, created = self.get_or_create_volume(
            publisher=publisher,
            primary_run=primary_run,
            volume_data=volume_data,
            stats=stats,
        )

        if created:
            stats["volumes_created"] += 1
        else:
            changed = self.update_volume_from_table(volume, volume_data)

            if changed:
                volume.save(
                    update_fields=[
                        "publisher",
                        "run",
                        "title",
                        "volume_number",
                        "first_issue_number",
                        "last_issue_number",
                        "release_date",
                        "issue_count",
                        "updated_at",
                    ]
                )
                stats["volumes_updated"] += 1

        expected_issue_ids = []
        issue_order = 1

        for issue_ref in volume_data["issue_refs"]:
            issue_run = self.get_or_create_run(
                publisher=publisher,
                title=issue_ref["run_title"],
                start_year=issue_ref["run_start_year"],
                stats=stats,
            )

            for issue_number in issue_ref["issue_numbers"]:
                issue, issue_created = ComicIssue.objects.get_or_create(
                    run=issue_run,
                    issue_number=str(issue_number),
                    defaults={
                        "title": "",
                    },
                )

                if issue_created:
                    stats["issues_created"] += 1

                link, link_created = ComicVolumeIssue.objects.get_or_create(
                    volume=volume,
                    issue=issue,
                    defaults={
                        "issue_order": issue_order,
                    },
                )

                if link_created:
                    stats["volume_issue_links_created"] += 1
                elif link.issue_order != issue_order:
                    link.issue_order = issue_order
                    link.save(update_fields=["issue_order"])
                    stats["volume_issue_links_updated"] += 1

                expected_issue_ids.append(issue.id)
                issue_order += 1

        if remove_extra_links:
            extra_links = ComicVolumeIssue.objects.filter(volume=volume).exclude(
                issue_id__in=expected_issue_ids
            )
            removed_count = extra_links.count()

            if removed_count:
                extra_links.delete()
                stats["volume_issue_links_removed"] += removed_count

    def get_or_create_publisher(self, name, stats):
        publisher, created = ComicPublisher.objects.get_or_create(
            name=name,
            defaults={
                "slug": slugify(name),
            },
        )

        if created:
            stats["publishers_created"] += 1

        return publisher

    def get_or_create_run(self, publisher, title, start_year, stats):
        exact_run = ComicRun.objects.filter(
            publisher=publisher,
            title=title,
            start_year=start_year,
        ).first()

        if exact_run:
            return exact_run

        same_title_runs = list(
            ComicRun.objects.filter(
                publisher=publisher,
                title=title,
            ).order_by("id")
        )

        if len(same_title_runs) == 1 and not same_title_runs[0].start_year:
            run = same_title_runs[0]
            run.start_year = start_year
            run.save(update_fields=["start_year", "updated_at"])
            stats["runs_updated"] += 1
            return run

        run = ComicRun.objects.create(
            publisher=publisher,
            title=title,
            start_year=start_year,
        )
        stats["runs_created"] += 1
        return run

    def get_or_create_volume(self, publisher, primary_run, volume_data, stats):
        existing_volume = self.find_existing_volume(
            publisher=publisher,
            primary_run=primary_run,
            title=volume_data["title"],
            volume_number=volume_data["volume_number"],
            release_date=date.fromisoformat(volume_data["release_date"]),
        )

        if existing_volume:
            return existing_volume, False

        volume = ComicVolume.objects.create(
            publisher=publisher,
            run=primary_run,
            title=volume_data["title"],
            volume_number=volume_data["volume_number"],
            first_issue_number=volume_data["first_issue_number"],
            last_issue_number=volume_data["last_issue_number"],
            release_date=date.fromisoformat(volume_data["release_date"]),
            issue_count=volume_data["issue_count"],
        )
        return volume, True

    def find_existing_volume(self, publisher, primary_run, title, volume_number, release_date):
        base_qs = ComicVolume.objects.filter(
            publisher=publisher,
            run=primary_run,
        ).order_by("id")

        if volume_number:
            volume_number_matches = list(base_qs.filter(volume_number=volume_number))

            if volume_number_matches:
                if len(volume_number_matches) > 1:
                    self.increment_duplicate_volume_warning()
                return volume_number_matches[0]

        target_display_title = build_display_preview(
            run_title=primary_run.title,
            volume_title=title,
            volume_number=volume_number,
        )
        normalized_title = normalize(title)
        normalized_display_title = normalize(target_display_title)

        for volume in base_qs:
            if normalize(volume.title) in {normalized_title, normalized_display_title}:
                return volume

            if normalize(volume.display_title) == normalized_display_title:
                return volume

        release_date_matches = list(base_qs.filter(release_date=release_date))

        if len(release_date_matches) == 1:
            return release_date_matches[0]

        if len(release_date_matches) > 1:
            self.increment_duplicate_volume_warning()
            return release_date_matches[0]

        return None

    def increment_duplicate_volume_warning(self):
        if not hasattr(self, "_duplicate_volume_matches"):
            self._duplicate_volume_matches = 0

        self._duplicate_volume_matches += 1

    def update_volume_from_table(self, volume, volume_data):
        changed = False

        updates = {
            "publisher": volume.run.publisher,
            "run": volume.run,
            "title": volume_data["title"],
            "volume_number": volume_data["volume_number"],
            "first_issue_number": volume_data["first_issue_number"],
            "last_issue_number": volume_data["last_issue_number"],
            "release_date": date.fromisoformat(volume_data["release_date"]),
            "issue_count": volume_data["issue_count"],
        }

        for field_name, new_value in updates.items():
            if getattr(volume, field_name) != new_value:
                setattr(volume, field_name, new_value)
                changed = True

        return changed