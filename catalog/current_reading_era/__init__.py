from catalog.current_reading_era import dc, marvel


PUBLISHER_HANDLERS = (
    marvel,
    dc,
)
DEFAULT_PUBLISHER_HANDLER = marvel


def normalize_publisher_identifier(value):
    return " ".join(str(value or "").strip().casefold().split())


def get_handler_for_publisher(publisher):
    publisher_slug = normalize_publisher_identifier(getattr(publisher, "slug", ""))
    publisher_name = normalize_publisher_identifier(getattr(publisher, "name", ""))

    for handler in PUBLISHER_HANDLERS:
        if publisher_slug in handler.PUBLISHER_SLUG_ALIASES:
            return handler

        if publisher_name in handler.PUBLISHER_NAME_ALIASES:
            return handler

    return None


def publisher_option_sort_key(option):
    handler = option["handler"]
    publisher = option["publisher"]
    return (
        handler.SORT_ORDER,
        publisher.name.casefold(),
        publisher.id,
    )
