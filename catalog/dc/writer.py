import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from django.db.models import Count, Max, Min
from django.utils.text import slugify

from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicOneShot,
    ComicOneShotCredit,
    ComicPublisher,
    ComicRun,
    ComicVolume,
    ComicVolumeCredit,
    ComicVolumeIssue,
    ComicVolumeRun,
    CreditPerson,
    CreditRole,
)


DC_PUBLISHER_NAME = "DC"
MAX_ISSUE_NUMBER_LENGTH = 50

SERIES_WITH_YEAR_RE = re.compile(
    r"^(?P<title>.+?)\s*\((?P<start_year>\d{4})(?P<ongoing>\s*-\s*)?(?P<end_year>\d{4})?\)\s*$",
    re.IGNORECASE,
)
TRAILING_YEAR_RE = re.compile(r"^(?P<title>.+?)\s+(?P<start_year>\d{4})$")
DETAIL_TITLE_YEAR_RE = re.compile(
    r"^(?P<title>.+?)\s*\((?P<start_year>\d{4})(?P<ongoing>\s*-\s*)?(?P<end_year>\d{4})?\)"
)

ROLE_DISPLAY_ORDER = {
    "Writer": 10,
    "Artist": 20,
    "Penciller": 30,
    "Inker": 40,
    "Colorist": 50,
    "Letterer": 60,
    "Cover Artist": 70,
    "Editor": 80,
}


@dataclass
class DcRunIdentity:
    title: str = ""
    start_year: str = ""


@dataclass
class DcWriteResult:
    runs_created: int = 0
    runs_updated: int = 0
    run_stats_updated: int = 0
    issues_created: int = 0
    issues_updated: int = 0
    volumes_created: int = 0
    volumes_updated: int = 0
    one_shots_created: int = 0
    one_shots_updated: int = 0
    volume_runs_created: int = 0
    volume_runs_updated: int = 0
    volume_issues_created: int = 0
    credits_added: int = 0
    skipped: int = 0


def add_results(target, source):
    for field_name in target.__dataclass_fields__:
        setattr(target, field_name, getattr(target, field_name) + getattr(source, field_name))

    return target


def get_or_create_dc_publisher():
    existing = ComicPublisher.objects.filter(name__iexact=DC_PUBLISHER_NAME).first()

    if existing:
        return existing

    base_slug = slugify(DC_PUBLISHER_NAME) or "dc"
    slug = base_slug
    suffix = 2

    while ComicPublisher.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    return ComicPublisher.objects.create(
        name=DC_PUBLISHER_NAME,
        slug=slug,
    )


def preview_publisher():
    return PreviewObject(name=DC_PUBLISHER_NAME)


def write_dc_detail(*, detail, dry_run=False):
    if detail.classification == "issue":
        return write_issue_detail(detail=detail, dry_run=dry_run)

    if detail.classification == "collected_volume":
        return write_volume_detail(detail=detail, dry_run=dry_run)

    if detail.classification == "standalone_graphic_novel_or_one_shot":
        return write_one_shot_detail(detail=detail, dry_run=dry_run)

    result = DcWriteResult()
    result.skipped = 1
    return result


def write_issue_detail(*, detail, dry_run=False):
    result = DcWriteResult()
    publisher = preview_publisher() if dry_run else get_or_create_dc_publisher()

    run, run_result = get_or_create_run_from_detail(
        publisher=publisher,
        detail=detail,
        dry_run=dry_run,
    )
    add_results(result, run_result)

    issue, issue_result = get_or_create_issue_from_detail(
        run=run,
        detail=detail,
        dry_run=dry_run,
    )
    add_results(result, issue_result)

    if issue is not None:
        result.credits_added += add_issue_credits(
            issue=issue,
            credits=detail.credits,
            dry_run=dry_run,
        )

    result.run_stats_updated += sync_run_stats(
        run=run,
        dry_run=dry_run,
    )

    return result


