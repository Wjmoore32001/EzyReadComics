import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from comics.models import ComicVolume


SEARCH_URL = "https://comicvine.gamespot.com/api/search/"
USER_AGENT = "EzyReadComics current Marvel volume seeder"


@dataclass(frozen=True)
class VolumeSeed:
    name: str
    start_year: str
    category: str
    search_names: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class CandidateScore:
    candidate: dict
    score: int
    reasons: list[str]
    exact_seed_title_match: bool = False
    exact_any_title_match: bool = False
    exact_year_match: bool = False


@dataclass
class SeedResult:
    seeds_checked: int = 0
    api_requests_made: int = 0
    volumes_created: int = 0
    volumes_updated: int = 0
    seeds_skipped_no_candidates: int = 0
    seeds_skipped_low_confidence: int = 0
    seeds_skipped_ambiguous: int = 0
    seeds_skipped_api_errors: int = 0


CURRENT_MARVEL_VOLUME_SEEDS = [
    # Ongoing series — Active
    VolumeSeed("The Amazing Spider-Man", "2025", "ongoing_active", ("Amazing Spider-Man",)),
    VolumeSeed("Black Cat", "2025", "ongoing_active"),
    VolumeSeed("Captain America", "2025", "ongoing_active"),
    VolumeSeed("Daredevil", "2026", "ongoing_active"),
    VolumeSeed("Doctor Strange", "2025", "ongoing_active"),
    VolumeSeed("Fantastic Four", "2025", "ongoing_active"),
    VolumeSeed("Generation X-23", "2026", "ongoing_active"),
    VolumeSeed("The Infernal Hulk", "2025", "ongoing_active", ("Infernal Hulk",)),
    VolumeSeed("Inglorious X-Force", "2026", "ongoing_active"),
    VolumeSeed("Iron Man", "2026", "ongoing_active"),
    VolumeSeed("Marc Spector: Moon Knight", "2026", "ongoing_active"),
    VolumeSeed("The Mortal Thor", "2025", "ongoing_active", ("Mortal Thor",)),
    VolumeSeed("The Punisher", "2026", "ongoing_active", ("Punisher",)),
    VolumeSeed("Sorcerer Supreme", "2025", "ongoing_active"),
    VolumeSeed("The Uncanny X-Men", "2024", "ongoing_active", ("Uncanny X-Men",)),
    VolumeSeed("Venom", "2025", "ongoing_active"),
    VolumeSeed("Wade Wilson: Deadpool", "2026", "ongoing_active"),
    VolumeSeed("Wolverine", "2024", "ongoing_active"),
    VolumeSeed("X-Men", "2024", "ongoing_active"),
    VolumeSeed("X-Men United", "2026", "ongoing_active"),

    # Ongoing series — Upcoming
    VolumeSeed("Miles Morales: Spider-Man", "2026", "ongoing_upcoming"),

    # Limited series — Active
    VolumeSeed(
        "The Amazing Spider-Man: Spider-Versity",
        "2026",
        "limited_active",
        ("Amazing Spider-Man: Spider-Versity", "Spider-Versity"),
    ),
    VolumeSeed("Avengers: Armageddon", "2026", "limited_active"),
    VolumeSeed("Captain Marvel: Dark Past", "2026", "limited_active"),
    VolumeSeed("Moonstar", "2026", "limited_active"),
    VolumeSeed(
        "The Spectacular Spider-Man: Brand New Day",
        "2026",
        "limited_active",
        ("Spectacular Spider-Man: Brand New Day", "Brand New Day"),
    ),
    VolumeSeed("Spider-Man: Long Way Home", "2026", "limited_active"),
    VolumeSeed("Wonder Man", "2026", "limited_active"),
    VolumeSeed("X-Men '97: Season 2", "2026", "limited_active", ("X-Men 97: Season 2", "X-Men '97")),
    VolumeSeed("X-Men: Outback", "2026", "limited_active"),

    # Limited series — Upcoming
    VolumeSeed("Punisher Vs. Spider-Man", "2026", "limited_upcoming", ("Punisher vs. Spider-Man",)),
    VolumeSeed("Queen in Black", "2026", "limited_upcoming"),
    VolumeSeed("Queen in Black: Defenders of Light and Dark", "2026", "limited_upcoming"),
    VolumeSeed("Queen in Black: Venom Unchained", "2026", "limited_upcoming"),
    VolumeSeed("Spider-Man/Hulk: Fire & Brimstone", "2026", "limited_upcoming"),
]


