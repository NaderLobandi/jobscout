"""Remotive adapter — https://remotive.com/api/remote-jobs

Public JSON API, no key, supports a server-side `search` parameter.
Remote jobs only.
"""

from __future__ import annotations

from datetime import datetime

from .base import JobSourceAdapter, http_client, matches_keywords
from schema import Job, SearchQuery, make_job_id, strip_html

API_URL = "https://remotive.com/api/remote-jobs"

_TYPE_MAP = {
    "full_time": "full-time",
    "part_time": "part-time",
    "internship": "internship",
    "contract": "contract",
    "freelance": "contract",
}


class RemotiveAdapter(JobSourceAdapter):
    name = "remotive"
    requires_key = False

    async def search(self, query: SearchQuery) -> list[Job]:
        # Remotive supports one search string; use the first keyword server-side
        # and filter the rest client-side.
        params: dict = {"limit": query.limit_per_source * 2}
        if query.keywords:
            params["search"] = query.keywords[0]
        try:
            async with http_client() as client:
                resp = await client.get(API_URL, params=params)
                resp.raise_for_status()
                data = resp.json().get("jobs", [])
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data:
            title = item.get("title", "")
            company = item.get("company_name", "")
            description = strip_html(item.get("description", ""))
            # Relevance matching uses title + category only — free-text
            # descriptions are prose, not a reliable relevance signal.
            if not matches_keywords(f"{title} {item.get('category', '')}",
                                    query.keywords):
                continue
            posted_at = None
            if item.get("publication_date"):
                try:
                    posted_at = datetime.fromisoformat(item["publication_date"])
                except ValueError:
                    pass
            url = item.get("url", "")
            if not url:
                continue
            jobs.append(
                Job(
                    id=make_job_id(url, title, company),
                    title=title,
                    company=company,
                    employment_type=_TYPE_MAP.get(item.get("job_type", ""), "unknown"),
                    location=item.get("candidate_required_location") or "Remote",
                    remote="remote",
                    industry=item.get("category") or None,
                    description=description[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
            if len(jobs) >= query.limit_per_source:
                break
        return jobs
