import re
from dataclasses import dataclass
from urllib.parse import unquote

from catalog.marvel.text import clean_text, canonical_issue_number


MARVEL_ISSUE_URL_RE = re.compile(
    r"/comics/issue/(?P<marvel_id>\d+)/(?P<slug>[^/?#]+)",
    re.IGNORECASE,
)

MARVEL_SERIES_URL_RE = re.compile(
    r"/comics/series/(?P<marvel_id>\d+)/(?P<slug>[^/?#]+)",
    re.IGNORECASE,
)

MARVEL_COLLECTION_URL_RE = re.compile(
    r"/comics/collection/(?P<marvel_id>\d+)/(?P<slug>[^/?#]+)",
    re.IGNORECASE,
)

MARVEL_ISSUE_SLUG_RE = re.compile(
    r"(?P<title>.+)_(?P<year>\d{4})_(?P<issue>[a-z0-9.\-]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MarvelIssueUrl:
    marvel_id: str
    slug: str
    url: str
    run_title: str = ""
    start_year: str = ""
    issue_number: str = ""


@dataclass(frozen=True)
class MarvelSeriesUrl:
    marvel_id: str
    slug: str
    url: str


@dataclass(frozen=True)
class MarvelCollectionUrl:
    marvel_id: str
    slug: str
    url: str


def parse_marvel_issue_url(url):
    url = clean_text(url)
    match = MARVEL_ISSUE_URL_RE.search(url)

    if not match:
        return None

    slug = clean_text(unquote(match.group("slug")))
    slug_data = parse_issue_slug(slug)

    return MarvelIssueUrl(
        marvel_id=clean_text(match.group("marvel_id")),
        slug=slug,
        url=url,
        run_title=slug_data.get("run_title", ""),
        start_year=slug_data.get("start_year", ""),
        issue_number=slug_data.get("issue_number", ""),
    )


def parse_marvel_series_url(url):
    url = clean_text(url)
    match = MARVEL_SERIES_URL_RE.search(url)

    if not match:
        return None

    return MarvelSeriesUrl(
        marvel_id=clean_text(match.group("marvel_id")),
        slug=clean_text(unquote(match.group("slug"))),
        url=url,
    )


def parse_marvel_collection_url(url):
    url = clean_text(url)
    match = MARVEL_COLLECTION_URL_RE.search(url)

    if not match:
        return None

    return MarvelCollectionUrl(
        marvel_id=clean_text(match.group("marvel_id")),
        slug=clean_text(unquote(match.group("slug"))),
        url=url,
    )


def is_marvel_issue_url(url):
    return parse_marvel_issue_url(url) is not None


def is_marvel_series_url(url):
    return parse_marvel_series_url(url) is not None


def is_marvel_collection_url(url):
    return parse_marvel_collection_url(url) is not None


def parse_issue_slug(slug):
    slug = clean_text(slug)
    match = MARVEL_ISSUE_SLUG_RE.match(slug)

    if not match:
        return {}

    return {
        "run_title": title_from_slug(match.group("title")),
        "start_year": clean_text(match.group("year")),
        "issue_number": canonical_issue_number(match.group("issue")),
    }


def title_from_slug(value):
    value = clean_text(value)
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    return value.title()