class Command(BaseCommand):
    help = "Temporarily seed selected current Marvel volumes from Comic Vine for algorithm testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be changed without saving anything.",
        )

        parser.add_argument(
            "--request-delay",
            type=float,
            default=0.25,
            help="Seconds to pause after each Comic Vine request. Defaults to 0.25.",
        )

        parser.add_argument(
            "--show-candidates",
            action="store_true",
            help="Print scored Comic Vine candidates for skipped seeds.",
        )

        parser.add_argument(
            "--allow-non-marvel-publisher",
            action="store_true",
            help="Allow matches whose Comic Vine publisher is not Marvel. Defaults to false.",
        )

        parser.add_argument(
            "--min-score",
            type=int,
            default=75,
            help="Minimum score required to auto-select a candidate. Defaults to 75.",
        )

        parser.add_argument(
            "--score-gap",
            type=int,
            default=0,
            help="Minimum score gap between best and second-best candidate. Defaults to 0.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        request_delay = options["request_delay"]
        dry_run = options["dry_run"]
        show_candidates = options["show_candidates"]
        allow_non_marvel_publisher = options["allow_non_marvel_publisher"]
        min_score = options["min_score"]
        score_gap = options["score_gap"]

        if request_delay < 0:
            raise CommandError("request-delay cannot be negative.")

        if min_score < 0:
            raise CommandError("min-score cannot be negative.")

        if score_gap < 0:
            raise CommandError("score-gap cannot be negative.")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled. Nothing will be saved."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Current Marvel volume seeder"))
        self.stdout.write("This is a temporary/manual sandbox command.")
        self.stdout.write("It searches Comic Vine for a curated list of current Marvel publication titles.")
        self.stdout.write("It only creates or updates ComicVolume rows. It does not create issues.")
        self.stdout.write("Title matching keeps leading words like 'The'.")
        self.stdout.write("Colon titles do not automatically search only the base title.")
        self.stdout.write("Temporary Comic Vine 500/502/503/504 errors are retried and then skipped per seed.")
        self.stdout.write(f"Seeds in manifest: {len(CURRENT_MARVEL_VOLUME_SEEDS)}")
        self.stdout.write(f"Minimum auto-select score: {min_score}")
        self.stdout.write(f"Minimum score gap: {score_gap}")

        result = seed_current_marvel_volumes(
            command=self,
            api_key=api_key,
            request_delay=request_delay,
            dry_run=dry_run,
            show_candidates=show_candidates,
            allow_non_marvel_publisher=allow_non_marvel_publisher,
            min_score=min_score,
            score_gap=score_gap,
        )

        print_summary(self, result)

        if dry_run:
            self.stdout.write("")
            self.stdout.write("No database changes were saved because this was a dry run.")