def write_volume_detail(*, detail, dry_run=False):
    result = DcWriteResult()
    publisher = preview_publisher() if dry_run else get_or_create_dc_publisher()

    run, run_result = get_or_create_run_from_detail(
        publisher=publisher,
        detail=detail,
        dry_run=dry_run,
    )
    add_results(result, run_result)

    volume, volume_result = get_or_create_volume_from_detail(
        publisher=publisher,
        run=run,
        detail=detail,
        dry_run=dry_run,
    )
    add_results(result, volume_result)

    result.credits_added += add_volume_credits(
        volume=volume,
        credits=detail.credits,
        dry_run=dry_run,
    )

    volume_run_result = create_or_update_volume_run(
        volume=volume,
        run=run,
        issue_numbers=detail.collection_parse.issue_numbers,
        dry_run=dry_run,
    )
    add_results(result, volume_run_result)

    for index, link in enumerate(detail.collection_parse.matched_issue_links, start=1):
        issue_number = link_issue_key(link)

        issue = find_existing_issue_by_url_or_number(
            run=run,
            source_url=link.get("href"),
            issue_number=issue_number,
        )

        if issue is None:
            continue

        link_result = create_volume_issue(
            volume=volume,
            issue=issue,
            issue_order=index,
            dry_run=dry_run,
        )
        add_results(result, link_result)

    result.run_stats_updated += sync_run_stats(
        run=run,
        dry_run=dry_run,
    )

    return result


def write_one_shot_detail(*, detail, dry_run=False):
    result = DcWriteResult()
    publisher = preview_publisher() if dry_run else get_or_create_dc_publisher()
    published_date = parse_dc_date(detail.on_sale_date_text)

    one_shot = find_existing_one_shot(
        publisher=publisher,
        source_url=detail.final_url,
        title=detail.title,
        published_date=published_date,
    )

    if one_shot is None:
        result.one_shots_created = 1

        if dry_run:
            result.credits_added += len(detail.credits)
            return result

        one_shot = ComicOneShot.objects.create(
            publisher=publisher,
            title=detail.title,
            start_year=date_year_text(published_date),
            official_source_key=source_key(detail.final_url),
            official_source_url=detail.final_url,
            published_date=published_date,
            description=detail.description,
        )
    else:
        changed = update_one_shot_from_detail(one_shot=one_shot, detail=detail)

        if changed:
            result.one_shots_updated = 1

            if not dry_run:
                one_shot.save()

    result.credits_added += add_one_shot_credits(
        one_shot=one_shot,
        credits=detail.credits,
        dry_run=dry_run,
    )

    return result


def get_or_create_run_from_detail(*, publisher, detail, dry_run=False):
    result = DcWriteResult()
    identity = run_identity_from_detail(detail)

    if not identity.title:
        result.skipped = 1
        return None, result

    existing = find_existing_run(
        publisher=publisher,
        title=identity.title,
        start_year=identity.start_year,
        source_url=series_source_url_from_identity(identity),
    )

    if existing is None:
        result.runs_created = 1

        if dry_run:
            return PreviewObject(
                title=identity.title,
                start_year=identity.start_year,
                status=run_status_from_detail(detail),
            ), result

        run = ComicRun.objects.create(
            publisher=publisher,
            title=identity.title,
            start_year=identity.start_year,
            official_source_key=source_key(series_source_url_from_identity(identity)),
            official_source_url=series_source_url_from_identity(identity),
            status=run_status_from_detail(detail),
            description="",
        )
        return run, result

    changed = update_run_from_detail(run=existing, detail=detail)

    if changed:
        result.runs_updated = 1

        if not dry_run:
            existing.save()

    return existing, result


def get_or_create_issue_from_detail(*, run, detail, dry_run=False):
    result = DcWriteResult()

    if run is None:
        result.skipped = 1
        return None, result

    issue_number = issue_number_from_detail(detail)

    if not issue_number:
        result.skipped = 1
        return None, result

    existing = find_existing_issue_by_url_or_number(
        run=run,
        source_url=detail.final_url,
        issue_number=issue_number,
    )

    published_date = parse_dc_date(detail.on_sale_date_text)

    if existing is None:
        result.issues_created = 1

        if dry_run:
            return PreviewObject(issue_number=issue_number), result

        issue = ComicIssue.objects.create(
            run=run,
            issue_number=issue_number,
            official_source_key=source_key(detail.final_url),
            official_source_url=detail.final_url,
            title="",
            published_date=published_date,
            is_released=bool(published_date),
            description=detail.description,
        )
        return issue, result

    changed = update_issue_from_detail(
        issue=existing,
        detail=detail,
        issue_number=issue_number,
        published_date=published_date,
    )

    if changed:
        result.issues_updated = 1

        if not dry_run:
            existing.save()

    return existing, result


