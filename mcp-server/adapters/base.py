"""Abstract adapter interface for job sources.

COURSE CONCEPT (tool design / NxM problem): every board plugs in behind
this one interface. Adding a source = one new file implementing `search()`.
The MCP server (and therefore the agent) never changes.

SECURITY (least privilege): adapters perform GET requests only. There is
no code path that can write to any job platform.
"""

from __future__ import annotations

import re
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


def rotation_keyword(query: SearchQuery) -> str | None:
    """The ONE query string for this search round, for boards whose API
    takes a single free-text query (LinkedIn, JSearch, Adzuna, USAJOBS).

    Round N uses keywords[N-1]: a fresh query pulls different inventory
    than page 2 of an already-starved query, which is the whole point of
    outcome-driven deepening. Returns None once the keyword list is
    exhausted — the adapter has nothing new left to ask for and must
    return [] rather than re-fetch a duplicate result set."""
    if query.page <= 1:
        return query.keywords[0] if query.keywords else ""
    if query.page - 1 < len(query.keywords):
        return query.keywords[query.page - 1]
    return None


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """Client-side keyword filter for boards without a search parameter.
    Empty keyword list matches everything. A job matches if ANY keyword
    phrase appears as a WHOLE WORD/PHRASE (case-insensitive) in the text.

    Deliberately a literal phrase check, not bag-of-words: matching each
    word of a multi-word phrase independently ANYWHERE in a long job
    description produces false positives (e.g. a Marketing role whose
    boilerplate separately mentions "research" and "engineering" would
    satisfy a "Research Engineer" keyword under bag-of-words matching even
    though the actual role is unrelated). Same discipline as
    violates_dealbreakers() in guardrails.py.

    Word-boundary anchored (not raw substring): short expanded keywords
    like "ml"/"ai"/"nlp" (see src/query_expansion.py) must match the WORD
    "AI", not the "ai" inside "training"/"maintain"/"retail". The anchor is
    dropped on a side whose keyword edge isn't alphanumeric (e.g. "c++",
    ".net") so those still match."""
    if not keywords:
        return True
    t = text.lower()
    for kw in keywords:
        kw = kw.strip().lower()
        if not kw:
            continue
        left = r"\b" if kw[0].isalnum() else ""
        right = r"\b" if kw[-1].isalnum() else ""
        if re.search(left + re.escape(kw) + right, t):
            return True
    return False