def seed_current_marvel_volumes(
    command,
    api_key,
    request_delay,
    dry_run,
    show_candidates,
    allow_non_marvel_publisher,
    min_score,
    score_gap,
):
    result = SeedResult()

    for seed in CURRENT_MARVEL_VOLUME_SEEDS:
        result.seeds_checked += 1

        try:
            candidates, request_count = fetch_candidates_for_seed(
                api_key=api_key,
                seed=seed,
                request_delay=request_delay,
            )
        except CommandError as error:
            command.stdout.write("")
            command.stdout.write(f"Seed: {seed.name} ({seed.start_year}) [{seed.category}]")
            command.stdout.write(
                command.style.WARNING(
                    f"Comic Vine request failed for this seed. Skipping and continuing. Error: {error}"
                )
            )
            result.seeds_skipped_api_errors += 1
            continue

        result.api_requests_made += request_count

        scored_candidates = score_candidates(
            candidates=candidates,
            seed=seed,
            allow_non_marvel_publisher=allow_non_marvel_publisher,
        )

        command.stdout.write("")
        command.stdout.write(f"Seed: {seed.name} ({seed.start_year}) [{seed.category}]")

        if not scored_candidates:
            command.stdout.write(command.style.WARNING("No Comic Vine volume candidates returned. Skipping."))
            result.seeds_skipped_no_candidates += 1
            continue

        best_score = scored_candidates[0]
        second_score = scored_candidates[1] if len(scored_candidates) > 1 else None

        if best_score.score < min_score:
            command.stdout.write(
                command.style.WARNING(
                    f"Best candidate score was too low ({best_score.score}). Skipping."
                )
            )
            print_best_candidate(command, best_score)

            if show_candidates:
                print_scored_candidates(command, scored_candidates)

            result.seeds_skipped_low_confidence += 1
            continue

        if score_gap > 0 and second_score and best_score.score - second_score.score < score_gap:
            command.stdout.write(
                command.style.WARNING(
                    f"Best candidate was too close to second-best candidate "
                    f"({best_score.score} vs {second_score.score}). Skipping."
                )
            )

            if show_candidates:
                print_scored_candidates(command, scored_candidates)

            result.seeds_skipped_ambiguous += 1
            continue

        match = best_score.candidate
        volume_id = to_optional_int(match.get("id"))

        if not volume_id:
            command.stdout.write(command.style.WARNING("Selected candidate did not include a Comic Vine volume ID. Skipping."))
            result.seeds_skipped_low_confidence += 1
            continue

        existing_volume = ComicVolume.objects.filter(comicvine_id=volume_id).first()

        print_selected_match(command, best_score)

        if not dry_run:
            created = save_volume_from_candidate(match)

            if created:
                result.volumes_created += 1
            else:
                result.volumes_updated += 1
        else:
            if existing_volume:
                result.volumes_updated += 1
            else:
                result.volumes_created += 1

    return result


def fetch_candidates_for_seed(api_key, seed, request_delay):
    candidates_by_id = {}
    request_count = 0

    for search_name in get_search_names(seed):
        data = fetch_volume_search_results(
            api_key=api_key,
            search_name=search_name,
        )
        request_count += 1

        for candidate in data.get("results") or []:
            candidate_id = to_optional_int(candidate.get("id"))

            if candidate_id:
                candidates_by_id[candidate_id] = candidate

        if request_delay > 0:
            time.sleep(request_delay)

    return list(candidates_by_id.values()), request_count


def get_search_names(seed):
    names = [seed.name]

    for search_name in seed.search_names:
        if search_name not in names:
            names.append(search_name)

    return names


def fetch_volume_search_results(api_key, search_name):
    params = {
        "api_key": api_key,
        "format": "json",
        "resources": "volume",
        "limit": 100,
        "offset": 0,
        "query": search_name,
        "field_list": ",".join(
            [
                "id",
                "aliases",
                "api_detail_url",
                "count_of_issues",
                "date_added",
                "date_last_updated",
                "deck",
                "description",
                "first_issue",
                "image",
                "last_issue",
                "name",
                "publisher",
                "site_detail_url",
                "start_year",
            ]
        ),
    }

    return fetch_comicvine_json(SEARCH_URL, params)


