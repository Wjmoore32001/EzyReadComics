from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from catalog.marvel.calendar import current_marvel_date
from catalog.marvel.credits import (
    ROLE_DISPLAY_ORDER,
    clean_credit_name,
    looks_like_concatenated_credit_name,
    normalize_credit_list,
    normalize_credit_role,
)
from catalog.marvel.issues import (
    get_detail_value,
    get_issue_missing_fields,
)
from catalog.marvel.text import (
    clean_text,
    normalize_issue_number,
    normalize_title,
    pure_integer_issue_number,
)
from catalog.models import (
    ComicIssue,
    ComicIssueCredit,
    ComicPublisher,
    ComicRun,
    CreditPerson,
    CreditRole,
)


MARVEL_PUBLISHER_NAME = "Marvel"


@dataclass
class WriteResult:
    run_created: int = 0
    run_updated: int = 0
    issue_created: int = 0
    issue_updated: int = 0
    credits_added: int = 0


def get_or_create_marvel_publisher():
    existing = ComicPublisher.objects.filter(name__iexact=MARVEL_PUBLISHER_NAME).first()

    if existing:
        return existing

    base_slug = slugify(MARVEL_PUBLISHER_NAME) or "marvel"
    slug = base_slug
    suffix = 2

    while ComicPublisher.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    return ComicPublisher.objects.create(
        name=MARVEL_PUBLISHER_NAME,
        slug=slug,
    )


def find_existing_run(*, title="", start_year="", marvel_series_id=""):
    title = clean_text(title)
    start_year = clean_text(start_year)
    marvel_series_id = clean_text(marvel_series_id)

    if marvel_series_id:
        match = ComicRun.objects.filter(marvel_series_id=marvel_series_id).order_by("id").first()

        if match:
            return match

    if not title:
        return None

    queryset = ComicRun.objects.all()

    if start_year:
        queryset = queryset.filter(start_year=start_year)

    exact_match = queryset.filter(title__iexact=title).order_by("id").first()

    if exact_match:
        return exact_match

    normalized_title = normalize_title(title)

    if not normalized_title:
        return None

    for run in queryset.order_by("id"):
        if normalize_title(run.title) == normalized_title:
            return run

    return None


def find_existing_issue(*, run=None, issue_number="", marvel_issue_id=""):
    marvel_issue_id = clean_text(marvel_issue_id)

    if run is not None and marvel_issue_id:
        match = (
            ComicIssue.objects.filter(run=run, marvel_issue_id=marvel_issue_id)
            .order_by("id")
            .first()
        )

        if match:
            return match

    if run is None:
        return None

    normalized_target = normalize_issue_number(issue_number)

    if not normalized_target:
        return None

    for issue in run.issues.all().order_by("id"):
        if normalize_issue_number(issue.issue_number) == normalized_target:
            return issue

    return None


def upsert_run_from_series(*, series, dry_run=False):
    publisher = None if dry_run else get_or_create_marvel_publisher()

    existing_run = find_existing_run(
        title=series.title,
        start_year=series.start_year,
        marvel_series_id=series.marvel_series_id,
    )

    result = WriteResult()

    if dry_run:
        if existing_run is None:
            result.run_created = 1
        elif run_needs_series_update(existing_run, series):
            result.run_updated = 1

        return existing_run, result

    with transaction.atomic():
        if existing_run is None:
            run = ComicRun.objects.create(
                publisher=publisher,
                title=series.title,
                start_year=series.start_year,
                marvel_series_id=series.marvel_series_id,
                marvel_series_url=series.url,
                status=series.status or ComicRun.STATUS_UNKNOWN,
                issue_count=len(series.issues) or None,
                description="",
            )
            result.run_created = 1
            return run, result

        run = existing_run

        if update_run_from_series(run=run, series=series):
            result.run_updated = 1

        return run, result


def run_needs_series_update(run, series):
    if clean_text(series.marvel_series_id) and run.marvel_series_id != clean_text(series.marvel_series_id):
        return True

    if clean_text(series.url) and run.marvel_series_url != clean_text(series.url):
        return True

    if clean_text(series.title) and run.title != clean_text(series.title):
        return True

    if clean_text(series.start_year) and run.start_year != clean_text(series.start_year):
        return True

    if clean_text(series.status) and run.status != clean_text(series.status):
        return True

    if series.issues and run.issue_count != len(series.issues):
        return True

    return False


