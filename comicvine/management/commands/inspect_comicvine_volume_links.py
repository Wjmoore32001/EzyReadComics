import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from comicvine.api.client import (
    ComicVineAPIError,
    create_comicvine_session,
    fetch_issue_detail,
    fetch_issues_page,
    fetch_volume_detail,
    get_comicvine_api_key,
)


USER_AGENT = "EzyReadComics/inspect-comicvine-volume-links"

RELATIONSHIP_KEYWORDS = [
    "volume",
    "issue",
    "collect",
    "collected",
    "collection",
    "trade",
    "paperback",
    "tpb",
    "hardcover",
    "omnibus",
    "edition",
    "series",
    "parent",
    "source",
    "first",
    "last",
]


class Command(BaseCommand):
    help = (
        "Inspect raw Comic Vine volume data to see whether two Comic Vine volumes "
        "have a direct relationship, such as a collected edition pointing to a run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--volume-id",
            type=int,
            required=True,
            help="Primary Comic Vine volume ID to inspect. Use the plain ID, not 4050-ID.",
        )
        parser.add_argument(
            "--compare-volume-id",
            type=int,
            default=None,
            help="Optional second Comic Vine volume ID to compare against.",
        )
        parser.add_argument(
            "--max-issue-pages",
            type=int,
            default=3,
            help="Maximum issue-list pages to fetch per volume. Each page can contain up to 100 issues.",
        )
        parser.add_argument(
            "--issue-detail-limit",
            type=int,
            default=1,
            help=(
                "Number of issue detail records to fetch per volume after fetching the issue list. "
                "Use 0 to skip issue detail calls."
            ),
        )
        parser.add_argument(
            "--save-json",
            type=str,
            default="",
            help=(
                "Optional path to save the raw inspection JSON. "
                "Example: tmp/comicvine_volume_inspection.json"
            ),
        )

    def handle(self, *args, **options):
        volume_id = options["volume_id"]
        compare_volume_id = options["compare_volume_id"]
        max_issue_pages = options["max_issue_pages"]
        issue_detail_limit = options["issue_detail_limit"]
        save_json_path = options["save_json"].strip()

        if volume_id < 1:
            raise CommandError("--volume-id must be greater than 0.")

        if compare_volume_id is not None and compare_volume_id < 1:
            raise CommandError("--compare-volume-id must be greater than 0.")

        if max_issue_pages < 1:
            raise CommandError("--max-issue-pages must be at least 1.")

        if issue_detail_limit < 0:
            raise CommandError("--issue-detail-limit cannot be negative.")

        try:
            api_key = get_comicvine_api_key()
            session = create_comicvine_session(USER_AGENT)

            inspected = []

            inspected.append(
                self.inspect_volume(
                    session=session,
                    api_key=api_key,
                    volume_id=volume_id,
                    max_issue_pages=max_issue_pages,
                    issue_detail_limit=issue_detail_limit,
                )
            )

            if compare_volume_id is not None:
                inspected.append(
                    self.inspect_volume(
                        session=session,
                        api_key=api_key,
                        volume_id=compare_volume_id,
                        max_issue_pages=max_issue_pages,
                        issue_detail_limit=issue_detail_limit,
                    )
                )

        except ComicVineAPIError as error:
            raise CommandError(str(error)) from error

        self.print_inspection(inspected)

        if len(inspected) == 2:
            self.print_comparison(inspected[0], inspected[1])

        if save_json_path:
            self.save_json(save_json_path, inspected)

    def inspect_volume(
        self,
        *,
        session,
        api_key,
        volume_id,
        max_issue_pages,
        issue_detail_limit,
    ):
        volume_response = fetch_volume_detail(
            session,
            api_key,
            volume_id=volume_id,
            fields=[],
        )
        volume_data = volume_response.get("results") or {}

        issue_pages = []
        issues = []

        for page_number in range(max_issue_pages):
            offset = page_number * 100

            issue_page_response = fetch_issues_page(
                session,
                api_key,
                filter_value=f"volume:{volume_id}",
                fields=[],
                offset=offset,
                limit=100,
                sort="store_date:asc",
            )

            page_issues = issue_page_response.get("results") or []

            issue_pages.append(
                {
                    "offset": offset,
                    "number_of_total_results": issue_page_response.get(
                        "number_of_total_results"
                    ),
                    "number_of_page_results": issue_page_response.get(
                        "number_of_page_results"
                    ),
                    "results": page_issues,
                }
            )

            issues.extend(page_issues)

            if not page_issues:
                break

            total_results = issue_page_response.get("number_of_total_results") or 0

            if len(issues) >= total_results:
                break

        issue_details = []

        for issue in issues[:issue_detail_limit]:
            issue_id = issue.get("id")

            if not issue_id:
                continue

            issue_detail_response = fetch_issue_detail(
                session,
                api_key,
                issue_id=issue_id,
                fields=[],
            )

            issue_details.append(
                {
                    "issue_id": issue_id,
                    "detail": issue_detail_response.get("results") or {},
                }
            )

        return {
            "volume_id": volume_id,
            "volume_response": volume_response,
            "volume": volume_data,
            "issue_pages": issue_pages,
            "issues": issues,
            "issue_details": issue_details,
        }

    def print_inspection(self, inspected):
        for item in inspected:
            volume = item["volume"]
            issues = item["issues"]

            self.print_header(f"Comic Vine volume {item['volume_id']}")

            self.print_volume_summary(volume)
            self.print_top_level_keys("Volume raw top-level keys", volume)
            self.print_relationship_like_paths("Volume relationship-looking fields", volume)

            first_issue = volume.get("first_issue")
            last_issue = volume.get("last_issue")

            self.print_subheader("First issue field")
            self.print_json_preview(first_issue)

            self.print_subheader("Last issue field")
            self.print_json_preview(last_issue)

            self.print_subheader("Issues returned by Comic Vine issue filter")
            self.stdout.write(f"Total local fetched from issue pages: {len(issues)}")

            for page in item["issue_pages"]:
                self.stdout.write(
                    f"  offset={page['offset']} "
                    f"page_results={page['number_of_page_results']} "
                    f"total_results={page['number_of_total_results']}"
                )

            self.print_issue_rows(issues)

            if item["issue_details"]:
                self.print_subheader("Fetched issue detail records")
                for detail_item in item["issue_details"]:
                    issue_detail = detail_item["detail"]
                    self.stdout.write("")
                    self.stdout.write(f"Issue detail for issue ID {detail_item['issue_id']}")
                    self.print_issue_summary(issue_detail, indent="  ")
                    self.print_top_level_keys(
                        "  Issue detail raw top-level keys",
                        issue_detail,
                    )
                    self.print_relationship_like_paths(
                        "  Issue detail relationship-looking fields",
                        issue_detail,
                        indent="  ",
                    )
            else:
                self.print_subheader("Fetched issue detail records")
                self.stdout.write("Skipped. --issue-detail-limit is 0 or no issues were found.")

    def print_comparison(self, first, second):
        first_id = first["volume_id"]
        second_id = second["volume_id"]

        self.print_header("Cross-volume comparison")

        self.print_key_comparison(first, second)

        self.print_subheader(f"Searching volume {first_id} raw data for volume {second_id}")
        self.print_matches(
            find_value_matches(
                first,
                needles=build_volume_needles(second_id),
            )
        )

        self.print_subheader(f"Searching volume {second_id} raw data for volume {first_id}")
        self.print_matches(
            find_value_matches(
                second,
                needles=build_volume_needles(first_id),
            )
        )

        self.print_subheader(f"Searching volume {first_id} raw data for collected/run words")
        self.print_matches(
            find_value_matches(
                first,
                needles=[
                    "collects",
                    "collecting",
                    "collected",
                    "trade paperback",
                    "paperback",
                    "hardcover",
                    "omnibus",
                    "volume 1",
                    "vol. 1",
                ],
                case_sensitive=False,
            )
        )

        self.print_subheader(f"Searching volume {second_id} raw data for collected/run words")
        self.print_matches(
            find_value_matches(
                second,
                needles=[
                    "collects",
                    "collecting",
                    "collected",
                    "trade paperback",
                    "paperback",
                    "hardcover",
                    "omnibus",
                    "volume 1",
                    "vol. 1",
                ],
                case_sensitive=False,
            )
        )

    def print_volume_summary(self, volume):
        self.print_subheader("Volume summary")

        publisher = volume.get("publisher")

        if isinstance(publisher, dict):
            publisher_name = publisher.get("name")
            publisher_id = publisher.get("id")
        else:
            publisher_name = publisher
            publisher_id = None

        rows = [
            ("id", volume.get("id")),
            ("name", volume.get("name")),
            ("start_year", volume.get("start_year")),
            ("count_of_issues", volume.get("count_of_issues")),
            ("publisher", publisher_name),
            ("publisher_id", publisher_id),
            ("site_detail_url", volume.get("site_detail_url")),
            ("api_detail_url", volume.get("api_detail_url")),
            ("date_added", volume.get("date_added")),
            ("date_last_updated", volume.get("date_last_updated")),
        ]

        for label, value in rows:
            self.stdout.write(f"{label}: {format_value(value)}")

        self.stdout.write("")
        self.stdout.write("deck:")
        self.stdout.write(format_long_text(volume.get("deck")))

        self.stdout.write("")
        self.stdout.write("description:")
        self.stdout.write(format_long_text(strip_html(volume.get("description"))))

    def print_issue_rows(self, issues):
        if not issues:
            self.stdout.write("No issues returned.")
            return

        self.stdout.write("")
        self.stdout.write("Issue rows:")

        for issue in issues:
            volume = issue.get("volume")

            if isinstance(volume, dict):
                volume_label = (
                    f"{volume.get('name')} "
                    f"(id={volume.get('id')}, api={volume.get('api_detail_url')})"
                )
            else:
                volume_label = format_value(volume)

            self.stdout.write(
                "  "
                f"id={format_value(issue.get('id'))} | "
                f"#{format_value(issue.get('issue_number'))} | "
                f"name={format_value(issue.get('name'))} | "
                f"store_date={format_value(issue.get('store_date'))} | "
                f"cover_date={format_value(issue.get('cover_date'))} | "
                f"volume={volume_label}"
            )

    def print_issue_summary(self, issue, indent=""):
        volume = issue.get("volume")

        if isinstance(volume, dict):
            volume_label = (
                f"{volume.get('name')} "
                f"(id={volume.get('id')}, api={volume.get('api_detail_url')})"
            )
        else:
            volume_label = format_value(volume)

        rows = [
            ("id", issue.get("id")),
            ("issue_number", issue.get("issue_number")),
            ("name", issue.get("name")),
            ("store_date", issue.get("store_date")),
            ("cover_date", issue.get("cover_date")),
            ("site_detail_url", issue.get("site_detail_url")),
            ("api_detail_url", issue.get("api_detail_url")),
            ("volume", volume_label),
        ]

        for label, value in rows:
            self.stdout.write(f"{indent}{label}: {format_value(value)}")

    def print_key_comparison(self, first, second):
        first_keys = set((first["volume"] or {}).keys())
        second_keys = set((second["volume"] or {}).keys())

        self.print_subheader("Volume top-level key comparison")

        only_first = sorted(first_keys - second_keys)
        only_second = sorted(second_keys - first_keys)
        shared = sorted(first_keys & second_keys)

        self.stdout.write(f"Shared keys: {', '.join(shared) if shared else 'None'}")
        self.stdout.write(
            f"Only volume {first['volume_id']}: "
            f"{', '.join(only_first) if only_first else 'None'}"
        )
        self.stdout.write(
            f"Only volume {second['volume_id']}: "
            f"{', '.join(only_second) if only_second else 'None'}"
        )

    def print_top_level_keys(self, title, value):
        self.print_subheader(title)

        if not isinstance(value, dict):
            self.stdout.write("Not a dictionary.")
            return

        keys = sorted(value.keys())

        if not keys:
            self.stdout.write("No keys.")
            return

        for key in keys:
            field_value = value.get(key)
            self.stdout.write(f"  {key}: {type(field_value).__name__}")

    def print_relationship_like_paths(self, title, value, indent=""):
        self.print_subheader(title)

        matches = find_relationship_like_paths(value)

        if not matches:
            self.stdout.write(f"{indent}No relationship-looking paths found.")
            return

        for path, matched_key, field_value in matches:
            self.stdout.write(
                f"{indent}{path} "
                f"(matched key: {matched_key}) = {preview_value(field_value)}"
            )

    def print_json_preview(self, value):
        if value is None or value == "":
            self.stdout.write("None")
            return

        self.stdout.write(
            json.dumps(
                value,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )

    def print_matches(self, matches):
        if not matches:
            self.stdout.write("No matches found.")
            return

        for path, field_value, needle in matches:
            self.stdout.write(
                f"{path} matched {needle!r}: {preview_value(field_value)}"
            )

    def print_header(self, title):
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write(title)
        self.stdout.write("=" * 80)

    def print_subheader(self, title):
        self.stdout.write("")
        self.stdout.write(title)
        self.stdout.write("-" * len(title))

    def save_json(self, save_json_path, inspected):
        path = Path(save_json_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(
                inspected,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.stdout.write("")
        self.stdout.write(f"Raw inspection JSON saved to: {path}")


def find_relationship_like_paths(value, path="root"):
    matches = []

    if isinstance(value, dict):
        for key, child_value in value.items():
            child_path = f"{path}.{key}"

            normalized_key = str(key).lower()

            for keyword in RELATIONSHIP_KEYWORDS:
                if keyword in normalized_key:
                    matches.append((child_path, key, child_value))
                    break

            matches.extend(find_relationship_like_paths(child_value, child_path))

    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            child_path = f"{path}[{index}]"
            matches.extend(find_relationship_like_paths(child_value, child_path))

    return matches


def find_value_matches(value, needles, path="root", case_sensitive=True):
    matches = []

    for needle in needles:
        matches.extend(
            find_value_matches_for_one_needle(
                value=value,
                needle=str(needle),
                path=path,
                case_sensitive=case_sensitive,
            )
        )

    return dedupe_matches(matches)


def find_value_matches_for_one_needle(value, needle, path, case_sensitive):
    matches = []

    if isinstance(value, dict):
        for key, child_value in value.items():
            child_path = f"{path}.{key}"
            matches.extend(
                find_value_matches_for_one_needle(
                    value=child_value,
                    needle=needle,
                    path=child_path,
                    case_sensitive=case_sensitive,
                )
            )

    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            child_path = f"{path}[{index}]"
            matches.extend(
                find_value_matches_for_one_needle(
                    value=child_value,
                    needle=needle,
                    path=child_path,
                    case_sensitive=case_sensitive,
                )
            )

    else:
        text_value = str(value)

        if case_sensitive:
            haystack = text_value
            target = needle
        else:
            haystack = text_value.lower()
            target = needle.lower()

        if target in haystack:
            matches.append((path, value, needle))

    return matches


def dedupe_matches(matches):
    seen = set()
    deduped = []

    for path, value, needle in matches:
        key = (path, str(value), needle)

        if key in seen:
            continue

        seen.add(key)
        deduped.append((path, value, needle))

    return deduped


def build_volume_needles(volume_id):
    return [
        str(volume_id),
        f"4050-{volume_id}",
        f"/volume/4050-{volume_id}/",
    ]


def format_value(value):
    if value is None or value == "":
        return "None"

    return str(value)


def preview_value(value, max_length=300):
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    else:
        text = str(value)

    text = collapse_whitespace(text)

    if len(text) <= max_length:
        return text

    return text[:max_length] + "..."


def format_long_text(value, max_length=1200):
    if not value:
        return "None"

    text = collapse_whitespace(str(value))

    if len(text) <= max_length:
        return text

    return text[:max_length] + "..."


def strip_html(value):
    if not value:
        return ""

    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)

    return text


def collapse_whitespace(value):
    return " ".join(str(value).split())