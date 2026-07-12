import re
from collections import Counter
from datetime import date
from difflib import SequenceMatcher

from django.db import transaction
from django.db.models import Prefetch

from catalog.models import ComicIssue
from comicvine.models import ComicVineIssue, ComicVineVolume


MATCH_SCORE_MINIMUM = 0.34


def find_possible_comicvine_volume_matches(*, title, start_year, publisher_name, limit):
    normalized_title = normalize_title(title)
    cleaned_year = clean_text(start_year)

    if not normalized_title:
        return []

    issue_queryset = ComicVineIssue.objects.only(
        "id",
        "volume_id",
        "issue_number",
        "issue_title",
        "store_date",
        "cover_date",
    )

    volumes = ComicVineVolume.objects.only(
        "id",
        "comicvine_id",
        "name",
        "publisher",
        "start_year",
    )

    if cleaned_year:
        volumes = volumes.filter(start_year=cleaned_year)

    if publisher_name:
        publisher_filtered = volumes.filter(publisher__iexact=publisher_name)

        if publisher_filtered.exists():
            volumes = publisher_filtered

    volumes = volumes.prefetch_related(
        Prefetch(
            "issues",
            queryset=issue_queryset,
        )
    )

    matches = []

    for volume in volumes:
        score = rough_title_score(title, volume.name)

        if score < MATCH_SCORE_MINIMUM:
            continue

        source_issues = list(volume.issues.all())

        matches.append(
            {
                "volume": volume,
                "score": score,
                "issue_count": len(source_issues),
                "complete_issue_count": count_complete_source_issues(source_issues),
            }
        )

    matches.sort(
        key=lambda item: (
            item["score"],
            item["complete_issue_count"],
            item["issue_count"],
        ),
        reverse=True,
    )

    return matches[:limit]


def format_comicvine_match_line(*, index, match):
    volume = match["volume"]

    return (
        f"{index}. {volume.name} "
        f"({volume.start_year or 'unknown year'}) "
        f"[comicvine_id={volume.comicvine_id}, local_id={volume.id}, "
        f"issues={match['issue_count']}, complete={match['complete_issue_count']}, "
        f"score={match['score']:.2f}]"
    )


def copy_complete_comicvine_issues_to_catalog_run(
    *,
    catalog_run,
    comicvine_volume,
    verbose=False,
    raise_issue_count=False,
):
    source_issues = list(
        ComicVineIssue.objects.filter(volume=comicvine_volume)
        .only(
            "id",
            "volume_id",
            "issue_number",
            "issue_title",
            "store_date",
            "cover_date",
        )
        .order_by(
            "store_date",
            "cover_date",
            "issue_number",
            "id",
        )
    )

    existing_catalog_issues = {
        normalize_issue_number(issue.issue_number): issue
        for issue in catalog_run.issues.all()
    }

    result = {
        "checked": len(source_issues),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "skipped_reasons": Counter(),
        "messages": [],
        "issue_count_updated": False,
        "old_issue_count": catalog_run.issue_count,
        "new_issue_count": catalog_run.issue_count,
    }

    highest_source_issue_number = highest_numeric_issue_number(source_issues)

    with transaction.atomic():
        for source_issue in source_issues:
            validation_errors = get_source_issue_validation_errors(source_issue)

            if validation_errors:
                result["skipped"] += 1

                for reason in validation_errors:
                    result["skipped_reasons"][reason] += 1

                if verbose:
                    result["messages"].append(
                        format_source_skip_line(
                            source_issue=source_issue,
                            reasons=validation_errors,
                        )
                    )

                continue

            issue_number = canonical_issue_number(source_issue.issue_number)
            normalized_issue_number = normalize_issue_number(issue_number)
            existing_issue = existing_catalog_issues.get(normalized_issue_number)

            if existing_issue:
                changed = update_existing_catalog_issue_from_source(
                    catalog_issue=existing_issue,
                    source_issue=source_issue,
                )

                if changed:
                    existing_issue.save()
                    result["updated"] += 1

                    if verbose:
                        result["messages"].append(
                            f"Updated catalog issue from Comic Vine: {existing_issue}"
                        )
                else:
                    result["unchanged"] += 1

                    if verbose:
                        result["messages"].append(f"Already complete: {existing_issue}")

                continue

            catalog_issue = ComicIssue.objects.create(
                run=catalog_run,
                issue_number=issue_number,
                title=clean_text(source_issue.issue_title),
                store_date=source_issue.store_date,
                cover_date=source_issue.cover_date,
                is_released=is_released_from_store_date(source_issue.store_date),
                description="",
            )

            existing_catalog_issues[normalized_issue_number] = catalog_issue
            result["created"] += 1

            if verbose:
                result["messages"].append(
                    f"Created catalog issue from Comic Vine: {catalog_issue}"
                )

        if (
            raise_issue_count
            and highest_source_issue_number is not None
            and (
                catalog_run.issue_count is None
                or catalog_run.issue_count < highest_source_issue_number
            )
        ):
            catalog_run.issue_count = highest_source_issue_number
            catalog_run.save(update_fields=["issue_count", "updated_at"])
            result["issue_count_updated"] = True
            result["new_issue_count"] = catalog_run.issue_count

    return result


