"""Deterministic tests for Playwright liveness verification, using fakes
for Playwright's async API — no real browser needed to run this suite,
consistent with the feature being an optional dependency.

Spec: specs/technical_design.md §2 step 3c; CLAUDE.md constraint 4
exception (opt-in, fails open).
"""

import asyncio

from src import liveness

JOBS = [{"url": "https://x.example/1"}, {"url": "https://x.example/2"},
       {"url": "https://x.example/3"}]


class _FakePage:
    def __init__(self, text=None, goto_error=None):
        self._text = text or ""
        self._goto_error = goto_error
        self.closed = False

    async def goto(self, url, timeout=None, wait_until=None):
        if self._goto_error:
            raise self._goto_error

    async def inner_text(self, selector):
        return self._text

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, pages):
        self._pages = list(pages)
        self._i = 0
        self.closed = False

    async def new_page(self):
        page = self._pages[self._i]
        self._i += 1
        return page

    async def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser=None, launch_error=None):
        self._browser = browser
        self._launch_error = launch_error

    async def launch(self):
        if self._launch_error:
            raise self._launch_error
        return self._browser


class _FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium


class _FakePlaywrightContext:
    def __init__(self, chromium):
        self._chromium = chromium

    async def __aenter__(self):
        return _FakePlaywright(self._chromium)

    async def __aexit__(self, *exc_info):
        return False


def _fake_async_playwright(chromium):
    return lambda: _FakePlaywrightContext(chromium)


def test_missing_playwright_is_a_noop(monkeypatch):
    def raise_import_error():
        raise ImportError("no module named playwright")
    monkeypatch.setattr(liveness, "_import_async_playwright", raise_import_error)

    live, dead_count = asyncio.run(liveness.filter_dead_postings(JOBS))
    assert live == JOBS
    assert dead_count == 0


def test_browser_launch_failure_fails_open(monkeypatch):
    chromium = _FakeChromium(launch_error=RuntimeError("no chromium binary"))
    monkeypatch.setattr(liveness, "_import_async_playwright",
                        lambda: _fake_async_playwright(chromium))

    live, dead_count = asyncio.run(liveness.filter_dead_postings(JOBS))
    assert live == JOBS
    assert dead_count == 0


def test_dead_posting_detected_and_dropped(monkeypatch):
    pages = [_FakePage(text="This position has been filled. Thanks for your interest.")]
    browser = _FakeBrowser(pages)
    chromium = _FakeChromium(browser=browser)
    monkeypatch.setattr(liveness, "_import_async_playwright",
                        lambda: _fake_async_playwright(chromium))

    live, dead_count = asyncio.run(liveness.filter_dead_postings(JOBS[:1]))
    assert live == []
    assert dead_count == 1
    assert browser.closed


def test_live_posting_is_kept(monkeypatch):
    pages = [_FakePage(text="Full job description here. Apply now!")]
    browser = _FakeBrowser(pages)
    chromium = _FakeChromium(browser=browser)
    monkeypatch.setattr(liveness, "_import_async_playwright",
                        lambda: _fake_async_playwright(chromium))

    live, dead_count = asyncio.run(liveness.filter_dead_postings(JOBS[:1]))
    assert live == JOBS[:1]
    assert dead_count == 0


def test_mixed_batch_preserves_order_of_survivors(monkeypatch):
    pages = [
        _FakePage(text="Apply now, great role!"),                       # live
        _FakePage(text="Sorry, this posting has expired."),             # dead
        _FakePage(text="Still hiring, apply today."),                   # live
    ]
    browser = _FakeBrowser(pages)
    chromium = _FakeChromium(browser=browser)
    monkeypatch.setattr(liveness, "_import_async_playwright",
                        lambda: _fake_async_playwright(chromium))

    live, dead_count = asyncio.run(liveness.filter_dead_postings(JOBS))
    assert live == [JOBS[0], JOBS[2]]
    assert dead_count == 1


def test_page_error_fails_open_not_dropped(monkeypatch):
    pages = [_FakePage(goto_error=TimeoutError("navigation timeout"))]
    browser = _FakeBrowser(pages)
    chromium = _FakeChromium(browser=browser)
    monkeypatch.setattr(liveness, "_import_async_playwright",
                        lambda: _fake_async_playwright(chromium))

    live, dead_count = asyncio.run(liveness.filter_dead_postings(JOBS[:1]))
    assert live == JOBS[:1]  # couldn't verify -> assume live
    assert dead_count == 0


def test_pattern_matching_is_case_insensitive(monkeypatch):
    pages = [_FakePage(text="THIS POSITION HAS BEEN FILLED.")]
    browser = _FakeBrowser(pages)
    chromium = _FakeChromium(browser=browser)
    monkeypatch.setattr(liveness, "_import_async_playwright",
                        lambda: _fake_async_playwright(chromium))

    live, dead_count = asyncio.run(liveness.filter_dead_postings(JOBS[:1]))
    assert dead_count == 1


def test_empty_job_list(monkeypatch):
    browser = _FakeBrowser([])
    chromium = _FakeChromium(browser=browser)
    monkeypatch.setattr(liveness, "_import_async_playwright",
                        lambda: _fake_async_playwright(chromium))

    live, dead_count = asyncio.run(liveness.filter_dead_postings([]))
    assert live == []
    assert dead_count == 0
