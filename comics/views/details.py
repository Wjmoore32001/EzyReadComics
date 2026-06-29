from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render

from comics.models import ComicIssue
from comics.selectors import (
    get_issue_detail_by_id,
    get_issues_for_run,
    get_run_detail_by_id,
)


DETAIL_PAGE_SIZE = 100


def run_detail(request, run_id):
    run = get_run_detail_by_id(run_id)

    if not run:
        raise Http404("Run not found.")

    issue_page_obj = paginate_queryset(
        request=request,
        queryset=get_issues_for_run(run),
        page_size=DETAIL_PAGE_SIZE,
    )

    context = {
        "run": run,
        "id_fields": build_run_id_fields(run),
        "detail_groups": build_run_detail_groups(run),
        "text_blocks": build_run_text_blocks(run),
        "volume_credits": run.person_credits.select_related("person").all(),
        "issue_page_obj": issue_page_obj,
    }

    return render(request, "comics/run_details.html", context)


def issue_detail(request, issue_id):
    issue = get_issue_detail_by_id(issue_id)

    if not issue:
        raise Http404("Issue not found.")

    if issue.volume:
        other_issues = get_issues_for_run(issue.volume).exclude(id=issue.id)
    else:
        other_issues = ComicIssue.objects.none()

    other_issue_page_obj = paginate_queryset(
        request=request,
        queryset=other_issues,
        page_size=DETAIL_PAGE_SIZE,
    )

    context = {
        "issue": issue,
        "id_fields": build_issue_id_fields(issue),
        "detail_groups": build_issue_detail_groups(issue),
        "text_blocks": build_issue_text_blocks(issue),
        "issue_credit_groups": build_issue_credit_groups(issue),
        "other_issue_page_obj": other_issue_page_obj,
    }

    return render(request, "comics/issue_details.html", context)


def paginate_queryset(request, queryset, page_size):
    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get("page")

    return paginator.get_page(page_number)


def build_run_id_fields(run):
    return [
        detail_field("Local run ID", run.id),
        detail_field("Comic Vine volume ID", run.comicvine_id),
        detail_field("Publisher Comic Vine ID", run.publisher_comicvine_id),
        detail_field("First issue Comic Vine ID", run.first_issue_comicvine_id),
        detail_field("Last issue Comic Vine ID", run.last_issue_comicvine_id),
    ]


def build_issue_id_fields(issue):
    volume = issue.volume

    return [
        detail_field("Local issue ID", issue.id),
        detail_field("Comic Vine issue ID", issue.comicvine_id),
        detail_field("Local run ID", volume.id if volume else None),
        detail_field("Comic Vine volume ID", volume.comicvine_id if volume else None),
        detail_field(
            "Publisher Comic Vine ID",
            volume.publisher_comicvine_id if volume else None,
        ),
    ]


def build_run_detail_groups(run):
    return [
        {
            "title": "Run overview",
            "fields": [
                detail_field("Name", run.name),
                detail_field("Publisher", run.publisher),
                detail_field("Start year", run.start_year),
                detail_field("Comic Vine issue count", run.count_of_issues),
                detail_field("Stored issue count", getattr(run, "stored_issue_count", None)),
                detail_field(
                    "Latest local issue store date",
                    getattr(run, "latest_store_date", None),
                ),
            ],
        },
        {
            "title": "Comic Vine and sync data",
            "fields": [
                detail_link_field("Comic Vine page", run.comicvine_url),
                detail_link_field("Comic Vine API detail URL", run.api_detail_url),
                detail_link_field("Publisher API detail URL", run.publisher_api_detail_url),
                detail_field("Date added on Comic Vine", run.date_added),
                detail_field("Date last updated on Comic Vine", run.date_last_updated),
                detail_field("Detail hydration attempted at", run.detail_hydration_attempted_at),
                detail_field("Detail hydrated at", run.detail_hydrated_at),
            ],
        },
        {
            "title": "First and last issue data",
            "fields": [
                detail_field("First issue number", run.first_issue_number),
                detail_field("First issue name", run.first_issue_name),
                detail_field("First issue Comic Vine ID", run.first_issue_comicvine_id),
                detail_link_field("First issue API URL", run.first_issue_api_url),
                detail_field("Last issue number", run.last_issue_number),
                detail_field("Last issue name", run.last_issue_name),
                detail_field("Last issue Comic Vine ID", run.last_issue_comicvine_id),
                detail_link_field("Last issue API URL", run.last_issue_api_url),
            ],
        },
        {
            "title": "Local run status",
            "fields": [
                detail_field("Run status", run.get_run_status_display()),
                detail_field("Run status source", run.get_run_status_source_display()),
                detail_field("Run status checked at", run.run_status_checked_at),
                detail_field("Manual final issue store date", run.manual_final_issue_store_date),
            ],
        },
    ]


