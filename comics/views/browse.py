from django.core.paginator import Paginator
from django.shortcuts import render

from comics.selectors import (
    get_all_runs,
    get_issue_for_run,
    get_issues_for_run,
    get_publishers,
    get_run_by_id,
    get_runs_for_publisher,
)


BROWSE_PAGE_SIZE = 100


def browse(request):
    selected_publisher = request.GET.get("publisher", "").strip()
    selected_run_id = to_optional_int(request.GET.get("run"))
    selected_issue_id = to_optional_int(request.GET.get("issue"))

    selected_run = get_run_by_id(selected_run_id)
    selected_issue = None

    if selected_run and not selected_publisher:
        selected_publisher = selected_run.publisher or ""

    if selected_run and selected_publisher and selected_run.publisher != selected_publisher:
        selected_run = None
        selected_run_id = None
        selected_issue_id = None

    runs = get_runs_for_publisher(selected_publisher)

    if selected_run:
        issue_options = get_issues_for_run(selected_run)
        selected_issue = get_issue_for_run(selected_run, selected_issue_id)

        if selected_issue:
            results = issue_options.filter(id=selected_issue.id)
        else:
            results = issue_options

        result_mode = "issues"
        page_title = build_issue_result_title(selected_run, selected_issue)
    else:
        issue_options = get_issues_for_run(None)
        selected_issue_id = None

        if selected_publisher:
            results = runs
            page_title = f"{selected_publisher} runs"
        else:
            results = get_all_runs()
            page_title = "All runs"

        result_mode = "runs"

    page_obj = paginate_queryset(
        request=request,
        queryset=results,
        page_size=BROWSE_PAGE_SIZE,
    )

    context = {
        "publishers": get_publishers(),
        "runs": runs,
        "issue_options": issue_options,
        "selected_publisher": selected_publisher,
        "selected_run": selected_run,
        "selected_issue": selected_issue,
        "selected_run_id": selected_run_id,
        "selected_issue_id": selected_issue_id,
        "result_mode": result_mode,
        "page_title": page_title,
        "page_obj": page_obj,
        "base_query_string": get_base_query_string_without_page(request),
    }

    return render(request, "comics/browse.html", context)


def issue_list(request):
    return browse(request)


def volume_list(request):
    return browse(request)


def paginate_queryset(request, queryset, page_size):
    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get("page")

    return paginator.get_page(page_number)


def get_base_query_string_without_page(request):
    query_data = request.GET.copy()

    if "page" in query_data:
        query_data.pop("page")

    return query_data.urlencode()


def build_issue_result_title(run, issue):
    run_label = build_run_label(run)

    if issue:
        return f"{run_label} #{issue.issue_number}"

    return f"{run_label} issues"


def build_run_label(run):
    if run.start_year:
        return f"{run.start_year} {run.name}"

    return run.name


def to_optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None