def update_run_from_series(*, run, series):
    changed = False

    if clean_text(series.marvel_series_id) and run.marvel_series_id != clean_text(series.marvel_series_id):
        run.marvel_series_id = clean_text(series.marvel_series_id)
        changed = True

    if clean_text(series.url) and run.marvel_series_url != clean_text(series.url):
        run.marvel_series_url = clean_text(series.url)
        changed = True

    if clean_text(series.title) and run.title != clean_text(series.title):
        run.title = clean_text(series.title)
        changed = True

    if clean_text(series.start_year) and run.start_year != clean_text(series.start_year):
        run.start_year = clean_text(series.start_year)
        changed = True

    if clean_text(series.status) and run.status != clean_text(series.status):
        run.status = clean_text(series.status)
        changed = True

    if series.issues and run.issue_count != len(series.issues):
        run.issue_count = len(series.issues)
        changed = True

    if changed:
        run.save()

    return changed


def upsert_issue_from_series_issue(*, run, series_issue, detail=None, dry_run=False):
    detail = detail or None

    existing_issue = find_existing_issue(
        run=run,
        issue_number=series_issue.issue_number,
        marvel_issue_id=series_issue.marvel_issue_id,
    )

    result = WriteResult()

    if dry_run:
        if existing_issue is None:
            result.issue_created = 1
        elif issue_needs_series_or_detail_update(existing_issue, series_issue, detail):
            result.issue_updated = 1

        result.credits_added = count_new_issue_credits(
            issue=existing_issue,
            credits=get_detail_value(detail, "credits") or [],
        )
        return existing_issue, result

    with transaction.atomic():
        issue = existing_issue
        issue_was_created = False

        if issue is None:
            issue = create_issue_from_series_issue(
                run=run,
                series_issue=series_issue,
                detail=detail,
            )
            issue_was_created = True
            result.issue_created = 1
        else:
            if update_issue_from_series_issue(
                issue=issue,
                series_issue=series_issue,
                detail=detail,
            ):
                result.issue_updated = 1

        result.credits_added = add_issue_credits(
            issue=issue,
            credits=get_detail_value(detail, "credits") or [],
        )

        if detail and get_detail_value(detail, "checked"):
            tracking_changed = update_issue_official_detail_tracking(issue)

            if tracking_changed and not issue_was_created:
                result.issue_updated = 1

        return issue, result


def create_issue_from_series_issue(*, run, series_issue, detail=None):
    published_date = get_detail_value(detail, "published_date")
    description = clean_text(get_detail_value(detail, "description"))

    return ComicIssue.objects.create(
        run=run,
        issue_number=series_issue.issue_number,
        marvel_issue_id=series_issue.marvel_issue_id,
        marvel_issue_url=series_issue.detail_url,
        title="",
        cover_date=None,
        published_date=published_date,
        is_released=bool(published_date and published_date <= current_marvel_date()),
        description=description,
    )


def update_issue_from_series_issue(*, issue, series_issue, detail=None):
    changed = False

    if issue.issue_number != series_issue.issue_number:
        duplicate_exists = (
            ComicIssue.objects.filter(
                run=issue.run,
                issue_number=series_issue.issue_number,
            )
            .exclude(id=issue.id)
            .exists()
        )

        if not duplicate_exists:
            issue.issue_number = series_issue.issue_number
            changed = True

    if clean_text(series_issue.marvel_issue_id) and issue.marvel_issue_id != clean_text(series_issue.marvel_issue_id):
        issue.marvel_issue_id = clean_text(series_issue.marvel_issue_id)
        changed = True

    if clean_text(series_issue.detail_url) and issue.marvel_issue_url != clean_text(series_issue.detail_url):
        issue.marvel_issue_url = clean_text(series_issue.detail_url)
        changed = True

    published_date = get_detail_value(detail, "published_date")

    if published_date and issue.published_date != published_date:
        issue.published_date = published_date
        changed = True

    if published_date:
        is_released = published_date <= current_marvel_date()

        if issue.is_released != is_released:
            issue.is_released = is_released
            changed = True

    description = clean_text(get_detail_value(detail, "description"))

    if description and not issue.description:
        issue.description = description
        changed = True

    if issue.title:
        issue.title = ""
        changed = True

    if changed:
        issue.save()

    return changed


def issue_needs_series_or_detail_update(issue, series_issue, detail=None):
    if issue.issue_number != series_issue.issue_number:
        return True

    if clean_text(series_issue.marvel_issue_id) and issue.marvel_issue_id != clean_text(series_issue.marvel_issue_id):
        return True

    if clean_text(series_issue.detail_url) and issue.marvel_issue_url != clean_text(series_issue.detail_url):
        return True

    published_date = get_detail_value(detail, "published_date")

    if published_date and issue.published_date != published_date:
        return True

    if published_date and issue.is_released != (published_date <= current_marvel_date()):
        return True

    description = clean_text(get_detail_value(detail, "description"))

    if description and not issue.description:
        return True

    if issue.title:
        return True

    if issue_has_suspicious_credits(issue):
        return True

    if detail and get_detail_value(detail, "checked"):
        status, missing_fields = preview_official_detail_tracking(
            issue=issue,
            detail=detail,
        )

        if issue.official_detail_status != status:
            return True

        if issue.official_detail_missing_fields != missing_fields:
            return True

    if issue_has_complete_details(issue):
        if issue.official_detail_status != ComicIssue.OFFICIAL_DETAIL_STATUS_COMPLETE:
            return True

        if issue.official_detail_missing_fields:
            return True

    return False


