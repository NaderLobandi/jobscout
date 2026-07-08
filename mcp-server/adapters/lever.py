"""Lever adapter — per-company public job boards.

https://api.lever.co/v0/postings/{company_token}?mode=json

No key needed. Company tokens come from the user's profile
(sources.lever_companies). Lever is heavily used by startups (including
many YC-backed companies), and — unlike free-text employment-type
guessing — its postings carry a structured `categories.commitment` field
("Internship", "Full-time", "Contractor", ...), so internships are
detected exactly instead of sniffed from the title/description.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from .base import JobSourceAdapter, http_client, matches_keywords
from schema import Job, SearchQuery, guess_employment_type, make_job_id

API_URL = "https://api.lever.co/v0/postings/{token}"

_COMMITMENT_MAP = {
    "internship": "internship",
    "intern": "internship",
    "full-time": "full-time",
    "full time": "full-time",
    "part-time": "part-time",
    "part time": "part-time",
    "contractor": "contract",
    "contract": "contract",
    "freelance": "contract",
    "temporary": "contract",
    "fixed-term": "contract",
}


class LeverAdapter(JobSourceAdapter):
    name = "lever"
    requires_key = False

    def __init__(self, companies: list[str] | None = None):
        self.companies = companies or []

    def available(self) -> bool:
        return bool(self.companies)

    async def search(self, query: SearchQuery) -> list[Job]:
        if query.page > 1:
            return []  # whole inventory came on round 1; nothing deeper exists
        boards = await asyncio.gather(
            *(self._fetch_board(token, query) for token in self.companies)
        )
        jobs = [job for board in boards for job in board]
        return jobs[: query.limit_per_source]

    async def _fetch_board(self, token: str, query: SearchQuery) -> list[Job]:
        try:
            async with http_client() as client:
                resp = await client.get(
                    API_URL.format(token=token), params={"mode": "json"}
                )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    return []
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data:
            title = item.get("text", "")
            description = item.get("descriptionPlain", "") or ""
            if not matches_keywords(f"{title} {description}", query.keywords):
                continue
            categories = item.get("categories") or {}
            location = categories.get("location", "") or ""
            workplace_type = (item.get("workplaceType") or "").lower()
            remote = "remote" if workplace_type == "remote" else (
                "hybrid" if workplace_type == "hybrid" else (
                    "onsite" if workplace_type == "onsite" else "unknown"))
            if query.remote_only and remote != "remote":
                continue
            commitment = (categories.get("commitment") or "").strip().lower()
            employment_type = (_COMMITMENT_MAP.get(commitment)
                              or guess_employment_type(f"{title} {description}"))
            posted_at = None
            if item.get("createdAt"):
                try:
                    posted_at = datetime.fromtimestamp(item["createdAt"] / 1000)
                except (ValueError, OSError, OverflowError):
                    pass
            url = item.get("hostedUrl", "")
            if not url:
                continue
            jobs.append(
                Job(
                    id=make_job_id(url, title, token),
                    title=title,
                    company=token.capitalize(),
                    employment_type=employment_type,
                    location=location,
                    remote=remote,
                    industry=categories.get("team") or None,
                    description=description[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
        return jobs
