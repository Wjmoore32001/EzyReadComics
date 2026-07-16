import re
from collections import defaultdict
from datetime import date


ISSUE_NUMBER_PATTERN = re.compile(r"^\s*#?\s*(-?\d+(?:\.\d+)?)\s*(.*)$")


def issue_number_sort_key(value):
    normalized_value = str(value or "").strip()
    match = ISSUE_NUMBER_PATTERN.match(normalized_value)

    if not match:
        return (1, normalized_value.casefold())

    numeric_text, suffix = match.groups()

    try:
        numeric_value = float(numeric_text)
    except ValueError:
        return (1, normalized_value.casefold())

    return (
        0,
        numeric_value,
        suffix.strip().casefold(),
        normalized_value.casefold(),
    )


def run_sort_key(run):
    return (
        run.first_issue_date or date.max,
        run.title.casefold(),
        str(run.start_year or "").casefold(),
        run.id,
    )


def issue_sort_key(issue):
    run = issue.run
    return (
        issue.published_date or date.max,
        run.first_issue_date or date.max,
        run.title.casefold(),
        str(run.start_year or "").casefold(),
        issue_number_sort_key(issue.issue_number),
        issue.id,
    )


def build_timeline(runs):
    sorted_runs = list(runs)
    sorted_runs.sort(key=run_sort_key)

    issues_by_date = defaultdict(list)
    issues_by_run_and_date = defaultdict(list)

    for run in sorted_runs:
        timeline_issues = list(getattr(run, "current_era_timeline_issues", []))
        timeline_issues.sort(key=issue_sort_key)
        run.current_era_sorted_issues = timeline_issues

        for issue in timeline_issues:
            issues_by_date[issue.published_date].append(issue)
            issues_by_run_and_date[(run.id, issue.published_date)].append(issue)

    issue_columns = {}
    next_column = 1

    for published_date in sorted(issues_by_date):
        issues_on_date = issues_by_date[published_date]
        run_ids_on_date = {issue.run_id for issue in issues_on_date}
        date_column_count = max(
            len(issues_by_run_and_date[(run_id, published_date)])
            for run_id in run_ids_on_date
        )

        for run_id in run_ids_on_date:
            run_issues_on_date = issues_by_run_and_date[(run_id, published_date)]
            run_issues_on_date.sort(key=issue_sort_key)

            for offset, issue in enumerate(run_issues_on_date):
                issue_columns[issue.id] = next_column + offset

        next_column += date_column_count

    rows = []

    for run in sorted_runs:
        row_issues = [
            {
                "issue": issue,
                "column": issue_columns[issue.id],
            }
            for issue in run.current_era_sorted_issues
        ]
        row_issues.sort(key=lambda item: item["column"])

        first_column = row_issues[0]["column"] if row_issues else None
        last_column = row_issues[-1]["column"] if row_issues else None

        rows.append(
            {
                "run": run,
                "issues": row_issues,
                "first_column": first_column,
                "line_end_column": last_column + 1 if last_column is not None else None,
            }
        )

    issue_count = sum(len(row["issues"]) for row in rows)

    return {
        "rows": rows,
        "column_count": max(next_column - 1, 1),
        "run_count": len(rows),
        "issue_count": issue_count,
    }