def score_candidates(candidates, seed, allow_non_marvel_publisher):
    scored_candidates = []

    for candidate in candidates:
        score = score_candidate(
            candidate=candidate,
            seed=seed,
            allow_non_marvel_publisher=allow_non_marvel_publisher,
        )
        scored_candidates.append(score)

    scored_candidates.sort(
        key=lambda scored: (
            scored.score,
            scored.exact_seed_title_match,
            scored.exact_any_title_match,
            scored.exact_year_match,
            to_int(scored.candidate.get("start_year")),
            to_int(scored.candidate.get("count_of_issues")),
            -to_int(scored.candidate.get("id")),
        ),
        reverse=True,
    )

    return scored_candidates


def score_candidate(candidate, seed, allow_non_marvel_publisher):
    score = 0
    reasons = []

    candidate_name = candidate.get("name") or ""
    candidate_start_year = str(candidate.get("start_year") or "")
    publisher_name = get_publisher_name(candidate)

    normalized_candidate_name = normalize_title(candidate_name)
    normalized_seed_name = normalize_title(seed.name)
    normalized_search_names = {
        normalize_title(name)
        for name in seed.search_names
    }
    normalized_all_seed_names = {normalized_seed_name, *normalized_search_names}

    normalized_aliases = get_normalized_aliases(candidate)

    exact_seed_title_match = normalized_candidate_name == normalized_seed_name
    exact_any_title_match = normalized_candidate_name in normalized_all_seed_names

    if exact_seed_title_match:
        score += 70
        reasons.append("exact seed title match")
    elif exact_any_title_match:
        score += 55
        reasons.append("exact alternate title match")
    elif normalized_aliases.intersection(normalized_all_seed_names):
        score += 40
        reasons.append("alias title match")
    elif title_is_close_enough(normalized_candidate_name, normalized_all_seed_names):
        score += 20
        reasons.append("close title match")

    start_year_score = get_start_year_score(candidate_start_year, seed.start_year)
    exact_year_match = candidate_start_year == seed.start_year

    if start_year_score:
        score += start_year_score
        reasons.append(f"start year match score {start_year_score}")

    if publisher_name:
        if "marvel" in publisher_name.lower():
            score += 25
            reasons.append("publisher contains Marvel")
        elif allow_non_marvel_publisher:
            reasons.append(f"non-Marvel publisher allowed: {publisher_name}")
        else:
            score -= 40
            reasons.append(f"publisher does not look like Marvel: {publisher_name}")
    else:
        score += 5
        reasons.append("publisher missing")

    count_of_issues = to_optional_int(candidate.get("count_of_issues"))

    if count_of_issues:
        score += 5
        reasons.append("has issue count")

    if candidate.get("site_detail_url"):
        score += 5
        reasons.append("has Comic Vine URL")

    return CandidateScore(
        candidate=candidate,
        score=score,
        reasons=reasons,
        exact_seed_title_match=exact_seed_title_match,
        exact_any_title_match=exact_any_title_match,
        exact_year_match=exact_year_match,
    )


def title_is_close_enough(normalized_candidate_name, normalized_seed_names):
    for normalized_seed_name in normalized_seed_names:
        if not normalized_seed_name:
            continue

        if normalized_candidate_name == normalized_seed_name:
            return True

        if len(normalized_seed_name) >= 12 and normalized_seed_name in normalized_candidate_name:
            return True

        if len(normalized_candidate_name) >= 12 and normalized_candidate_name in normalized_seed_name:
            return True

    return False


def get_start_year_score(candidate_start_year, seed_start_year):
    candidate_year = to_optional_int(candidate_start_year)
    seed_year = to_optional_int(seed_start_year)

    if not candidate_year or not seed_year:
        return 0

    year_difference = abs(candidate_year - seed_year)

    if year_difference == 0:
        return 50

    if year_difference == 1:
        return 25

    if year_difference == 2:
        return 10

    return 0


