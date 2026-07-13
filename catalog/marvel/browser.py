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


def ensure_playwright():
    if sync_playwright is None:
        raise CommandError(
            "Playwright is not installed. Run: "
            "pip install playwright && python -m playwright install chromium"
        )


def build_browser_context(browser):
    return browser.new_context(
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


@contextmanager
def marvel_browser_context(*, headed=False):
    ensure_playwright()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = build_browser_context(browser)

        try:
            yield context
        finally:
            context.close()
            browser.close()


def safe_wait_for_networkidle(*, page, timeout_ms):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass