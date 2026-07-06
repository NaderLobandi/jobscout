"""Normalized data models shared by every job-source adapter.

COURSE CONCEPT (MCP / NxM problem): each job board has its own response
shape. Adapters normalize everything into this single Job model, so the
agent integrates with ONE schema instead of N board formats x M consumers.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from pydantic import BaseModel, Field

EMPLOYMENT_TYPES = ("full-time", "part-time", "internship", "contract", "unknown")
REMOTE_TYPES = ("onsite", "hybrid", "remote", "unknown")


class Job(BaseModel):
    """One job posting, normalized across all sources."""

    id: str
    title: str
    company: str
    employment_type: str = "unknown"
    location: str = ""
    remote: str = "unknown"
    industry: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    description: str = ""
    url: str
    source: str
    posted_at: datetime | None = None


class SearchQuery(BaseModel):
    """What the agent asks the MCP server for, built from profile prefs."""

    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_only: bool = False
    limit_per_source: int = 25


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Job boards return HTML descriptions; agents want plain text."""
    text = _TAG_RE.sub(" ", text or "")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return _WS_RE.sub(" ", text).strip()


def make_job_id(url: str, title: str = "", company: str = "") -> str:
    """Stable job id: hash of the canonical URL (fallback: title+company)."""
    basis = url.split("?")[0].rstrip("/").lower() or f"{title}|{company}".lower()
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def dedupe(jobs: list[Job]) -> list[Job]:
    """Merge duplicates across sources: first by id (URL hash), then by a
    normalized (title, company) key — the same role posted on two boards
    collapses to one record. Deterministic code, not LLM judgment."""
    seen_ids: set[str] = set()
    seen_tc: set[tuple[str, str]] = set()
    out: list[Job] = []
    for job in jobs:
        tc = (job.title.strip().lower(), job.company.strip().lower())
        if job.id in seen_ids or tc in seen_tc:
            continue
        seen_ids.add(job.id)
        seen_tc.add(tc)
        out.append(job)
    return out


def guess_employment_type(text: str) -> str:
    """Best-effort employment-type inference from free text."""
    t = (text or "").lower()
    if "intern" in t:
        return "internship"
    if "part-time" in t or "part time" in t:
        return "part-time"
    if "contract" in t or "freelance" in t:
        return "contract"
    if "full-time" in t or "full time" in t or "full_time" in t:
        return "full-time"
    return "unknown"
