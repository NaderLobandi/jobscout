"""Ashby adapter — per-company public job boards.

https://api.ashbyhq.com/posting-api/job-board/{organization_name}

No key needed. Company tokens come from the user's profile
(sources.ashby_companies). Ashby is the dominant ATS among recent
YC-batch startups; like Lever, its postings carry a structured
`employmentType` field ("Intern", "FullTime", "PartTime", "Contract",
"Temporary") so internships are detected exactly, not sniffed from text.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from .base import JobSourceAdapter, http_client, matches_keywords
from schema import Job, SearchQuery, guess_employment_type, make_job_id, strip_html

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"

_EMPLOYMENT_TYPE_MAP = {
    "intern": "internship",
    "fulltime": "full-time",
    "parttime": "part-time",
    "contract": "contract",
    "temporary": "contract",
}


class AshbyAdapter(JobSourceAdapter):
    name = "ashby"
    requires_key = False

    def __init__(self, companies: list[str] | None = None):
        self.companies = companies or []

    def available(self) -> bool:
        return bool(self.companies)

    async def search(self, query: SearchQuery) -> list[Job]:
        if query.page > 1:
            return []  # whole inventory came on round 1; nothing deeper exists
        boards = await asyncio.gather(
            *(self._fetch_board(org, query) for org in self.companies)
        )
        jobs = [job for board in boards for job in board]
        return jobs[: query.limit_per_source]

    async def _fetch_board(self, org: str, query: SearchQuery) -> list[Job]:
        try:
            async with http_client() as client:
                resp = await client.get(API_URL.format(org=org))
                resp.raise_for_status()
                data = resp.json().get("jobs", [])
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data:
            if not item.get("isListed", True):
                continue
            title = item.get("title", "")
            description = strip_html(item.get("descriptionHtml", ""))
            if not matches_keywords(f"{title} {description}", query.keywords):
                continue
            location = item.get("location", "") or ""
            workplace_type = (item.get("workplaceType") or "").lower()
            remote = "remote" if item.get("isRemote") or workplace_type == "remote" else (
                "hybrid" if workplace_type == "hybrid" else (
                    "onsite" if workplace_type == "onsite" else "unknown"))
            if query.remote_only and remote != "remote":
                continue
            raw_type = (item.get("employmentType") or "").strip().lower()
            employment_type = (_EMPLOYMENT_TYPE_MAP.get(raw_type)
                              or guess_employment_type(f"{title} {description}"))
            posted_at = None
            if item.get("publishedAt"):
                try:
                    posted_at = datetime.fromisoformat(
                        item["publishedAt"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    pass
            url = item.get("jobUrl", "")
            if not url:
                continue
            jobs.append(
                Job(
                    id=make_job_id(url, title, org),
                    title=title,
                    company=org.capitalize(),
                    employment_type=employment_type,
                    location=location,
                    remote=remote,
                    industry=item.get("department") or None,
                    description=description[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
        return jobs
