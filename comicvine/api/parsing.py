from datetime import datetime, time

from django.utils import timezone


COMICVINE_DATE_FORMAT = "%Y-%m-%d"
COMICVINE_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def clean_optional_text(value):
    cleaned_value = clean_text(value)

    if not cleaned_value:
        return None

    return cleaned_value


def to_optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_comicvine_date(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        return datetime.strptime(value, COMICVINE_DATE_FORMAT).date()
    except ValueError:
        return None


def parse_comicvine_datetime(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        parsed_value = datetime.strptime(value, COMICVINE_DATETIME_FORMAT)
    except ValueError:
        return None

    if timezone.is_naive(parsed_value):
        return timezone.make_aware(parsed_value, timezone.get_current_timezone())

    return parsed_value


def build_day_filter(field_name, date_value):
    start_datetime = datetime.combine(date_value, time.min)
    end_datetime = datetime.combine(date_value, time.max).replace(microsecond=0)

    return f"{field_name}:{start_datetime}|{end_datetime}"


def first_non_empty(*values):
    for value in values:
        cleaned_value = clean_text(value)

        if cleaned_value:
            return cleaned_value

    return ""


def has_usable_value(value):
    return value is not None and value != ""


def is_missing_value(value):
    return value is None or value == ""


def image_data_from_remote(remote_image, field_prefix="comicvine_image"):
    image = remote_image or {}

    return {
        f"{field_prefix}_icon_url": clean_text(image.get("icon_url")),
        f"{field_prefix}_medium_url": clean_text(image.get("medium_url")),
        f"{field_prefix}_screen_url": clean_text(image.get("screen_url")),
        f"{field_prefix}_screen_large_url": clean_text(image.get("screen_large_url")),
        f"{field_prefix}_small_url": clean_text(image.get("small_url")),
        f"{field_prefix}_super_url": clean_text(image.get("super_url")),
        f"{field_prefix}_thumb_url": clean_text(image.get("thumb_url")),
        f"{field_prefix}_tiny_url": clean_text(image.get("tiny_url")),
        f"{field_prefix}_original_url": clean_text(image.get("original_url")),
        f"{field_prefix}_tags": clean_text(image.get("image_tags")),
    }


def associated_image_data_from_remote(remote_image):
    image = remote_image or {}

    return {
        "icon_url": clean_text(image.get("icon_url")),
        "medium_url": clean_text(image.get("medium_url")),
        "screen_url": clean_text(image.get("screen_url")),
        "screen_large_url": clean_text(image.get("screen_large_url")),
        "small_url": clean_text(image.get("small_url")),
        "super_url": clean_text(image.get("super_url")),
        "thumb_url": clean_text(image.get("thumb_url")),
        "tiny_url": clean_text(image.get("tiny_url")),
        "original_url": clean_text(image.get("original_url")),
        "image_tags": clean_text(image.get("image_tags")),
        "caption": first_non_empty(
            image.get("caption"),
            image.get("name"),
            image.get("title"),
        ),
    }


def choose_display_image_url(image_data, field_prefix="comicvine_image"):
    return first_non_empty(
        image_data.get(f"{field_prefix}_original_url"),
        image_data.get(f"{field_prefix}_super_url"),
        image_data.get(f"{field_prefix}_screen_large_url"),
        image_data.get(f"{field_prefix}_medium_url"),
        image_data.get(f"{field_prefix}_small_url"),
        image_data.get(f"{field_prefix}_thumb_url"),
    )


def split_comicvine_role_string(role_value):
    role_value = clean_text(role_value)

    if not role_value:
        return []

    role_names = []

    for raw_role_name in role_value.split(","):
        role_name = clean_text(raw_role_name).lower()

        if role_name and role_name not in role_names:
            role_names.append(role_name)

    return role_names