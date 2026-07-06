"""Adapter parsing tests against recorded fixtures — no live HTTP calls.

Each adapter's http_client is swapped for an httpx.MockTransport that
serves a canned response, so tests are fast and deterministic.
"""

import asyncio
import json
from pathlib import Path

import httpx

from adapters import remoteok, themuse
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


def test_adapter_returns_empty_on_http_error(monkeypatch):
    def handler(request):
        return httpx.Response(500)

    monkeypatch.setattr(
        remoteok, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    jobs = asyncio.run(remoteok.RemoteOKAdapter().search(SearchQuery()))
    assert jobs == []  # one dead board never kills the search
