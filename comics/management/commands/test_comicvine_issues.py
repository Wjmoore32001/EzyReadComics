import os
from datetime import date, timedelta

import requests
from django.core.management.base import BaseCommand, CommandError


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
USER_AGENT = "EzyReadComics development API test"


class Command(BaseCommand):
    help = "Fetch a tiny sample of Comic Vine issues from a rolling store_date range and print the results without saving anything."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Number of issues to fetch. Defaults to 5. Maximum allowed here is 10 for safe testing.",
        )

        parser.add_argument(
            "--days-back",
            type=int,
            default=730,
            help="How many days back from today to search. Defaults to 730 days, about 2 years.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("COMICVINE_API_KEY")

        if not api_key:
            raise CommandError(
                "COMICVINE_API_KEY is not set. Add it to your .env file."
            )

        limit = options["limit"]
        days_back = options["days_back"]

        if limit < 1:
            raise CommandError("Limit must be at least 1.")

        if limit > 10:
            raise CommandError(
                "This test command only allows a limit up to 10 so we do not spam the API."
            )

        if days_back < 1:
            raise CommandError("days-back must be at least 1.")

        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        params = {
            "api_key": api_key,
            "format": "json",
            "limit": limit,
            "sort": "store_date:desc",
            "filter": f"store_date:{start_date.isoformat()}|{end_date.isoformat()}",
            "field_list": ",".join(
                [
                    "id",
                    "issue_number",
                    "name",
                    "cover_date",
                    "store_date",
                    "site_detail_url",
                    "image",
                    "volume",
                ]
            ),
        }

        self.stdout.write(
            f"Fetching {limit} Comic Vine issues with store_date from "
            f"{start_date.isoformat()} to {end_date.isoformat()}."
        )

        data = fetch_comicvine_json(ISSUES_URL, params)

        results = data.get("results", [])

        self.stdout.write(self.style.SUCCESS(f"Fetched {len(results)} issues."))

        for issue in results:
            volume = issue.get("volume") or {}
            image = issue.get("image") or {}

            publisher_name = fetch_volume_publisher_name(api_key, volume)

            comicvine_id = issue.get("id")
            volume_name = volume.get("name") or ""
            issue_number = issue.get("issue_number") or ""
            issue_title = issue.get("name") or ""
            cover_date = issue.get("cover_date") or ""
            store_date = issue.get("store_date") or ""
            comicvine_url = issue.get("site_detail_url") or ""
            image_url = image.get("small_url") or ""

            self.stdout.write("")
            self.stdout.write(f"Comic Vine ID: {comicvine_id}")
            self.stdout.write(f"Volume: {volume_name}")
            self.stdout.write(f"Publisher: {publisher_name}")
            self.stdout.write(f"Issue Number: {issue_number}")
            self.stdout.write(f"Issue Title: {issue_title}")
            self.stdout.write(f"Cover Date: {cover_date}")
            self.stdout.write(f"Store Date: {store_date}")
            self.stdout.write(f"Comic Vine URL: {comicvine_url}")
            self.stdout.write(f"Image URL: {image_url}")


def fetch_comicvine_json(url, params):
    headers = {
        "User-Agent": USER_AGENT,
    }

    response = requests.get(url, params=params, headers=headers, timeout=30)

    if response.status_code != 200:
        raise CommandError(
            f"Comic Vine request failed with HTTP status {response.status_code}."
        )

    data = response.json()

    status_code = data.get("status_code")
    error_message = data.get("error")

    if status_code != 1:
        raise CommandError(
            f"Comic Vine API returned status_code={status_code}: {error_message}"
        )

    return data


def fetch_volume_publisher_name(api_key, volume):
    volume_api_url = volume.get("api_detail_url")

    if not volume_api_url:
        return ""

    params = {
        "api_key": api_key,
        "format": "json",
        "field_list": "name,publisher",
    }

    data = fetch_comicvine_json(volume_api_url, params)

    volume_details = data.get("results") or {}
    publisher = volume_details.get("publisher") or {}

    return publisher.get("name") or ""