def save_volume_from_candidate(candidate):
    volume_id = to_optional_int(candidate.get("id"))

    volume, created = ComicVolume.objects.get_or_create(
        comicvine_id=volume_id,
        defaults={
            "name": candidate.get("name") or "",
        },
    )

    volume_data = build_volume_data(
        local_volume=volume,
        candidate=candidate,
    )

    volume.name = volume_data["name"]
    volume.publisher = volume_data["publisher"]
    volume.publisher_comicvine_id = volume_data["publisher_comicvine_id"]
    volume.publisher_api_detail_url = volume_data["publisher_api_detail_url"]

    volume.start_year = volume_data["start_year"]
    volume.count_of_issues = volume_data["count_of_issues"]

    volume.date_added = volume_data["date_added"]
    volume.date_last_updated = volume_data["date_last_updated"]

    volume.comicvine_url = volume_data["comicvine_url"]
    volume.api_detail_url = volume_data["api_detail_url"]

    volume.aliases = volume_data["aliases"]
    volume.deck = volume_data["deck"]
    volume.description = volume_data["description"]

    volume.comicvine_image_icon_url = volume_data["comicvine_image_icon_url"]
    volume.comicvine_image_medium_url = volume_data["comicvine_image_medium_url"]
    volume.comicvine_image_screen_url = volume_data["comicvine_image_screen_url"]
    volume.comicvine_image_screen_large_url = volume_data["comicvine_image_screen_large_url"]
    volume.comicvine_image_small_url = volume_data["comicvine_image_small_url"]
    volume.comicvine_image_super_url = volume_data["comicvine_image_super_url"]
    volume.comicvine_image_thumb_url = volume_data["comicvine_image_thumb_url"]
    volume.comicvine_image_tiny_url = volume_data["comicvine_image_tiny_url"]
    volume.comicvine_image_original_url = volume_data["comicvine_image_original_url"]
    volume.comicvine_image_tags = volume_data["comicvine_image_tags"]

    volume.display_image_url = volume_data["display_image_url"]
    volume.display_image_source = volume_data["display_image_source"]

    volume.first_issue_comicvine_id = volume_data["first_issue_comicvine_id"]
    volume.first_issue_number = volume_data["first_issue_number"]
    volume.first_issue_name = volume_data["first_issue_name"]
    volume.first_issue_api_url = volume_data["first_issue_api_url"]

    volume.last_issue_comicvine_id = volume_data["last_issue_comicvine_id"]
    volume.last_issue_number = volume_data["last_issue_number"]
    volume.last_issue_name = volume_data["last_issue_name"]
    volume.last_issue_api_url = volume_data["last_issue_api_url"]

    volume.save(
        update_fields=[
            "name",
            "publisher",
            "publisher_comicvine_id",
            "publisher_api_detail_url",
            "start_year",
            "count_of_issues",
            "date_added",
            "date_last_updated",
            "comicvine_url",
            "api_detail_url",
            "aliases",
            "deck",
            "description",
            "comicvine_image_icon_url",
            "comicvine_image_medium_url",
            "comicvine_image_screen_url",
            "comicvine_image_screen_large_url",
            "comicvine_image_small_url",
            "comicvine_image_super_url",
            "comicvine_image_thumb_url",
            "comicvine_image_tiny_url",
            "comicvine_image_original_url",
            "comicvine_image_tags",
            "display_image_url",
            "display_image_source",
            "first_issue_comicvine_id",
            "first_issue_number",
            "first_issue_name",
            "first_issue_api_url",
            "last_issue_comicvine_id",
            "last_issue_number",
            "last_issue_name",
            "last_issue_api_url",
        ]
    )

    return created


