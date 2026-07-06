"""Adzuna adapter (Tier B) — https://developer.adzuna.com/

Broad coverage + real salary data. Requires free ADZUNA_APP_ID /
ADZUNA_APP_KEY env vars; the adapter reports itself unavailable without
them, so JobScout runs fine keyless.

SECURITY: credentials come from the environment only — never hardcoded.
"""

from __future__ import annotations

import os
from datetime import datetime

from .base import JobSourceAdapter, http_client
from schema import Job, SearchQuery, make_job_id, strip_html

API_URL = "https://api.adzuna.com/v1/api/jobs/us/search/1"


class AdzunaAdapter(JobSourceAdapter):
    name = "adzuna"
    requires_key = True

    def available(self) -> bool:
        return bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY"))

    async def search(self, query: SearchQuery) -> list[Job]:
        if not self.available():
            return []
        params = {
            "app_id": os.environ["ADZUNA_APP_ID"],
            "app_key": os.environ["ADZUNA_APP_KEY"],
            "results_per_page": query.limit_per_source,
            "what": " ".join(query.keywords[:1]) or "software engineer",
        }
        if query.locations:
            params["where"] = query.locations[0]
        try:
            async with http_client() as client:
                resp = await client.get(API_URL, params=params)
                resp.raise_for_status()
                data = resp.json().get("results", [])
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data:
            url = item.get("redirect_url", "")
            title = item.get("title", "")
            company = (item.get("company") or {}).get("display_name", "")
            if not url:
                continue
            posted_at = None
            if item.get("created"):
                try:
                    posted_at = datetime.fromisoformat(
                        item["created"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    pass
            contract_time = item.get("contract_time") or ""
            jobs.append(
                Job(
                    id=make_job_id(url, title, company),
                    title=strip_html(title),
                    company=company,
                    employment_type={"full_time": "full-time",
                                     "part_time": "part-time"}.get(contract_time, "unknown"),
                    location=(item.get("location") or {}).get("display_name", ""),
                    salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
                    salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
                    description=strip_html(item.get("description", ""))[:4000],
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
        return jobs
