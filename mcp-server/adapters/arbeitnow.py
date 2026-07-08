"""Arbeitnow adapter — https://www.arbeitnow.com/api/job-board-api

Public JSON API, no key. Tech jobs, EU-heavy. No search parameter,
so keywords are filtered client-side.
"""

from __future__ import annotations

from datetime import datetime

from .base import JobSourceAdapter, http_client, matches_keywords
from schema import Job, SearchQuery, guess_employment_type, make_job_id, strip_html

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowAdapter(JobSourceAdapter):
    name = "arbeitnow"
    requires_key = False

    async def search(self, query: SearchQuery) -> list[Job]:
        if query.page > 1:
            return []  # whole inventory came on round 1; nothing deeper exists
        try:
            async with http_client() as client:
                resp = await client.get(API_URL)
                resp.raise_for_status()
                data = resp.json().get("data", [])
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data:
            title = item.get("title", "")
            company = item.get("company_name", "")
            description = strip_html(item.get("description", ""))
            tags = " ".join(item.get("tags") or [])
            types = " ".join(item.get("job_types") or [])
            # Relevance matching uses title + tags/types only — free-text
            # descriptions are prose, not a reliable relevance signal.
            if not matches_keywords(f"{title} {tags} {types}", query.keywords):
                continue
            is_remote = bool(item.get("remote"))
            if query.remote_only and not is_remote:
                continue
            posted_at = None
            if item.get("created_at"):
                try:
                    posted_at = datetime.fromtimestamp(int(item["created_at"]))
                except (ValueError, OSError):
                    pass
            url = item.get("url", "")
            if not url:
                continue
            jobs.append(
                Job(
                    id=make_job_id(url, title, company),
                    title=title,
                    company=company,
                    employment_type=guess_employment_type(f"{types} {title}"),
                    location=item.get("location", ""),
                    remote="remote" if is_remote else "onsite",
                    description=description[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
            if len(jobs) >= query.limit_per_source:
                break
        return jobs