def build_volume_data(local_volume, candidate):
    publisher = candidate.get("publisher") or {}
    image = candidate.get("image") or {}
    first_issue = candidate.get("first_issue") or {}
    last_issue = candidate.get("last_issue") or {}

    display_image_url = local_volume.display_image_url
    display_image_source = local_volume.display_image_source

    preferred_image_url = get_preferred_image_url(image)

    if (
        display_image_source != ComicVolume.IMAGE_SOURCE_MANUAL
        and not display_image_url
        and preferred_image_url
    ):
        display_image_url = preferred_image_url
        display_image_source = ComicVolume.IMAGE_SOURCE_COMICVINE_VOLUME

    count_of_issues = to_optional_int(candidate.get("count_of_issues"))

    if count_of_issues is None:
        count_of_issues = local_volume.count_of_issues

    return {
        "name": candidate.get("name") or local_volume.name,
        "publisher": publisher.get("name") or local_volume.publisher,
        "publisher_comicvine_id": to_optional_int(publisher.get("id")) or local_volume.publisher_comicvine_id,
        "publisher_api_detail_url": publisher.get("api_detail_url") or local_volume.publisher_api_detail_url,
        "start_year": str(candidate.get("start_year") or local_volume.start_year or ""),
        "count_of_issues": count_of_issues,
        "date_added": parse_comicvine_datetime(candidate.get("date_added")) or local_volume.date_added,
        "date_last_updated": parse_comicvine_datetime(candidate.get("date_last_updated")) or local_volume.date_last_updated,
        "comicvine_url": candidate.get("site_detail_url") or local_volume.comicvine_url,
        "api_detail_url": candidate.get("api_detail_url") or local_volume.api_detail_url,
        "aliases": candidate.get("aliases") or "",
        "deck": candidate.get("deck") or "",
        "description": candidate.get("description") or "",
        "comicvine_image_icon_url": image.get("icon_url") or "",
        "comicvine_image_medium_url": image.get("medium_url") or "",
        "comicvine_image_screen_url": image.get("screen_url") or "",
        "comicvine_image_screen_large_url": image.get("screen_large_url") or "",
        "comicvine_image_small_url": image.get("small_url") or "",
        "comicvine_image_super_url": image.get("super_url") or "",
        "comicvine_image_thumb_url": image.get("thumb_url") or "",
        "comicvine_image_tiny_url": image.get("tiny_url") or "",
        "comicvine_image_original_url": image.get("original_url") or "",
        "comicvine_image_tags": image.get("image_tags") or "",
        "display_image_url": display_image_url,
        "display_image_source": display_image_source,
        "first_issue_comicvine_id": to_optional_int(first_issue.get("id")),
        "first_issue_number": first_issue.get("issue_number") or "",
        "first_issue_name": first_issue.get("name") or "",
        "first_issue_api_url": first_issue.get("api_detail_url") or "",
        "last_issue_comicvine_id": to_optional_int(last_issue.get("id")),
        "last_issue_number": last_issue.get("issue_number") or "",
        "last_issue_name": last_issue.get("name") or "",
        "last_issue_api_url": last_issue.get("api_detail_url") or "",
    }


def normalize_title(value):
    normalized = value.lower().strip()
    normalized = normalized.replace("&", "and")
    normalized = normalized.replace("’", "'")
    normalized = normalized.replace("‘", "'")
    normalized = normalized.replace("–", "-")
    normalized = normalized.replace("—", "-")
    normalized = normalized.replace("vs.", "vs")
    normalized = normalized.replace("versus", "vs")
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)

    return normalized


def get_normalized_aliases(candidate):
    aliases = candidate.get("aliases") or ""
    normalized_aliases = set()

    for alias in aliases.splitlines():
        normalized_alias = normalize_title(alias)

        if normalized_alias:
            normalized_aliases.add(normalized_alias)

    return normalized_aliases


def get_publisher_name(candidate):
    publisher = candidate.get("publisher") or {}

    return publisher.get("name") or ""


def get_preferred_image_url(image):
    return (
        image.get("small_url")
        or image.get("medium_url")
        or image.get("screen_url")
        or image.get("original_url")
        or ""
    )


