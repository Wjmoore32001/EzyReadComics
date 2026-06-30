import re

from comics.comicvine.parsing import clean_text, to_optional_int


COMICVINE_TYPED_ID_PATTERN = re.compile(r"/(\d+)-(\d+)/?$")


def extract_comicvine_id_from_url(value):
    value = clean_text(value)

    if not value:
        return None

    match = COMICVINE_TYPED_ID_PATTERN.search(value)

    if not match:
        return None

    return to_optional_int(match.group(2))


def get_remote_id(remote_object):
    if not isinstance(remote_object, dict):
        return None

    return to_optional_int(remote_object.get("id"))


def get_remote_name(remote_object):
    if not isinstance(remote_object, dict):
        return ""

    return clean_text(remote_object.get("name"))


def get_remote_api_detail_url(remote_object):
    if not isinstance(remote_object, dict):
        return ""

    return clean_text(remote_object.get("api_detail_url"))


def get_remote_site_detail_url(remote_object):
    if not isinstance(remote_object, dict):
        return ""

    return clean_text(remote_object.get("site_detail_url"))


def normalize_comicvine_ids(values, max_count=100):
    normalized_values = []
    seen_values = set()

    for value in values or []:
        normalized_value = to_optional_int(value)

        if normalized_value is None:
            continue

        if normalized_value in seen_values:
            continue

        seen_values.add(normalized_value)
        normalized_values.append(normalized_value)

    if len(normalized_values) > max_count:
        raise ValueError(f"Comic Vine ID batch cannot contain more than {max_count} IDs.")

    return normalized_values