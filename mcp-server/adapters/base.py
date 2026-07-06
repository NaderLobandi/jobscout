"""Abstract adapter interface for job sources.

COURSE CONCEPT (tool design / NxM problem): every board plugs in behind
this one interface. Adding a source = one new file implementing `search()`.
The MCP server (and therefore the agent) never changes.

SECURITY (least privilege): adapters perform GET requests only. There is
no code path that can write to any job platform.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schema import Job, SearchQuery  # noqa: E402

USER_AGENT = "JobScout/1.0 (personal job-search agent; educational project)"


class JobSourceAdapter(ABC):
    name: str = "base"
    requires_key: bool = False

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[Job]:
        """Return normalized jobs for the query. Must never raise on HTTP
        errors — return [] so one dead board can't kill the whole search."""

    def available(self) -> bool:
        """Tier B adapters override this to check their env vars."""
        return True


def http_client() -> httpx.AsyncClient:
    """Shared client config: identify ourselves, fail fast, follow redirects."""
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=15.0,
        follow_redirects=True,
    )


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """Client-side keyword filter for boards without a search parameter.
    Empty keyword list matches everything. Case-insensitive; a job matches
    if ANY keyword's significant words all appear in the text."""
    if not keywords:
        return True
    t = text.lower()
    for kw in keywords:
        words = [w for w in kw.lower().split() if len(w) > 2]
        if words and all(w in t for w in words):
            return True
    return False
