"""The Muse adapter — https://www.themuse.com/api/public/jobs?page=N

Public JSON API, no key. Broad US coverage with industry and seniority
tags. No keyword parameter, so we filter client-side.
"""

from __future__ import annotations

from datetime import datetime

from .base import JobSourceAdapter, http_client, matches_keywords
from schema import Job, SearchQuery, guess_employment_type, make_job_id, strip_html

API_URL = "https://www.themuse.com/api/public/jobs"
MAX_PAGES = 3  # 20 results/page; enough coverage without hammering the API

# Muse "levels" → our seniority-ish signal lives in description; map to type
_REMOTE_HINTS = ("remote", "flexible")


class TheMuseAdapter(JobSourceAdapter):
    name = "themuse"
    requires_key = False

    async def search(self, query: SearchQuery) -> list[Job]:
        jobs: list[Job] = []
        try:
            async with http_client() as client:
                for page in range(1, MAX_PAGES + 1):
                    resp = await client.get(API_URL, params={"page": page})
                    resp.raise_for_status()
                    results = resp.json().get("results", [])
                    if not results:
                        break
                    for item in results:
                        job = self._parse(item, query)
                        if job:
                            jobs.append(job)
                        if len(jobs) >= query.limit_per_source:
                            return jobs
        except Exception:
            pass  # partial results beat a crashed search
        return jobs

    def _parse(self, item: dict, query: SearchQuery) -> Job | None:
        title = item.get("name", "")
        company = (item.get("company") or {}).get("name", "")
        description = strip_html(item.get("contents", ""))
        categories = " ".join(c.get("name", "") for c in item.get("categories", []))
        haystack = f"{title} {categories} {description}"
        if not matches_keywords(haystack, query.keywords):
            return None

        locations = [l.get("name", "") for l in item.get("locations", [])]
        loc_text = ", ".join(locations)
        remote = "remote" if any(h in loc_text.lower() for h in _REMOTE_HINTS) else "onsite"
        if query.remote_only and remote != "remote":
            return None

        posted_at = None
        if item.get("publication_date"):
            try:
                posted_at = datetime.fromisoformat(
                    item["publication_date"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass

        url = (item.get("refs") or {}).get("landing_page", "")
        if not url:
            return None
        return Job(
            id=make_job_id(url, title, company),
            title=title,
            company=company,
            employment_type=guess_employment_type(f"{title} {description}"),
            location=loc_text,
            remote=remote,
            industry=categories or None,
            description=description[:4000],
            url=url,
            source=self.name,
            posted_at=posted_at,
        )