def get_or_create_volume_from_detail(*, publisher, run, detail, dry_run=False):
    result = DcWriteResult()
    release_date = parse_dc_date(detail.on_sale_date_text)

    existing = find_existing_volume(
        publisher=publisher,
        source_url=detail.final_url,
        title=detail.title,
        release_date=release_date,
    )

    first_issue = first_issue_number(detail.collection_parse.issue_numbers)
    last_issue = last_issue_number(detail.collection_parse.issue_numbers)

    if existing is None:
        result.volumes_created = 1

        if dry_run:
            return PreviewObject(title=detail.title), result

        volume = ComicVolume.objects.create(
            publisher=publisher,
            run=run,
            title=detail.title,
            volume_number=extract_volume_number(detail.title),
            official_source_key=source_key(detail.final_url),
            official_source_url=detail.final_url,
            first_issue_number=first_issue,
            last_issue_number=last_issue,
            release_date=release_date,
            issue_count=len(detail.collection_parse.issue_numbers) or None,
            description=detail.description,
        )
        return volume, result

    changed = update_volume_from_detail(
        volume=existing,
        run=run,
        detail=detail,
        first_issue=first_issue,
        last_issue=last_issue,
    )

    if changed:
        result.volumes_updated = 1

        if not dry_run:
            volume.save()

    return existing, result


def create_or_update_volume_run(*, volume, run, issue_numbers, dry_run=False):
    result = DcWriteResult()

    if volume is None or run is None:
        result.skipped = 1
        return result

    first_issue = first_issue_number(issue_numbers)
    last_issue = last_issue_number(issue_numbers)
    issue_numbers_text = compact_issue_numbers(issue_numbers)

    if is_preview(volume) or is_preview(run):
        result.volume_runs_created = 1
        return result

    existing = ComicVolumeRun.objects.filter(volume=volume, run=run).first()

    if existing is None:
        result.volume_runs_created = 1

        if dry_run:
            return result

        ComicVolumeRun.objects.create(
            volume=volume,
            run=run,
            first_issue_number=first_issue,
            last_issue_number=last_issue,
            issue_numbers_text=issue_numbers_text,
            item_order=1,
        )
        return result

    changed = (
        existing.first_issue_number != first_issue
        or existing.last_issue_number != last_issue
        or existing.issue_numbers_text != issue_numbers_text
    )

    if changed:
        result.volume_runs_updated = 1

        if not dry_run:
            existing.first_issue_number = first_issue
            existing.last_issue_number = last_issue
            existing.issue_numbers_text = issue_numbers_text
            existing.save()

    return result


def create_volume_issue(*, volume, issue, issue_order, dry_run=False):
    result = DcWriteResult()

    if is_preview(volume) or is_preview(issue):
        result.volume_issues_created = 1
        return result

    existing = ComicVolumeIssue.objects.filter(volume=volume, issue=issue).first()

    if existing:
        if not dry_run and existing.issue_order != issue_order:
            existing.issue_order = issue_order
            existing.save(update_fields=["issue_order"])
        return result

    result.volume_issues_created = 1

    if dry_run:
        return result

    ComicVolumeIssue.objects.create(
        volume=volume,
        issue=issue,
        issue_order=issue_order,
    )
    return result


def find_existing_run(*, publisher, title, start_year, source_url):
    if is_preview(publisher):
        return None

    source = source_key(source_url)

    if source:
        match = (
            ComicRun.objects.filter(
                publisher=publisher,
                official_source_key=source,
            )
            .order_by("id")
            .first()
        )

        if match:
            return match

    queryset = ComicRun.objects.filter(
        publisher=publisher,
        title__iexact=title,
    )

    if start_year:
        match = queryset.filter(start_year=start_year).order_by("id").first()

        if match:
            return match

    match = queryset.order_by("id").first()

    if match:
        return match

    legacy_title = clean_text(f"{title} {start_year}")

    if legacy_title and start_year:
        legacy_match = (
            ComicRun.objects.filter(
                publisher=publisher,
                title__iexact=legacy_title,
                start_year="",
            )
            .order_by("id")
            .first()
        )

        if legacy_match:
            return legacy_match

    return None


