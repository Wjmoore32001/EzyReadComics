from dataclasses import dataclass, field

from catalog.marvel.text import clean_text
from catalog.marvel.writer import (
    find_existing_issue,
    find_existing_run,
    issue_has_complete_details,
    issue_has_suspicious_credits,
)


@dataclass
class IssueDetailPlan:
    series_issue: object
    existing_issue: object = None
    reason: str = ""


@dataclass
class SeriesSyncPlan:
    series: object
    existing_run: object = None
    issue_detail_plans: list[IssueDetailPlan] = field(default_factory=list)


def build_series_sync_plan(series):
    existing_run = find_existing_run(
        title=series.title,
        start_year=series.start_year,
        marvel_series_id=series.marvel_series_id,
    )

    plan = SeriesSyncPlan(
        series=series,
        existing_run=existing_run,
    )

    for series_issue in series.issues:
        existing_issue = find_existing_issue(
            run=existing_run,
            issue_number=series_issue.issue_number,
            marvel_issue_id=series_issue.marvel_issue_id,
        )

        reason = get_issue_detail_read_reason(
            existing_issue=existing_issue,
            series_issue=series_issue,
        )

        if not reason:
            continue

        plan.issue_detail_plans.append(
            IssueDetailPlan(
                series_issue=series_issue,
                existing_issue=existing_issue,
                reason=reason,
            )
        )

    return plan


def get_issue_detail_read_reason(*, existing_issue, series_issue):
    if existing_issue is None:
        return "missing local issue"

    if not clean_text(existing_issue.marvel_issue_id) and clean_text(series_issue.marvel_issue_id):
        return "missing Marvel issue ID"

    if not clean_text(existing_issue.marvel_issue_url) and clean_text(series_issue.detail_url):
        return "missing Marvel issue URL"

    if issue_has_suspicious_credits(existing_issue):
        return "suspicious existing credits"

    if not issue_has_complete_details(existing_issue):
        return "incomplete official details"

    return ""


def count_issue_detail_plans(series_plan):
    return len(series_plan.issue_detail_plans)