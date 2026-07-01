import os

import requests

from comicvine.api.ids import normalize_comicvine_ids


ISSUES_URL = "https://comicvine.gamespot.com/api/issues/"
ISSUE_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/issue/4000-{issue_id}/"

VOLUMES_URL = "https://comicvine.gamespot.com/api/volumes/"
VOLUME_DETAIL_URL_TEMPLATE = "https://comicvine.gamespot.com/api/volume/4050-{volume_id}/"

DEFAULT_TIMEOUT = 30
MAX_LIST_LIMIT = 100


class ComicVineAPIError(RuntimeError):
    pass


def get_comicvine_api_key():
    api_key = os.getenv("COMICVINE_API_KEY")

    if not api_key:
        raise ComicVineAPIError("COMICVINE_API_KEY is not set. Add it to your .env file.")

    return api_key


def create_comicvine_session(user_agent):
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    return session


def build_field_list(fields):
    if not fields:
        return ""

    return ",".join(fields)


def validate_list_limit(limit):
    if limit < 1:
        raise ComicVineAPIError("Comic Vine list limit must be at least 1.")

    if limit > MAX_LIST_LIMIT:
        raise ComicVineAPIError("Comic Vine list limit cannot be above 100.")


def fetch_comicvine_json(session, url, params, timeout=DEFAULT_TIMEOUT):
    response = session.get(url, params=params, timeout=timeout)

    if response.status_code == 420:
        raise ComicVineAPIError(
            "Comic Vine returned HTTP 420. This is probably a temporary rate or velocity limit. "
            "Wait before running the command again."
        )

    if response.status_code != 200:
        raise ComicVineAPIError(
            f"Comic Vine request failed with HTTP status {response.status_code}."
        )

    try:
        data = response.json()
    except ValueError as error:
        raise ComicVineAPIError("Comic Vine response was not valid JSON.") from error

    status_code = data.get("status_code")
    error_message = data.get("error")

    if str(status_code) != "1":
        raise ComicVineAPIError(
            f"Comic Vine API returned status_code={status_code}: {error_message}"
        )

    return data


def fetch_issues_page(
    session,
    api_key,
    *,
    filter_value,
    fields,
    offset=0,
    limit=MAX_LIST_LIMIT,
    sort=None,
):
    validate_list_limit(limit)

    params = {
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "offset": offset,
        "filter": filter_value,
    }

    field_list = build_field_list(fields)

    if field_list:
        params["field_list"] = field_list

    if sort:
        params["sort"] = sort

    return fetch_comicvine_json(session, ISSUES_URL, params)


def fetch_volumes_page(
    session,
    api_key,
    *,
    filter_value,
    fields,
    offset=0,
    limit=MAX_LIST_LIMIT,
    sort=None,
):
    validate_list_limit(limit)

    params = {
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "offset": offset,
        "filter": filter_value,
    }

    field_list = build_field_list(fields)

    if field_list:
        params["field_list"] = field_list

    if sort:
        params["sort"] = sort

    return fetch_comicvine_json(session, VOLUMES_URL, params)


def fetch_issues_by_ids(session, api_key, *, issue_ids, fields):
    issue_ids = normalize_comicvine_ids(issue_ids, max_count=MAX_LIST_LIMIT)

    if not issue_ids:
        return empty_list_response()

    params = {
        "api_key": api_key,
        "format": "json",
        "limit": len(issue_ids),
        "offset": 0,
        "filter": "id:" + "|".join(str(issue_id) for issue_id in issue_ids),
    }

    field_list = build_field_list(fields)

    if field_list:
        params["field_list"] = field_list

    return fetch_comicvine_json(session, ISSUES_URL, params)


def fetch_volumes_by_ids(session, api_key, *, volume_ids, fields):
    volume_ids = normalize_comicvine_ids(volume_ids, max_count=MAX_LIST_LIMIT)

    if not volume_ids:
        return empty_list_response()

    params = {
        "api_key": api_key,
        "format": "json",
        "limit": len(volume_ids),
        "offset": 0,
        "filter": "id:" + "|".join(str(volume_id) for volume_id in volume_ids),
    }

    field_list = build_field_list(fields)

    if field_list:
        params["field_list"] = field_list

    return fetch_comicvine_json(session, VOLUMES_URL, params)


def fetch_issue_detail(session, api_key, *, issue_id, fields):
    issue_id = validate_detail_id(issue_id, label="issue_id")

    params = {
        "api_key": api_key,
        "format": "json",
    }

    field_list = build_field_list(fields)

    if field_list:
        params["field_list"] = field_list

    url = ISSUE_DETAIL_URL_TEMPLATE.format(issue_id=issue_id)

    return fetch_comicvine_json(session, url, params)


def fetch_volume_detail(session, api_key, *, volume_id, fields):
    volume_id = validate_detail_id(volume_id, label="volume_id")

    params = {
        "api_key": api_key,
        "format": "json",
    }

    field_list = build_field_list(fields)

    if field_list:
        params["field_list"] = field_list

    url = VOLUME_DETAIL_URL_TEMPLATE.format(volume_id=volume_id)

    return fetch_comicvine_json(session, url, params)


def validate_detail_id(value, label):
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as error:
        raise ComicVineAPIError(f"{label} must be an integer.") from error

    if normalized_value < 1:
        raise ComicVineAPIError(f"{label} must be greater than 0.")

    return normalized_value


def empty_list_response():
    return {
        "status_code": 1,
        "error": "OK",
        "number_of_total_results": 0,
        "number_of_page_results": 0,
        "results": [],
    }