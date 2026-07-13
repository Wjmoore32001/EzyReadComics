import re


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_title(value):
    value = clean_text(value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def canonical_issue_number(value):
    value = clean_text(value)
    value = re.sub(r"^\s*issue\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*no\.?\s*", "", value, flags=re.IGNORECASE)

    while value.startswith("#"):
        value = value[1:].strip()

    return value.upper()


def normalize_issue_number(value):
    value = canonical_issue_number(value).casefold()
    value = value.replace(".", "")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def pure_integer_issue_number(value):
    value = canonical_issue_number(value)

    if not value.isdigit():
        return None

    return int(value)


def issue_number_sort_key(value):
    canonical = canonical_issue_number(value)
    integer_value = pure_integer_issue_number(canonical)

    if integer_value is not None:
        return (0, integer_value, "")

    return (1, 0, canonical.casefold())