"""Adapter parsing tests against recorded fixtures — no live HTTP calls.

Each adapter's http_client is swapped for an httpx.MockTransport that
serves a canned response, so tests are fast and deterministic.
"""

import asyncio
import json
from pathlib import Path

import httpx

from adapters import ashby, jsearch, lever, linkedin, remoteok, themuse
from schema import SearchQuery

FIXTURES = Path(__file__).parent / "fixtures"


def _mock_client(payload, adapter_module, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    def fake_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(adapter_module, "http_client", fake_client)


def test_remoteok_parsing(monkeypatch):
    payload = json.loads((FIXTURES / "remoteok.json").read_text())
    _mock_client(payload, remoteok, monkeypatch)
    jobs = asyncio.run(
        remoteok.RemoteOKAdapter().search(SearchQuery(keywords=["machine learning"]))
    )
    assert len(jobs) == 1  # legal notice skipped; non-matching job filtered
    job = jobs[0]
    assert job.title == "Machine Learning Engineer"
    assert job.company == "Acme AI"
    assert job.remote == "remote"
    assert job.source == "remoteok"
    assert "<p>" not in job.description  # HTML stripped


def test_themuse_parsing(monkeypatch):
    payload = json.loads((FIXTURES / "themuse.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        # only page 1 has results, like a real one-page board
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(
        themuse, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    jobs = asyncio.run(
        themuse.TheMuseAdapter().search(SearchQuery(keywords=["machine learning"]))
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Globex"
    assert job.industry  # categories mapped to industry
    assert job.url.startswith("https://")


def test_lever_parsing_uses_structured_commitment(monkeypatch):
    payload = json.loads((FIXTURES / "lever.json").read_text())
    _mock_client(payload, lever, monkeypatch)
    jobs = asyncio.run(
        lever.LeverAdapter(companies=["acme"]).search(SearchQuery())
    )
    assert len(jobs) == 3
    by_title = {j.title: j for j in jobs}

    intern = by_title["Software Engineer Intern, Summer 2027"]
    assert intern.employment_type == "internship"  # from categories.commitment
    assert intern.remote == "hybrid"
    assert intern.industry == "Platform"

    fulltime = by_title["Senior Backend Engineer"]
    assert fulltime.employment_type == "full-time"
    assert fulltime.remote == "remote"

    # Regression: empty commitment falls back to guess_employment_type(),
    # which must NOT match "International" as a substring of "intern".
    sales = by_title["International Sales Manager"]
    assert sales.employment_type == "full-time"


def test_ashby_parsing_uses_structured_employment_type(monkeypatch):
    payload = json.loads((FIXTURES / "ashby.json").read_text())
    _mock_client(payload, ashby, monkeypatch)
    jobs = asyncio.run(
        ashby.AshbyAdapter(companies=["acme"]).search(SearchQuery())
    )
    # unlisted draft role must be excluded
    assert len(jobs) == 2
    by_title = {j.title: j for j in jobs}

    intern = by_title["Software Engineer Internship, Backend"]
    assert intern.employment_type == "internship"  # from employmentType: Intern
    assert intern.remote == "onsite"
    assert "<p>" not in intern.description  # HTML stripped

    designer = by_title["Staff Product Designer"]
    assert designer.employment_type == "full-time"
    assert designer.remote == "remote"


def _linkedin_transport(list_html: str, detail_html: str = ""):
    def handler(request: httpx.Request) -> httpx.Response:
        if "seeMoreJobPostings" in str(request.url):
            return httpx.Response(200, text=list_html)
        return httpx.Response(200, text=detail_html)
    return handler


def test_linkedin_gated_off_without_tos_acknowledgment(monkeypatch):
    # SECURITY/COMPLIANCE: the ToS-risk gate must hold even if the adapter
    # is somehow constructed and called — no ack, no request, no jobs.
    def handler(request):
        raise AssertionError("LinkedIn must never be contacted without ack")
    monkeypatch.setattr(
        linkedin, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    adapter = linkedin.LinkedInAdapter(tos_acknowledged=False)
    assert adapter.available() is False
    assert asyncio.run(adapter.search(SearchQuery(keywords=["ml"]))) == []


def test_linkedin_parsing(monkeypatch):
    list_html = (FIXTURES / "linkedin.html").read_text()
    detail_html = ('<div class="show-more-less-html__markup">'
                   "<p>Build <b>ML</b> pipelines with the team.</p></div>")
    monkeypatch.setattr(linkedin, "DETAIL_DELAY_S", 0)  # no sleep in tests
    monkeypatch.setattr(
        linkedin, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(
            _linkedin_transport(list_html, detail_html))))
    adapter = linkedin.LinkedInAdapter(employment_types=["internship"],
                                       tos_acknowledged=True)
    jobs = asyncio.run(adapter.search(SearchQuery(keywords=["ml intern"])))

    assert len(jobs) == 3
    by_title = {j.title: j for j in jobs}
    intern = by_title["ML Engineering Intern"]
    assert intern.company == "Acme AI"
    assert intern.location == "New York, NY"
    # employment_type is inferred from the title text, never assumed from
    # the f_JT request filter
    assert intern.employment_type == "internship"
    assert intern.url == "https://www.linkedin.com/jobs/view/ml-engineering-intern-at-acme-1111111111"
    assert intern.posted_at is not None
    # detail fetch filled the description, HTML stripped
    assert intern.description == "Build ML pipelines with the team."

    remote = by_title["Data Science Intern (Remote)"]
    assert remote.remote == "remote"

    # Regression: a full-time-shaped title must NOT be force-labeled
    # "internship" just because the search was filtered to f_JT=I —
    # LinkedIn's guest search doesn't strictly enforce that filter, and
    # this exact case (real posting: "Machine Learning Engineer" @ Intel)
    # was leaking through mislabeled as an internship.
    fulltime = by_title["Machine Learning Engineer"]
    assert fulltime.employment_type != "internship"


def test_linkedin_backs_off_on_rate_limit(monkeypatch):
    detail_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "seeMoreJobPostings" in str(request.url):
            return httpx.Response(200,
                                  text=(FIXTURES / "linkedin.html").read_text())
        detail_calls.append(str(request.url))
        return httpx.Response(429)

    monkeypatch.setattr(linkedin, "DETAIL_DELAY_S", 0)
    monkeypatch.setattr(
        linkedin, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    adapter = linkedin.LinkedInAdapter(tos_acknowledged=True)
    jobs = asyncio.run(adapter.search(SearchQuery(keywords=["ml"])))

    # first 429 stops ALL further detail fetches for the run...
    assert len(detail_calls) == 1
    # ...but the jobs already parsed from the list are still returned
    assert len(jobs) == 3
    assert all(j.description == "" for j in jobs)


def test_jsearch_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    adapter = jsearch.JSearchAdapter()
    assert adapter.available() is False
    assert asyncio.run(adapter.search(SearchQuery(keywords=["ml"]))) == []


def test_jsearch_parsing(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-key")
    payload = json.loads((FIXTURES / "jsearch.json").read_text())
    _mock_client(payload, jsearch, monkeypatch)
    adapter = jsearch.JSearchAdapter(employment_types=["internship"])
    jobs = asyncio.run(adapter.search(SearchQuery(keywords=["ml intern"])))

    assert len(jobs) == 4  # entry with no apply link (and no options) skipped
    by_title = {j.title: j for j in jobs}

    intern = by_title["Machine Learning Intern"]
    assert intern.employment_type == "internship"  # INTERN mapped
    assert intern.company == "Acme AI"
    assert intern.location == "Boston, MA, US"
    assert intern.publisher == "Indeed"  # origin board captured
    assert "<p>" not in intern.description  # HTML stripped
    # HOURLY salary must NOT populate salary fields — $40/hr would falsely
    # trip the yearly salary-floor filter
    assert intern.salary_min is None and intern.salary_max is None

    senior = by_title["Senior Data Engineer"]
    assert senior.employment_type == "full-time"
    assert senior.remote == "remote"
    assert senior.publisher == "Glassdoor"  # Glassdoor listing stays labeled
    assert senior.salary_max == 190000  # YEAR salary kept

    # apply_options: a Glassdoor option is preferred over the primary
    # LinkedIn link, so Glassdoor postings surface with a Glassdoor URL
    backend = by_title["Backend Engineer"]
    assert backend.publisher == "Glassdoor"
    assert backend.url == "https://www.glassdoor.com/apply/d4"

    # ...and Indeed gets the same treatment: its direct apply option wins
    # over the primary LinkedIn link
    qa = by_title["QA Engineer"]
    assert qa.publisher == "Indeed"
    assert qa.url == "https://www.indeed.com/viewjob?jk=e5"


def test_adapter_returns_empty_on_http_error(monkeypatch):
    def handler(request):
        return httpx.Response(500)

    monkeypatch.setattr(
        remoteok, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    jobs = asyncio.run(remoteok.RemoteOKAdapter().search(SearchQuery()))
    assert jobs == []  # one dead board never kills the search