def build_issue_detail_groups(issue):
    volume = issue.volume

    return [
        {
            "title": "Issue overview",
            "fields": [
                detail_field("Issue number", issue.issue_number),
                detail_field("Issue title", issue.issue_title),
                detail_field("Run", volume.name if volume else None),
                detail_field("Publisher", volume.publisher if volume else None),
                detail_field("Run start year", volume.start_year if volume else None),
                detail_field("Store date", issue.store_date),
                detail_field("Cover date", issue.cover_date),
                detail_field("Has staff review", format_boolean(issue.has_staff_review)),
            ],
        },
        {
            "title": "Comic Vine and sync data",
            "fields": [
                detail_link_field("Comic Vine page", issue.comicvine_url),
                detail_link_field("Comic Vine API detail URL", issue.api_detail_url),
                detail_field("Date added on Comic Vine", issue.date_added),
                detail_field("Date last updated on Comic Vine", issue.date_last_updated),
                detail_field("Detail hydration attempted at", issue.detail_hydration_attempted_at),
                detail_field("Detail hydrated at", issue.detail_hydrated_at),
            ],
        },
        {
            "title": "Connected run data",
            "fields": [
                detail_field("Run name", volume.name if volume else None),
                detail_field("Run publisher", volume.publisher if volume else None),
                detail_field("Run start year", volume.start_year if volume else None),
                detail_field("Run Comic Vine issue count", volume.count_of_issues if volume else None),
                detail_field("Run status", volume.get_run_status_display() if volume else None),
                detail_link_field("Run Comic Vine page", volume.comicvine_url if volume else ""),
                detail_link_field("Run Comic Vine API detail URL", volume.api_detail_url if volume else ""),
            ],
        },
    ]


def build_run_text_blocks(run):
    return [
        text_block("Aliases", run.aliases),
        text_block("Deck", run.deck),
        text_block("Description", run.description),
        text_block("Manual status notes", run.manual_status_notes),
    ]


def build_issue_text_blocks(issue):
    return [
        text_block("Aliases", issue.aliases),
        text_block("Deck", issue.deck),
        text_block("Description", issue.description),
        text_block("Local notes", issue.notes),
    ]


def build_issue_credit_groups(issue):
    groups = []
    credits = issue.person_credits.select_related("person", "role").order_by(
        "role__name",
        "person__name",
    )

    for credit in credits:
        role_name = credit.role.name

        if not groups or groups[-1]["role_name"] != role_name:
            groups.append(
                {
                    "role_name": role_name,
                    "credits": [],
                }
            )

        groups[-1]["credits"].append(credit)

    return groups


def detail_field(label, value, missing="Unknown"):
    if value is None or value == "":
        return {
            "label": label,
            "value": missing,
            "url": "",
            "is_missing": True,
        }

    return {
        "label": label,
        "value": value,
        "url": "",
        "is_missing": False,
    }


def detail_link_field(label, url):
    if not url:
        return {
            "label": label,
            "value": "None",
            "url": "",
            "is_missing": True,
        }

    return {
        "label": label,
        "value": "Open",
        "url": url,
        "is_missing": False,
    }


def text_block(label, value):
    return {
        "label": label,
        "value": value,
    }


def format_boolean(value):
    if value:
        return "Yes"

    return "No"