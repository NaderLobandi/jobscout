"""USAJOBS adapter (Tier B) — https://developer.usajobs.gov/

US federal jobs with excellent structured data. Requires free
USAJOBS_API_KEY + USAJOBS_USER_AGENT (your email) env vars; reports
itself unavailable without them.

SECURITY: credentials come from the environment only — never hardcoded.
"""

from __future__ import annotations

import os
from datetime import datetime

import httpx

from .base import JobSourceAdapter, rotation_keyword
from schema import Job, SearchQuery, make_job_id, strip_html

API_URL = "https://data.usajobs.gov/api/search"


class USAJobsAdapter(JobSourceAdapter):
    name = "usajobs"
    requires_key = True

    def available(self) -> bool:
        return bool(os.getenv("USAJOBS_API_KEY") and os.getenv("USAJOBS_USER_AGENT"))

    async def search(self, query: SearchQuery) -> list[Job]:
        if not self.available():
            return []
        headers = {
            "Authorization-Key": os.environ["USAJOBS_API_KEY"],
            "User-Agent": os.environ["USAJOBS_USER_AGENT"],
        }
        # Deeper rounds rotate to the next keyword — fresh inventory
        # instead of re-fetching the same starved query.
        kw = rotation_keyword(query)
        if kw is None:
            return []  # keyword rotation exhausted
        params = {
            "Keyword": kw,
            "ResultsPerPage": query.limit_per_source,
        }
        if query.locations:
            params["LocationName"] = query.locations[0]
        try:
            async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
                resp = await client.get(API_URL, params=params)
                resp.raise_for_status()
                items = (resp.json().get("SearchResult") or {}).get("SearchResultItems", [])
        except Exception:
            return []

        jobs: list[Job] = []
        for wrapper in items:
            d = wrapper.get("MatchedObjectDescriptor", {})
            url = d.get("PositionURI", "")
            title = d.get("PositionTitle", "")
            company = d.get("OrganizationName", "")
            if not url:
                continue
            salary_min = salary_max = None
            for pay in d.get("PositionRemuneration", []):
                if pay.get("RateIntervalCode") in ("PA", "Per Year"):
                    try:
                        salary_min = int(float(pay.get("MinimumRange", 0))) or None
                        salary_max = int(float(pay.get("MaximumRange", 0))) or None
                    except ValueError:
                        pass
            posted_at = None
            if d.get("PublicationStartDate"):
                try:
                    posted_at = datetime.fromisoformat(d["PublicationStartDate"])
                except ValueError:
                    pass
            summary = (d.get("UserArea", {}).get("Details", {}) or {}).get("JobSummary", "")
            jobs.append(
                Job(
                    id=make_job_id(url, title, company),
                    title=title,
                    company=company,
                    employment_type="full-time",
                    location=d.get("PositionLocationDisplay", ""),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    description=strip_html(summary)[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
        return jobs