def fetch_comicvine_json(url, params):
    headers = {
        "User-Agent": USER_AGENT,
    }

    max_attempts = 3
    retry_statuses = {429, 500, 502, 503, 504}

    for attempt_number in range(1, max_attempts + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as error:
            if attempt_number == max_attempts:
                raise CommandError(
                    f"Comic Vine request failed after {max_attempts} attempts: {error}"
                ) from error

            time.sleep(attempt_number * 2)
            continue

        if response.status_code == 200:
            data = response.json()

            status_code = data.get("status_code")
            error_message = data.get("error")

            if str(status_code) != "1":
                raise CommandError(
                    f"Comic Vine API returned status_code={status_code}: {error_message}"
                )

            return data

        if response.status_code == 420:
            raise CommandError(
                "Comic Vine returned HTTP 420. This is probably a temporary rate or velocity limit. "
                "Wait before running the command again."
            )

        if response.status_code in retry_statuses:
            if attempt_number == max_attempts:
                raise CommandError(
                    f"Comic Vine request failed with HTTP status {response.status_code} "
                    f"after {max_attempts} attempts."
                )

            time.sleep(attempt_number * 2)
            continue

        raise CommandError(
            f"Comic Vine request failed with HTTP status {response.status_code}."
        )

    raise CommandError("Comic Vine request failed unexpectedly.")


def parse_comicvine_datetime(value):
    if not value:
        return None

    try:
        parsed_datetime = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    if timezone.is_naive(parsed_datetime):
        return timezone.make_aware(parsed_datetime, timezone.get_current_timezone())

    return parsed_datetime


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def print_selected_match(command, scored_candidate):
    candidate = scored_candidate.candidate
    publisher_name = get_publisher_name(candidate) or "Unknown publisher"

    command.stdout.write(
        command.style.SUCCESS(
            f"Selected Comic Vine volume: {candidate.get('name')} "
            f"({candidate.get('start_year')}) "
            f"[ID {candidate.get('id')}] "
            f"[{publisher_name}] "
            f"score={scored_candidate.score}"
        )
    )

    command.stdout.write(f"Reasons: {', '.join(scored_candidate.reasons)}")


def print_best_candidate(command, scored_candidate):
    candidate = scored_candidate.candidate
    publisher_name = get_publisher_name(candidate) or "Unknown publisher"

    command.stdout.write(
        f"Best candidate: {candidate.get('name') or ''} "
        f"({candidate.get('start_year') or ''}) "
        f"[ID {candidate.get('id') or ''}] "
        f"[{publisher_name}] "
        f"score={scored_candidate.score}"
    )

    command.stdout.write(f"Reasons: {', '.join(scored_candidate.reasons)}")


def print_scored_candidates(command, scored_candidates):
    if not scored_candidates:
        command.stdout.write("No candidates returned.")
        return

    command.stdout.write("Top candidates:")

    for scored_candidate in scored_candidates[:10]:
        candidate = scored_candidate.candidate
        publisher_name = get_publisher_name(candidate) or "Unknown publisher"

        command.stdout.write(
            f"- {candidate.get('name') or ''} "
            f"({candidate.get('start_year') or ''}) "
            f"[ID {candidate.get('id') or ''}] "
            f"[{publisher_name}] "
            f"score={scored_candidate.score} "
            f"reasons={'; '.join(scored_candidate.reasons)}"
        )


def print_summary(command, result):
    command.stdout.write("")
    command.stdout.write(command.style.SUCCESS("Current Marvel volume seed summary:"))
    command.stdout.write(f"Seeds checked: {result.seeds_checked}")
    command.stdout.write(f"Volumes created: {result.volumes_created}")
    command.stdout.write(f"Volumes updated: {result.volumes_updated}")
    command.stdout.write(f"Seeds skipped with no candidates: {result.seeds_skipped_no_candidates}")
    command.stdout.write(f"Seeds skipped as low confidence: {result.seeds_skipped_low_confidence}")
    command.stdout.write(f"Seeds skipped as ambiguous: {result.seeds_skipped_ambiguous}")
    command.stdout.write(f"Seeds skipped because of Comic Vine/API errors: {result.seeds_skipped_api_errors}")
    command.stdout.write(f"Comic Vine API requests made: {result.api_requests_made}")