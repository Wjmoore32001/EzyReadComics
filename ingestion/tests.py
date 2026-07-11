from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from catalog.models import ComicRun, ComicVolume, ComicVolumeIssue
from comicvine.models import ComicVineIssue, ComicVineVolume
from ingestion.management.commands.analyze_marvel_comicvine_volumes import (
    parse_collecting_references,
)
from ingestion.models import (
    ComicVineCollectedEditionCandidate,
    ComicVineVolumeCandidate,
    MarvelCatalogVolumeSource,
)


def create_volume(*, comicvine_id, name, start_year, count_of_issues=None):
    return ComicVineVolume.objects.create(
        comicvine_id=comicvine_id,
        name=name,
        publisher="Marvel",
        start_year=str(start_year),
        count_of_issues=count_of_issues,
    )


def create_issue(
    *,
    volume,
    comicvine_id,
    issue_number,
    title="",
    store_date=None,
    cover_date=None,
    description="",
):
    return ComicVineIssue.objects.create(
        volume=volume,
        comicvine_id=comicvine_id,
        issue_number=str(issue_number),
        issue_title=title,
        store_date=store_date,
        cover_date=cover_date,
        description=description,
    )


def create_numbered_run(
    *,
    comicvine_id,
    name,
    start_year,
    first_issue,
    last_issue,
    first_store_date,
    issue_id_base,
):
    volume = create_volume(
        comicvine_id=comicvine_id,
        name=name,
        start_year=start_year,
        count_of_issues=last_issue - first_issue + 1,
    )

    for issue_number in range(first_issue, last_issue + 1):
        create_issue(
            volume=volume,
            comicvine_id=issue_id_base + issue_number,
            issue_number=issue_number,
            title=f"Issue {issue_number}",
            store_date=(
                first_store_date
                + timedelta(days=(issue_number - first_issue) * 14)
            ),
        )

    return volume


def run_analysis(**options):
    call_command(
        "analyze_marvel_comicvine_volumes",
        stdout=StringIO(),
        **options,
    )


def run_apply(**options):
    call_command(
        "apply_marvel_ingestion_to_catalog",
        stdout=StringIO(),
        **options,
    )


class CollectingParserTests(SimpleTestCase):
    def test_parses_supported_marvel_collecting_statements(self):
        references, errors = parse_collecting_references(
            "Uncanny X-Men (2024) #1-6, X-Men (2021) #35 (C story), "
            "Free Comic Book Day 2024: Blood Hunt / X-Men #1"
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            [
                (
                    reference.title,
                    reference.start_year,
                    reference.first_issue_number,
                    reference.last_issue_number,
                    reference.standalone,
                )
                for reference in references
            ],
            [
                ("Uncanny X-Men", "2024", "1", "6", False),
                ("X-Men", "2021", "35", "35", False),
                (
                    "Free Comic Book Day 2024: Blood Hunt / X-Men",
                    "",
                    "1",
                    "1",
                    False,
                ),
            ],
        )

    def test_parses_numberless_standalone_reference(self):
        references, errors = parse_collecting_references(
            "X-Men (2024) #19 -22 and X-MEN: HELLFIRE VIGIL"
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(references), 2)
        self.assertTrue(references[1].standalone)
        self.assertEqual(references[1].title, "X-MEN: HELLFIRE VIGIL")

    def test_does_not_split_and_inside_a_series_title(self):
        references, errors = parse_collecting_references(
            "Wolverine and the X-Men (2011) #1-5 and X-Men (2024) #1"
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(references), 2)
        self.assertEqual(references[0].title, "Wolverine and the X-Men")
        self.assertEqual(references[1].title, "X-Men")


class MarvelIngestionEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.xmen_run = create_numbered_run(
            comicvine_id=158814,
            name="X-Men",
            start_year=2024,
            first_issue=1,
            last_issue=22,
            first_store_date=date(2024, 7, 10),
            issue_id_base=1_000_000,
        )
        cls.xmen_collections = create_volume(
            comicvine_id=162694,
            name="X-Men by Jed MacKay",
            start_year=2025,
            count_of_issues=3,
        )
        cls.xmen_volume_one = create_issue(
            volume=cls.xmen_collections,
            comicvine_id=1098668,
            issue_number=1,
            title="Volume 1: Homecoming",
            store_date=date(2025, 3, 12),
            description="<p>Collecting X-MEN (2024) 1-7.</p>",
        )
        create_issue(
            volume=cls.xmen_collections,
            comicvine_id=1127291,
            issue_number=2,
            title="Vol. 2: Hostile Takeover",
            store_date=date(2025, 8, 20),
            description="<p>COLLECTING: X-Men (2024) #11-18</p>",
        )
        create_issue(
            volume=cls.xmen_collections,
            comicvine_id=1149168,
            issue_number=3,
            title="Vol. 3: The Hellfire Vigil",
            store_date=date(2025, 12, 17),
            description=(
                "<p>COLLECTING: X-Men (2024) #19 -22 and "
                "X-MEN: HELLFIRE VIGIL.</p>"
            ),
        )

        hellfire_vigil = create_volume(
            comicvine_id=164000,
            name="X-Men: Hellfire Vigil",
            start_year=2025,
            count_of_issues=1,
        )
        create_issue(
            volume=hellfire_vigil,
            comicvine_id=1149000,
            issue_number=1,
            store_date=date(2025, 10, 29),
        )

        cls.uncanny_run = create_numbered_run(
            comicvine_id=159189,
            name="Uncanny X-Men",
            start_year=2024,
            first_issue=1,
            last_issue=21,
            first_store_date=date(2024, 8, 7),
            issue_id_base=1_100_000,
        )
        cls.uncanny_collections = create_volume(
            comicvine_id=163387,
            name="Uncanny X-Men by Gail Simone",
            start_year=2025,
            count_of_issues=3,
        )
        create_issue(
            volume=cls.uncanny_collections,
            comicvine_id=1103209,
            issue_number=1,
            title="Vol. 1: Red Wave",
            store_date=date(2025, 4, 9),
            description=(
                "<p>COLLECTING: Uncanny X-Men (2024) #1-6, "
                "X-Men (2021) #35 (C story), Free Comic Book Day 2024: "
                "Blood Hunt / X-Men #1.</p>"
            ),
        )
        create_issue(
            volume=cls.uncanny_collections,
            comicvine_id=1125082,
            issue_number=2,
            title="Vol. 2: The Dark Artery",
            store_date=date(2025, 8, 6),
            description="<p>COLLECTING: Uncanny X-Men (2024) #9-16</p>",
        )
        create_issue(
            volume=cls.uncanny_collections,
            comicvine_id=1149164,
            issue_number=3,
            title="Vol. 3: Murder Me, Mutina",
            store_date=date(2025, 12, 17),
            description="<p>Collecting UNCANNY X-MEN (2024) #17-21.</p>",
        )

        xmen_2021 = create_volume(
            comicvine_id=140001,
            name="X-Men",
            start_year=2021,
            count_of_issues=35,
        )
        create_issue(
            volume=xmen_2021,
            comicvine_id=900035,
            issue_number=35,
            store_date=date(2024, 6, 5),
        )
        free_comic_book_day = create_volume(
            comicvine_id=157001,
            name="Free Comic Book Day 2024: Blood Hunt / X-Men",
            start_year=2024,
            count_of_issues=1,
        )
        create_issue(
            volume=free_comic_book_day,
            comicvine_id=900036,
            issue_number=1,
            store_date=date(2024, 5, 4),
        )

        cls.fantastic_four_run = create_volume(
            comicvine_id=165358,
            name="Fantastic Four",
            start_year=2025,
            count_of_issues=13,
        )
        create_issue(
            volume=cls.fantastic_four_run,
            comicvine_id=1119095,
            issue_number=1,
            store_date=date(2025, 7, 9),
        )
        create_issue(
            volume=cls.fantastic_four_run,
            comicvine_id=1175684,
            issue_number=13,
            store_date=date(2026, 7, 1),
        )
        cls.fantastic_four_collection = create_volume(
            comicvine_id=170993,
            name="Fantastic Four",
            start_year=2026,
            count_of_issues=1,
        )
        create_issue(
            volume=cls.fantastic_four_collection,
            comicvine_id=1159467,
            issue_number=1,
            title="Vol. 1 - Save Everyone",
            store_date=date(2026, 3, 11),
        )

        cls.captain_america_run = create_numbered_run(
            comicvine_id=165232,
            name="Captain America",
            start_year=2025,
            first_issue=1,
            last_issue=2,
            first_store_date=date(2025, 7, 2),
            issue_id_base=1_200_000,
        )

    def test_analyze_and_apply_all_known_cases(self):
        run_analysis()

        for source_volume in [
            self.xmen_run,
            self.uncanny_run,
            self.fantastic_four_run,
            self.captain_america_run,
        ]:
            candidate = ComicVineVolumeCandidate.objects.get(
                comicvine_volume=source_volume
            )
            self.assertEqual(
                candidate.analysis_status,
                ComicVineVolumeCandidate.ANALYSIS_STATUS_CONFIRMED_RUN,
            )

        for source_volume in [self.xmen_collections, self.uncanny_collections]:
            candidate = ComicVineVolumeCandidate.objects.get(
                comicvine_volume=source_volume
            )
            self.assertEqual(
                candidate.analysis_status,
                ComicVineVolumeCandidate.ANALYSIS_STATUS_COLLECTION_CONTAINER,
            )

        expected_issue_counts = {
            1098668: 7,
            1127291: 8,
            1149168: 5,
            1103209: 8,
            1125082: 8,
            1149164: 5,
            1159467: 0,
        }
        collected_candidates = ComicVineCollectedEditionCandidate.objects.filter(
            comicvine_issue__comicvine_id__in=expected_issue_counts
        )
        self.assertEqual(collected_candidates.count(), 7)

        for candidate in collected_candidates:
            self.assertEqual(
                candidate.analysis_status,
                candidate.ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME,
            )
            self.assertEqual(
                candidate.source_issue_count,
                expected_issue_counts[candidate.comicvine_issue.comicvine_id],
            )
            self.assertEqual(
                candidate.source_issue_links.count(),
                expected_issue_counts[candidate.comicvine_issue.comicvine_id],
            )

        self.assertFalse(
            ComicVineCollectedEditionCandidate.objects.filter(
                source_collection_volume=self.captain_america_run
            ).exists()
        )

        run_apply(create_missing_catalog=True)

        xmen_catalog_run = ComicRun.objects.get(title="X-Men", start_year="2024")
        uncanny_catalog_run = ComicRun.objects.get(
            title="Uncanny X-Men",
            start_year="2024",
        )
        fantastic_four_catalog_run = ComicRun.objects.get(
            title="Fantastic Four",
            start_year="2025",
        )
        captain_catalog_run = ComicRun.objects.get(
            title="Captain America",
            start_year="2025",
        )

        self.assertEqual(
            list(
                ComicVolume.objects.filter(run=xmen_catalog_run)
                .order_by("volume_number")
                .values_list("volume_number", "title", "issue_count")
            ),
            [
                ("1", "Homecoming", 7),
                ("2", "Hostile Takeover", 8),
                ("3", "The Hellfire Vigil", 5),
            ],
        )
        self.assertEqual(
            list(
                ComicVolume.objects.filter(run=uncanny_catalog_run)
                .order_by("volume_number")
                .values_list("volume_number", "title", "issue_count")
            ),
            [
                ("1", "Red Wave", 8),
                ("2", "The Dark Artery", 8),
                ("3", "Murder Me, Mutina", 5),
            ],
        )

        fantastic_four_volume = ComicVolume.objects.get(
            run=fantastic_four_catalog_run,
            volume_number="1",
        )
        self.assertEqual(fantastic_four_volume.title, "Save Everyone")
        self.assertEqual(fantastic_four_volume.first_issue_number, "")
        self.assertEqual(fantastic_four_volume.last_issue_number, "")
        self.assertIsNone(fantastic_four_volume.issue_count)
        self.assertEqual(fantastic_four_volume.volume_issues.count(), 0)
        self.assertFalse(ComicVolume.objects.filter(run=captain_catalog_run).exists())

        self.assertEqual(MarvelCatalogVolumeSource.objects.count(), 7)
        self.assertEqual(
            ComicVolumeIssue.objects.count(),
            sum(expected_issue_counts.values()),
        )

    def test_reanalysis_replaces_stale_explicit_memberships(self):
        run_analysis()
        run_apply(create_missing_catalog=True)

        candidate = ComicVineCollectedEditionCandidate.objects.get(
            comicvine_issue=self.xmen_volume_one
        )
        catalog_volume = candidate.catalog_volume
        self.assertEqual(catalog_volume.volume_issues.count(), 7)

        self.xmen_volume_one.description = "<p>Collecting X-MEN (2024) 1-6.</p>"
        self.xmen_volume_one.save(update_fields=["description"])

        run_analysis(comicvine_volume_ids=[162694])
        candidate.refresh_from_db()
        self.assertEqual(candidate.source_issue_count, 6)
        self.assertEqual(
            candidate.catalog_status,
            candidate.CATALOG_STATUS_UPDATE_AVAILABLE,
        )

        run_apply(
            comicvine_issue_ids=[1098668],
            create_missing_catalog=True,
            update_existing_catalog=True,
        )
        candidate.refresh_from_db()
        catalog_volume.refresh_from_db()
        self.assertEqual(candidate.catalog_status, candidate.CATALOG_STATUS_APPLIED)
        self.assertEqual(catalog_volume.issue_count, 6)
        self.assertEqual(catalog_volume.volume_issues.count(), 6)

    def test_commands_are_idempotent(self):
        run_analysis()
        run_apply(create_missing_catalog=True)
        first_counts = (
            ComicRun.objects.count(),
            ComicVolume.objects.count(),
            ComicVolumeIssue.objects.count(),
            MarvelCatalogVolumeSource.objects.count(),
        )

        run_analysis()
        run_apply(create_missing_catalog=True)
        second_counts = (
            ComicRun.objects.count(),
            ComicVolume.objects.count(),
            ComicVolumeIssue.objects.count(),
            MarvelCatalogVolumeSource.objects.count(),
        )
        self.assertEqual(second_counts, first_counts)


