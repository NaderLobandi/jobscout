"""RemoteOK adapter — https://remoteok.com/api

Single public JSON endpoint, no key. Remote tech jobs. Requires a
User-Agent header (403 without one). First array element is a legal
notice, not a job.
"""

from __future__ import annotations

from datetime import datetime

from .base import JobSourceAdapter, http_client, matches_keywords
from schema import Job, SearchQuery, guess_employment_type, make_job_id, strip_html

API_URL = "https://remoteok.com/api"


class RemoteOKAdapter(JobSourceAdapter):
    name = "remoteok"
    requires_key = False

    async def search(self, query: SearchQuery) -> list[Job]:
        try:
            async with http_client() as client:
                resp = await client.get(API_URL)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []  # one dead board must not kill the whole search

        jobs: list[Job] = []
        for item in data:
            if not isinstance(item, dict) or "position" not in item:
                continue  # skips the legal-notice header element
            title = item.get("position", "")
            company = item.get("company", "")
            description = strip_html(item.get("description", ""))
            tags = " ".join(item.get("tags") or [])
            haystack = f"{title} {tags} {description}"
            if not matches_keywords(haystack, query.keywords):
                continue

            posted_at = None
            if item.get("epoch"):
                try:
                    posted_at = datetime.fromtimestamp(int(item["epoch"]))
                except (ValueError, OSError):
                    pass

            url = item.get("url") or f"https://remoteok.com/l/{item.get('id', '')}"
            jobs.append(
                Job(
                    id=make_job_id(url, title, company),
                    title=title,
                    company=company,
                    employment_type=guess_employment_type(haystack) or "unknown",
                    location=item.get("location") or "Remote",
                    remote="remote",  # RemoteOK is remote-only by definition
                    salary_min=item.get("salary_min") or None,
                    salary_max=item.get("salary_max") or None,
                    description=description[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
            if len(jobs) >= query.limit_per_source:
                break
        return jobs