def find_existing_issue_by_url_or_number(*, run, source_url, issue_number):
    if run is None or is_preview(run):
        return None

    source = source_key(source_url)

    if source:
        match = (
            ComicIssue.objects.filter(
                run=run,
                official_source_key=source,
            )
            .order_by("id")
            .first()
        )

        if match:
            return match

    if issue_number:
        return (
            ComicIssue.objects.filter(
                run=run,
                issue_number=issue_number,
            )
            .order_by("id")
            .first()
        )

    return None


def find_existing_volume(*, publisher, source_url, title, release_date):
    if is_preview(publisher):
        return None

    source = source_key(source_url)

    if source:
        match = (
            ComicVolume.objects.filter(
                publisher=publisher,
                official_source_key=source,
            )
            .order_by("id")
            .first()
        )

        if match:
            return match

    queryset = ComicVolume.objects.filter(
        publisher=publisher,
        title__iexact=title,
    )

    if release_date:
        match = queryset.filter(release_date=release_date).order_by("id").first()

        if match:
            return match

    return queryset.order_by("id").first()


def find_existing_one_shot(*, publisher, source_url, title, published_date):
    if is_preview(publisher):
        return None

    source = source_key(source_url)

    if source:
        match = (
            ComicOneShot.objects.filter(
                publisher=publisher,
                official_source_key=source,
            )
            .order_by("id")
            .first()
        )

        if match:
            return match

    queryset = ComicOneShot.objects.filter(
        publisher=publisher,
        title__iexact=title,
    )

    if published_date:
        match = queryset.filter(published_date=published_date).order_by("id").first()

        if match:
            return match

    return queryset.order_by("id").first()


def update_run_from_detail(*, run, detail):
    changed = False
    identity = run_identity_from_detail(detail)

    if identity.title and run.title != identity.title:
        run.title = identity.title
        changed = True

    if identity.start_year and run.start_year != identity.start_year:
        run.start_year = identity.start_year
        changed = True

    source_url_value = series_source_url_from_identity(identity)
    source_key_value = source_key(source_url_value)

    if source_key_value and run.official_source_key != source_key_value:
        run.official_source_key = source_key_value
        changed = True

    if source_url_value and run.official_source_url != source_url_value:
        run.official_source_url = source_url_value
        changed = True

    status = run_status_from_detail(detail)

    if status and run.status != status:
        run.status = status
        changed = True

    if detail.description and is_mainline_first_issue_detail(detail) and run.description != detail.description:
        run.description = detail.description
        changed = True

    return changed


def update_issue_from_detail(*, issue, detail, issue_number, published_date):
    changed = False

    source = source_key(detail.final_url)

    if source and issue.official_source_key != source:
        issue.official_source_key = source
        changed = True

    if detail.final_url and issue.official_source_url != detail.final_url:
        issue.official_source_url = detail.final_url
        changed = True

    if issue.issue_number != issue_number:
        duplicate_exists = (
            ComicIssue.objects.filter(
                run=issue.run,
                issue_number=issue_number,
            )
            .exclude(id=issue.id)
            .exists()
        )

        if not duplicate_exists:
            issue.issue_number = issue_number
            changed = True

    if published_date and issue.published_date != published_date:
        issue.published_date = published_date
        changed = True

    if published_date and not issue.is_released:
        issue.is_released = True
        changed = True

    if detail.description and not issue.description:
        issue.description = detail.description
        changed = True

    if issue.title:
        issue.title = ""
        changed = True

    return changed