def issue_has_complete_details(issue):
    if issue_has_suspicious_credits(issue):
        return False

    if not clean_text(issue.description):
        return False

    return issue_has_role(issue, "Writer")


def issue_has_role(issue, role_name):
    target_role = role_name.casefold()

    for credit in issue.credits.select_related("role").all():
        if credit.role.name.casefold() == target_role:
            return True

    return False


def issue_has_suspicious_credits(issue):
    for credit in issue.credits.select_related("person").all():
        if looks_like_concatenated_credit_name(credit.person.name):
            return True

    return False


def update_issue_official_detail_tracking(issue):
    missing_fields = get_issue_missing_official_fields(issue)
    status = (
        ComicIssue.OFFICIAL_DETAIL_STATUS_INCOMPLETE
        if missing_fields
        else ComicIssue.OFFICIAL_DETAIL_STATUS_COMPLETE
    )
    missing_fields_text = ",".join(missing_fields)

    changed = False

    if issue.official_detail_status != status:
        issue.official_detail_status = status
        changed = True

    if issue.official_detail_missing_fields != missing_fields_text:
        issue.official_detail_missing_fields = missing_fields_text
        changed = True

    issue.official_detail_checked_at = timezone.now()
    changed = True

    if changed:
        issue.save()

    return changed


def preview_official_detail_tracking(*, issue, detail):
    missing_fields = get_preview_missing_fields(issue=issue, detail=detail)
    status = (
        ComicIssue.OFFICIAL_DETAIL_STATUS_INCOMPLETE
        if missing_fields
        else ComicIssue.OFFICIAL_DETAIL_STATUS_COMPLETE
    )

    return status, ",".join(missing_fields)


def get_issue_missing_official_fields(issue):
    missing_fields = []

    if not clean_text(issue.description):
        missing_fields.append("description")

    if not issue_has_role(issue, "Writer"):
        missing_fields.append("writer")

    return missing_fields


def get_preview_missing_fields(*, issue, detail):
    missing_fields = []
    detail_missing_fields = get_issue_missing_fields(detail)

    has_description = "description" not in detail_missing_fields
    has_writer = "writer" not in detail_missing_fields

    if issue is not None and clean_text(issue.description):
        has_description = True

    if issue is not None and issue_has_role(issue, "Writer"):
        has_writer = True

    if not has_description:
        missing_fields.append("description")

    if not has_writer:
        missing_fields.append("writer")

    return missing_fields


def add_issue_credits(*, issue, credits):
    normalized_credits = normalize_credit_list(credits)
    remove_suspicious_issue_credits_for_replacement_roles(
        issue=issue,
        replacement_credits=normalized_credits,
    )

    created_count = 0

    for index, credit in enumerate(normalized_credits, start=1):
        role_name = normalize_credit_role(credit.get("role"))
        person_name = clean_credit_name(credit.get("name"))

        if not role_name or not person_name:
            continue

        role = get_or_create_credit_role(name=role_name)
        person = get_or_create_credit_person(person_name)

        _, created = ComicIssueCredit.objects.get_or_create(
            issue=issue,
            person=person,
            role=role,
            defaults={
                "credit_order": index,
            },
        )

        if created:
            created_count += 1

    return created_count


def remove_suspicious_issue_credits_for_replacement_roles(*, issue, replacement_credits):
    roles_with_replacements = {
        normalize_credit_role(credit.get("role")).casefold()
        for credit in replacement_credits
        if normalize_credit_role(credit.get("role"))
    }

    if not roles_with_replacements:
        return 0

    removed_count = 0

    for credit in issue.credits.select_related("person", "role").all():
        if credit.role.name.casefold() not in roles_with_replacements:
            continue

        if not looks_like_concatenated_credit_name(credit.person.name):
            continue

        credit.delete()
        removed_count += 1

    return removed_count


def count_new_issue_credits(*, issue, credits):
    normalized_credits = normalize_credit_list(credits)

    if issue is None:
        return len(normalized_credits)

    count = 0

    for credit in normalized_credits:
        role_name = normalize_credit_role(credit.get("role"))
        person_name = clean_credit_name(credit.get("name"))

        if not role_name or not person_name:
            continue

        exists = ComicIssueCredit.objects.filter(
            issue=issue,
            person__name__iexact=person_name,
            role__name__iexact=role_name,
        ).exists()

        if not exists:
            count += 1

    return count


def get_or_create_credit_role(*, name):
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