"""Playwright-based posting liveness verification. OPT-IN ONLY, off by
default (CLAUDE.md constraint 4 exception, 2026-07).

Augments the recency filter for the one failure mode `posting_is_recent()`
can't see: a job page that returns HTTP 200 but says "no longer accepting
applications" — that text only exists in the rendered page, not in any
API's `posted_at` field. Read-only: loads the page and reads visible
text, nothing else — no clicks, no form interaction, no login. Runs on
a bounded batch (the jobs about to be scored, not the full search-result
set), one shared headless Chromium instance per batch.

Fails OPEN, deliberately: any error, timeout, or missing Playwright
install is treated as "assume live." A liveness check's entire job is to
catch postings it can POSITIVELY identify as dead — it must never risk
wrongly dropping a real one because the check itself broke.
"""

from __future__ import annotations

# Generic phrases used across many job boards/ATS platforms when a
# posting has closed — not site-specific scraping, plain text matching,
# same discipline as violates_dealbreakers().
_DEAD_PATTERNS = (
    "no longer accepting applications",
    "no longer accepting new applicants",
    "position has been filled",
    "this position has been filled",
    "posting has expired",
    "this posting has expired",
    "job is no longer available",
    "this job is no longer available",
    "this listing is no longer active",
    "position is no longer available",
    "job posting has closed",
    "applications are now closed",
    "we are no longer accepting applications",
)


def _import_async_playwright():
    """Isolated into its own function so tests can monkeypatch this one
    seam (raise ImportError, or return a fake) without needing a real
    Playwright install."""
    from playwright.async_api import async_playwright
    return async_playwright


async def filter_dead_postings(jobs: list[dict],
                               timeout_ms: int = 15000) -> tuple[list[dict], int]:
    """Returns (live_jobs, dead_count). ONE browser launch for the whole
    batch (much cheaper than one per job); one page per job, closed
    immediately after each check.

    If Playwright isn't installed, or the browser fails to launch, this
    is a no-op: every job is returned as-is. That keeps the feature
    genuinely optional — the rest of JobScout must work with zero
    Playwright dependency present."""
    try:
        async_playwright = _import_async_playwright()
    except ImportError:
        return jobs, 0

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                live, dead_count = [], 0
                for job in jobs:
                    if await _is_dead(browser, job["url"], timeout_ms):
                        dead_count += 1
                    else:
                        live.append(job)
                return live, dead_count
            finally:
                await browser.close()
    except Exception:
        return jobs, 0  # browser launch itself failed -> no-op, fail open


async def _is_dead(browser, url: str, timeout_ms: int) -> bool:
    """True only when a dead-posting phrase was positively found. Any
    error/timeout returns False (assume live) — fail open."""
    try:
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            text = (await page.inner_text("body")).lower()
            return any(pattern in text for pattern in _DEAD_PATTERNS)
        finally:
            await page.close()
    except Exception:
        return False