def update_volume_from_detail(*, volume, run, detail, first_issue, last_issue):
    changed = False
    release_date = parse_dc_date(detail.on_sale_date_text)
    source = source_key(detail.final_url)

    if run is not None and not is_preview(run) and volume.run_id != run.id:
        volume.run = run
        changed = True

    if source and volume.official_source_key != source:
        volume.official_source_key = source
        changed = True

    if detail.final_url and volume.official_source_url != detail.final_url:
        volume.official_source_url = detail.final_url
        changed = True

    if detail.title and volume.title != detail.title:
        volume.title = detail.title
        changed = True

    volume_number = extract_volume_number(detail.title)

    if volume_number and volume.volume_number != volume_number:
        volume.volume_number = volume_number
        changed = True

    if first_issue and volume.first_issue_number != first_issue:
        volume.first_issue_number = first_issue
        changed = True

    if last_issue and volume.last_issue_number != last_issue:
        volume.last_issue_number = last_issue
        changed = True

    issue_count = len(detail.collection_parse.issue_numbers) or None

    if issue_count and volume.issue_count != issue_count:
        volume.issue_count = issue_count
        changed = True

    if release_date and volume.release_date != release_date:
        volume.release_date = release_date
        changed = True

    if detail.description and not volume.description:
        volume.description = detail.description
        changed = True

    return changed


def update_one_shot_from_detail(*, one_shot, detail):
    changed = False
    published_date = parse_dc_date(detail.on_sale_date_text)
    source = source_key(detail.final_url)

    if source and one_shot.official_source_key != source:
        one_shot.official_source_key = source
        changed = True

    if detail.final_url and one_shot.official_source_url != detail.final_url:
        one_shot.official_source_url = detail.final_url
        changed = True

    if published_date and one_shot.published_date != published_date:
        one_shot.published_date = published_date
        changed = True

    if detail.description and not one_shot.description:
        one_shot.description = detail.description
        changed = True

    if not one_shot.start_year and published_date:
        one_shot.start_year = str(published_date.year)
        changed = True

    return changed


def sync_run_stats(*, run, dry_run=False):
    if run is None or is_preview(run) or dry_run:
        return 0

    stats = run.issues.aggregate(
        issue_count=Count("id"),
        first_issue_date=Min("published_date"),
        last_issue_date=Max("published_date"),
    )
    issue_count = stats["issue_count"] or None
    first_issue_date = stats["first_issue_date"]
    last_issue_date = stats["last_issue_date"]

    changed = False

    if run.issue_count != issue_count:
        run.issue_count = issue_count
        changed = True

    if run.first_issue_date != first_issue_date:
        run.first_issue_date = first_issue_date
        changed = True

    if run.last_issue_date != last_issue_date:
        run.last_issue_date = last_issue_date
        changed = True

    if changed:
        run.save()
        return 1

    return 0


def add_issue_credits(*, issue, credits, dry_run=False):
    if issue is None:
        return 0

    if is_preview(issue):
        return len(credits)

    return add_credits(
        object_name="issue",
        target=issue,
        credits=credits,
        dry_run=dry_run,
    )


def add_one_shot_credits(*, one_shot, credits, dry_run=False):
    if one_shot is None:
        return 0

    if is_preview(one_shot):
        return len(credits)

    return add_credits(
        object_name="one_shot",
        target=one_shot,
        credits=credits,
        dry_run=dry_run,
    )


def add_volume_credits(*, volume, credits, dry_run=False):
    if volume is None:
        return 0

    if is_preview(volume):
        return len(credits)

    return add_credits(
        object_name="volume",
        target=volume,
        credits=credits,
        dry_run=dry_run,
    )


def add_credits(*, object_name, target, credits, dry_run=False):
    through_model = credit_model_for_object_name(object_name)

    if through_model is None:
        return 0

    created_count = 0

    for index, credit in enumerate(credits, start=1):
        role_name = clean_text(credit.get("role"))
        person_name = clean_text(credit.get("name"))

        if not role_name or not person_name:
            continue

        exists_kwargs = {
            object_name: target,
            "person__name__iexact": person_name,
            "role__name__iexact": role_name,
        }

        if through_model.objects.filter(**exists_kwargs).exists():
            continue

        created_count += 1

        if dry_run:
            continue

        role = get_or_create_credit_role(role_name)
        person = get_or_create_credit_person(person_name)

        create_kwargs = {
            object_name: target,
            "person": person,
            "role": role,
            "credit_order": index,
        }
        through_model.objects.create(**create_kwargs)

    return created_count


def credit_model_for_object_name(object_name):
    if object_name == "issue":
        return ComicIssueCredit

    if object_name == "one_shot":
        return ComicOneShotCredit

    if object_name == "volume":
        return ComicVolumeCredit

    return None


def get_or_create_credit_role(name):
    display_order = ROLE_DISPLAY_ORDER.get(name, 100)
    role = CreditRole.objects.filter(name__iexact=name).first()

    if role is None:
        return CreditRole.objects.create(
            name=name,
            display_order=display_order,
            show_by_default=True,
        )

    changed = False

    if role.display_order != display_order:
        role.display_order = display_order
        changed = True

    if not role.show_by_default:
        role.show_by_default = True
        changed = True

    if changed:
        role.save()

    return role


def get_or_create_credit_person(name):
    existing = CreditPerson.objects.filter(name__iexact=name).first()

    if existing:
        return existing

    return CreditPerson.objects.create(name=name)


def run_identity_from_detail(detail):
    raw = clean_text(detail.series.raw)
    parsed_title = clean_text(detail.series.title)
    parsed_start_year = clean_text(detail.series.start_year)

    if parsed_title and parsed_start_year:
        return DcRunIdentity(
            title=parsed_title,
            start_year=parsed_start_year,
        )

    raw_year_match = TRAILING_YEAR_RE.match(raw)

    if raw_year_match:
        return DcRunIdentity(
            title=clean_text(raw_year_match.group("title")),
            start_year=clean_text(raw_year_match.group("start_year")),
        )

    raw_parenthetical_match = SERIES_WITH_YEAR_RE.match(raw)

    if raw_parenthetical_match:
        return DcRunIdentity(
            title=clean_text(raw_parenthetical_match.group("title")),
            start_year=clean_text(raw_parenthetical_match.group("start_year")),
        )

    title_match = DETAIL_TITLE_YEAR_RE.match(clean_text(detail.title))

    if title_match:
        return DcRunIdentity(
            title=clean_text(title_match.group("title")),
            start_year=clean_text(title_match.group("start_year")),
        )

    if parsed_title:
        return DcRunIdentity(title=parsed_title)

    if raw:
        return DcRunIdentity(title=raw)

    return DcRunIdentity()


def run_status_from_detail(detail):
    raw = clean_text(detail.series.raw)
    raw_parenthetical_match = SERIES_WITH_YEAR_RE.match(raw)

    if raw_parenthetical_match:
        has_ongoing_dash = bool(raw_parenthetical_match.group("ongoing"))
        has_end_year = bool(clean_text(raw_parenthetical_match.group("end_year")))

        if has_ongoing_dash and not has_end_year:
            return ComicRun.STATUS_ONGOING

        return ComicRun.STATUS_COMPLETED

    if detail.series.is_ongoing:
        return ComicRun.STATUS_ONGOING

    title_match = DETAIL_TITLE_YEAR_RE.match(clean_text(detail.title))

    if title_match:
        has_ongoing_dash = bool(title_match.group("ongoing"))
        has_end_year = bool(clean_text(title_match.group("end_year")))

        if has_ongoing_dash and not has_end_year:
            return ComicRun.STATUS_ONGOING

        if has_end_year:
            return ComicRun.STATUS_COMPLETED

    if clean_text(detail.series.end_year):
        return ComicRun.STATUS_COMPLETED

    return ComicRun.STATUS_UNKNOWN


def is_mainline_first_issue_detail(detail):
    issue_number = clean_text(getattr(detail, "issue_number", ""))
    issue_key = clean_text(getattr(detail, "issue_key", ""))
    title = clean_text(getattr(detail, "title", ""))

    if issue_number != "1":
        return False

    if issue_key and issue_key != issue_number:
        return False

    return not looks_like_special_issue_text(title)


def looks_like_special_issue_text(value):
    value = f" {clean_text(value).casefold()} "
    return any(
        marker in value
        for marker in [
            " annual ",
            " annual #",
            " noir edition ",
            " noir edition #",
            " ark m ",
            " ark m #",
            ": ark ",
            ": ark m",
            " special ",
            " special #",
        ]
    )


def series_source_url_from_identity(identity):
    if identity.title and identity.start_year:
        return f"https://www.dc.com/comics/{slugify(identity.title)}-{identity.start_year}"

    return ""


def source_key(url):
    url = clean_text(url)

    if not url:
        return ""

    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if path:
        return path

    return url