class UnresolvedCollectionTests(TestCase):
    def test_exact_name_date_fallback_handles_multi_issue_trade_containers(self):
        create_numbered_run(
            comicvine_id=190001,
            name="Fallback Team",
            start_year=2024,
            first_issue=1,
            last_issue=24,
            first_store_date=date(2024, 1, 1),
            issue_id_base=1_900_000,
        )
        collection_volume = create_volume(
            comicvine_id=190002,
            name="Fallback Team",
            start_year=2025,
            count_of_issues=2,
        )
        create_issue(
            volume=collection_volume,
            comicvine_id=190003,
            issue_number=1,
            title="Vol. 1: First Book",
            store_date=date(2024, 3, 1),
        )
        create_issue(
            volume=collection_volume,
            comicvine_id=190004,
            issue_number=2,
            title="Vol. 2: Second Book",
            store_date=date(2024, 9, 1),
        )

        run_analysis()
        candidates = ComicVineCollectedEditionCandidate.objects.filter(
            source_collection_volume=collection_volume
        )
        self.assertEqual(candidates.count(), 2)
        self.assertFalse(
            candidates.exclude(
                analysis_status=(
                    ComicVineCollectedEditionCandidate
                    .ANALYSIS_STATUS_CONFIRMED_COLLECTED_VOLUME
                )
            ).exists()
        )

        run_apply(create_missing_catalog=True)
        catalog_run = ComicRun.objects.get(title="Fallback Team", start_year="2024")
        self.assertEqual(ComicVolume.objects.filter(run=catalog_run).count(), 2)
        self.assertFalse(
            ComicVolumeIssue.objects.filter(volume__run=catalog_run).exists()
        )

    def test_missing_monthly_issue_blocks_entire_collected_volume(self):
        create_numbered_run(
            comicvine_id=200001,
            name="Example Team",
            start_year=2024,
            first_issue=1,
            last_issue=7,
            first_store_date=date(2024, 1, 1),
            issue_id_base=2_000_000,
        )
        collection_volume = create_volume(
            comicvine_id=200002,
            name="Example Team by Example Writer",
            start_year=2025,
            count_of_issues=1,
        )
        trade_issue = create_issue(
            volume=collection_volume,
            comicvine_id=200003,
            issue_number=1,
            title="Vol. 1: Missing Issue",
            store_date=date(2025, 1, 1),
            description="<p>COLLECTING: Example Team (2024) #1-8.</p>",
        )

        run_analysis()
        candidate = ComicVineCollectedEditionCandidate.objects.get(
            comicvine_issue=trade_issue
        )
        self.assertEqual(
            candidate.analysis_status,
            candidate.ANALYSIS_STATUS_UNRESOLVED,
        )
        self.assertEqual(candidate.source_issue_links.count(), 0)

        run_apply(create_missing_catalog=True)
        self.assertEqual(ComicVolume.objects.count(), 0)

    def test_dry_runs_do_not_persist_analysis_or_catalog_rows(self):
        create_numbered_run(
            comicvine_id=210001,
            name="Dry Run Team",
            start_year=2024,
            first_issue=1,
            last_issue=2,
            first_store_date=date(2024, 1, 1),
            issue_id_base=2_100_000,
        )

        run_analysis(dry_run=True)
        self.assertEqual(ComicVineVolumeCandidate.objects.count(), 0)

        run_analysis()
        run_apply(create_missing_catalog=True, dry_run=True)
        self.assertEqual(ComicRun.objects.count(), 0)