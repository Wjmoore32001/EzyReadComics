from contextlib import contextmanager

from django.core.management.base import CommandError

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = None
    sync_playwright = None


MARVEL_CALENDAR_TIME_ZONE = "America/New_York"
DEFAULT_CALENDAR_TIMEOUT_MS = 45000
DEFAULT_DETAIL_TIMEOUT_MS = 45000

NETWORK_IDLE_CAP_MS = 3000

BLOCKED_RESOURCE_TYPES = {
    "image",
    "media",
    "font",
}


def ensure_playwright():
    if sync_playwright is None:
        raise CommandError(
            "Playwright is not installed. Run: "
            "pip install playwright && python -m playwright install chromium"
        )


def build_browser_context(browser):
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={
            "width": 1440,
            "height": 1800,
        },
        locale="en-US",
        timezone_id=MARVEL_CALENDAR_TIME_ZONE,
    )
    install_fast_resource_blocking(context)
    return context


def install_fast_resource_blocking(context):
    def handle_route(route):
        resource_type = route.request.resource_type

        if resource_type in BLOCKED_RESOURCE_TYPES:
            route.abort()
            return

        route.continue_()

    context.route("**/*", handle_route)


@contextmanager
def marvel_browser_context(*, headed=False):
    ensure_playwright()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = build_browser_context(browser)

        try:
            yield context
        finally:
            safe_close_context(context)
            safe_close_browser(browser)


def safe_wait_for_networkidle(*, page, timeout_ms):
    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=min(timeout_ms, NETWORK_IDLE_CAP_MS),
        )
    except Exception:
        pass


def safe_close_page(page):
    if page is None:
        return

    try:
        page.close()
    except Exception:
        pass


def safe_close_context(context):
    if context is None:
        return

    try:
        context.close()
    except Exception:
        pass


def safe_close_browser(browser):
    if browser is None:
        return

    try:
        browser.close()
    except Exception:
        pass