def issue_number_from_detail(detail):
    issue_number = clean_text(getattr(detail, "issue_number", ""))
    issue_key = clean_text(getattr(detail, "issue_key", ""))
    value = issue_key or issue_number

    if not value:
        return ""

    if len(value) <= MAX_ISSUE_NUMBER_LENGTH:
        return value

    if issue_key and issue_number and issue_key != issue_number:
        return shortened_issue_key(
            issue_key=issue_key,
            issue_number=issue_number,
        )

    if issue_number:
        return issue_number[:MAX_ISSUE_NUMBER_LENGTH]

    return value[:MAX_ISSUE_NUMBER_LENGTH]


def shortened_issue_key(*, issue_key, issue_number):
    issue_key = clean_text(issue_key)
    issue_number = clean_text(issue_number)

    if not issue_number:
        return issue_key[:MAX_ISSUE_NUMBER_LENGTH]

    suffix = f"#{issue_number}"

    if len(suffix) >= MAX_ISSUE_NUMBER_LENGTH:
        return issue_number[:MAX_ISSUE_NUMBER_LENGTH]

    base = issue_key

    if base.casefold().endswith(suffix.casefold()):
        base = base[: -len(suffix)]

    base = clean_text(base).strip(" #:,-")
    base_slug = slugify(base) or "special"
    max_base_length = MAX_ISSUE_NUMBER_LENGTH - len(suffix)

    shortened = f"{base_slug[:max_base_length].strip('-')}{suffix}"
    shortened = shortened.strip("-")

    if not shortened:
        return issue_number[:MAX_ISSUE_NUMBER_LENGTH]

    return shortened[:MAX_ISSUE_NUMBER_LENGTH]


def parse_dc_date(value):
    value = clean_text(value)

    if not value:
        return None

    value = re.sub(r"(\d+)(st|nd|rd|th),", r"\1,", value)

    for fmt in ["%A, %B %d, %Y", "%B %d, %Y"]:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def date_year_text(value):
    if value:
        return str(value.year)

    return ""


def extract_volume_number(title):
    title = clean_text(title)
    marker = "VOL."

    if marker not in title.upper():
        return ""

    after_marker = title.upper().split(marker, 1)[1].strip()
    value = after_marker.split(" ", 1)[0].strip(" :,-")

    return value if value.isdigit() else ""


def compact_issue_numbers(issue_numbers):
    values = [clean_text(value) for value in issue_numbers if clean_text(value)]

    if not values:
        return ""

    numeric_values = []

    for value in values:
        if not value.isdigit():
            return ",".join(values)

        numeric_values.append(int(value))

    numeric_values = sorted(set(numeric_values))

    parts = []
    start = numeric_values[0]
    previous = numeric_values[0]

    for value in numeric_values[1:]:
        if value == previous + 1:
            previous = value
            continue

        parts.append(format_issue_range(start, previous))
        start = value
        previous = value

    parts.append(format_issue_range(start, previous))

    return ",".join(parts)


def format_issue_range(start, end):
    if start == end:
        return str(start)

    return f"{start}-{end}"


def first_issue_number(issue_numbers):
    numbers = [clean_text(value) for value in issue_numbers if clean_text(value)]

    if not numbers:
        return ""

    numeric = [int(value) for value in numbers if value.isdigit()]

    if len(numeric) == len(numbers):
        return str(min(numeric))

    return numbers[0]


def last_issue_number(issue_numbers):
    numbers = [clean_text(value) for value in issue_numbers if clean_text(value)]

    if not numbers:
        return ""

    numeric = [int(value) for value in numbers if value.isdigit()]

    if len(numeric) == len(numbers):
        return str(max(numeric))

    return numbers[-1]


def link_issue_key(link):
    from catalog.dc.browser import build_dc_issue_key

    label = clean_text(link.get("label"))
    issue_number = link_issue_number(link)

    if not issue_number:
        return ""

    return build_dc_issue_key(
        title=label,
        issue_number=issue_number,
    )


def link_issue_number(link):
    from catalog.dc.browser import link_issue_number as parse_link_issue_number

    return parse_link_issue_number(link)


def clean_text(value):
    return str(value or "").strip()


class PreviewObject:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.id = None
        self.pk = None


def is_preview(value):
    return isinstance(value, PreviewObject)