def update_existing_catalog_issue_from_source(*, catalog_issue, source_issue):
    changed = False
    source_issue_number = canonical_issue_number(source_issue.issue_number)

    if source_issue_number and catalog_issue.issue_number != source_issue_number:
        duplicate_exists = (
            ComicIssue.objects.filter(
                run=catalog_issue.run,
                issue_number=source_issue_number,
            )
            .exclude(id=catalog_issue.id)
            .exists()
        )

        if not duplicate_exists:
            catalog_issue.issue_number = source_issue_number
            changed = True

    source_title = clean_text(source_issue.issue_title)

    if title_needs_repair(catalog_issue.title) and source_title:
        catalog_issue.title = source_title
        changed = True

    if catalog_issue.store_date is None and source_issue.store_date is not None:
        catalog_issue.store_date = source_issue.store_date
        changed = True

    if catalog_issue.cover_date is None and source_issue.cover_date is not None:
        catalog_issue.cover_date = source_issue.cover_date
        changed = True

    source_is_released = is_released_from_store_date(source_issue.store_date)

    if catalog_issue.is_released != source_is_released:
        catalog_issue.is_released = source_is_released
        changed = True

    return changed


def get_source_issue_validation_errors(source_issue):
    errors = []

    if not canonical_issue_number(source_issue.issue_number):
        errors.append("missing issue_number")

    if not clean_text(source_issue.issue_title):
        errors.append("missing title")

    if source_issue.store_date is None:
        errors.append("missing store_date")

    if source_issue.cover_date is None:
        errors.append("missing cover_date")

    return errors


def count_complete_source_issues(source_issues):
    return sum(
        1
        for issue in source_issues
        if not get_source_issue_validation_errors(issue)
    )


def highest_numeric_issue_number(source_issues):
    highest = None

    for issue in source_issues:
        numeric_issue_number = pure_integer_issue_number(issue.issue_number)

        if numeric_issue_number is None:
            continue

        if highest is None or numeric_issue_number > highest:
            highest = numeric_issue_number

    return highest


def format_source_skip_line(*, source_issue, reasons):
    issue_number = clean_text(source_issue.issue_number) or "?"
    title = clean_text(source_issue.issue_title) or "[blank]"
    reason_text = ", ".join(reasons)

    return (
        f"Skipped Comic Vine issue #{issue_number}: "
        f"title={title}; "
        f"store_date={source_issue.store_date or 'missing'}; "
        f"cover_date={source_issue.cover_date or 'missing'}; "
        f"reason={reason_text}"
    )


def rough_title_score(catalog_title, comicvine_title):
    catalog_normalized = normalize_title(catalog_title)
    comicvine_normalized = normalize_title(comicvine_title)

    if not catalog_normalized or not comicvine_normalized:
        return 0.0

    if catalog_normalized == comicvine_normalized:
        return 1.0

    if catalog_normalized in comicvine_normalized or comicvine_normalized in catalog_normalized:
        return 0.92

    catalog_tokens = set(catalog_normalized.split())
    comicvine_tokens = set(comicvine_normalized.split())

    if not catalog_tokens or not comicvine_tokens:
        return 0.0

    token_score = len(catalog_tokens & comicvine_tokens) / max(
        len(catalog_tokens),
        len(comicvine_tokens),
    )
    sequence_score = SequenceMatcher(
        None,
        catalog_normalized,
        comicvine_normalized,
    ).ratio()

    return max(token_score, sequence_score)


def title_needs_repair(title):
    title = clean_text(title)

    if not title:
        return True

    return title.casefold() == "untitled"


def is_released_from_store_date(store_date):
    if store_date is None:
        return False

    return store_date <= date.today()


def parse_date(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def canonical_issue_number(value):
    value = clean_text(value)
    value = re.sub(r"^\s*issue\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*no\.?\s*", "", value, flags=re.IGNORECASE)

    while value.startswith("#"):
        value = value[1:].strip()

    return value.strip()


def normalize_issue_number(value):
    value = canonical_issue_number(value).casefold()
    return re.sub(r"[^a-z0-9.]+", "", value)


def pure_integer_issue_number(value):
    value = canonical_issue_number(value)

    if not value.isdigit():
        return None

    return int(value)


def normalize_title(value):
    title = clean_text(value).casefold()
    title = re.sub(r"^the\s+", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    title = " ".join(title.split())

    stop_words = {
        "a",
        "an",
        "and",
        "by",
        "of",
        "the",
    }

    return " ".join(
        token
        for token in title.split()
        if token not in stop_words
    )


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()