"""Greenhouse adapter — per-company public job boards.

https://boards-api.greenhouse.io/v1/boards/{company_token}/jobs?content=true

No key needed. Company tokens come from the user's profile
(sources.greenhouse_companies) — this lets the user watch specific
companies they care about (e.g. anthropic, stripe).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from .base import JobSourceAdapter, http_client, matches_keywords
from schema import Job, SearchQuery, guess_employment_type, make_job_id, strip_html

API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseAdapter(JobSourceAdapter):
    name = "greenhouse"
    requires_key = False

    def __init__(self, companies: list[str] | None = None):
        self.companies = companies or []

    def available(self) -> bool:
        return bool(self.companies)

    async def search(self, query: SearchQuery) -> list[Job]:
        boards = await asyncio.gather(
            *(self._fetch_board(token, query) for token in self.companies)
        )
        jobs = [job for board in boards for job in board]
        return jobs[: query.limit_per_source]

    async def _fetch_board(self, token: str, query: SearchQuery) -> list[Job]:
        try:
            async with http_client() as client:
                resp = await client.get(
                    API_URL.format(token=token), params={"content": "true"}
                )
                resp.raise_for_status()
                data = resp.json().get("jobs", [])
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data:
            title = item.get("title", "")
            description = strip_html(item.get("content", ""))
            if not matches_keywords(f"{title} {description}", query.keywords):
                continue
            location = (item.get("location") or {}).get("name", "")
            remote = "remote" if "remote" in location.lower() else "unknown"
            if query.remote_only and remote != "remote":
                continue
            posted_at = None
            if item.get("updated_at"):
                try:
                    posted_at = datetime.fromisoformat(
                        item["updated_at"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    pass
            url = item.get("absolute_url", "")
            if not url:
                continue
            jobs.append(
                Job(
                    id=make_job_id(url, title, token),
                    title=title,
                    company=token.capitalize(),
                    employment_type=guess_employment_type(f"{title} {description}"),
                    location=location,
                    remote=remote,
                    description=description[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
        return jobs
