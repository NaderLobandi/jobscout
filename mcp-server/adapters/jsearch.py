"""JSearch adapter (Tier B) — Google for Jobs aggregation via RapidAPI.

https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch (free tier:
200 requests/month, no card). Requires JSEARCH_API_KEY env var; reports
itself unavailable without it, so JobScout runs fine keyless.

WHY THIS EXISTS instead of Indeed/Glassdoor adapters: both sites sit
behind active anti-bot walls (HTTP 403 + Cloudflare CAPTCHA even for a
logged-out browser — verified 2026-07). Defeating a CAPTCHA is active
countermeasure evasion, categorically different from LinkedIn's open
guest endpoint, and out of scope no matter the opt-in. Google for Jobs
legitimately indexes Indeed's and Glassdoor's postings, and JSearch
exposes that index as a keyed JSON API — so their listings arrive here
through the front door, with `job_publisher` telling you which board
each one came from.

SECURITY: credentials come from the environment only — never hardcoded.
"""

from __future__ import annotations

import os
from datetime import datetime

from .base import JobSourceAdapter, http_client
from schema import Job, SearchQuery, guess_employment_type, make_job_id, strip_html

API_URL = "https://jsearch.p.rapidapi.com/search"

# profile employment_types -> JSearch's employment_types filter codes
_EMPLOYMENT_PARAM = {"full-time": "FULLTIME", "part-time": "PARTTIME",
                     "internship": "INTERN", "contract": "CONTRACTOR"}
# JSearch's job_employment_type values -> normalized schema values
_EMPLOYMENT_MAP = {"fulltime": "full-time", "parttime": "part-time",
                   "intern": "internship", "contractor": "contract"}

# Boards we specifically want to surface: when a posting lists apply
# options across several boards, prefer one of these (direct link first)
# so its listing appears with that board's URL and publisher label. This
# is display/apply-link preference only — no job is filtered by it.
_SURFACE_PUBLISHERS = ("glassdoor", "indeed")


def _preferred_option(options: list[dict]) -> dict | None:
    for board in _SURFACE_PUBLISHERS:
        matches = [o for o in options
                   if board in (o.get("publisher") or "").lower()]
        if matches:
            return next((o for o in matches if o.get("is_direct")), matches[0])
    return None


class JSearchAdapter(JobSourceAdapter):
    name = "jsearch"
    requires_key = True

    def __init__(self, employment_types: list[str] | None = None):
        self.employment_types = employment_types or []

    def available(self) -> bool:
        return bool(os.getenv("JSEARCH_API_KEY"))

    async def search(self, query: SearchQuery) -> list[Job]:
        if not self.available():
            return []
        # JSearch takes one natural-language query; num_pages=1 keeps each
        # run to a single request against the 200/month free budget.
        q = query.keywords[0] if query.keywords else "software engineer"
        if query.locations:
            q = f"{q} in {query.locations[0]}"
        params: dict[str, str] = {"query": q, "page": "1", "num_pages": "1"}
        if query.remote_only:
            params["work_from_home"] = "true"
        types = ",".join(_EMPLOYMENT_PARAM[t] for t in self.employment_types
                         if t in _EMPLOYMENT_PARAM)
        if types:
            params["employment_types"] = types
        headers = {"x-rapidapi-key": os.environ["JSEARCH_API_KEY"],
                   "x-rapidapi-host": "jsearch.p.rapidapi.com"}
        try:
            async with http_client() as client:
                resp = await client.get(API_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json().get("data", [])
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data:
            title = item.get("job_title", "")
            company = item.get("employer_name", "") or ""
            # A single Google-for-Jobs entry often carries several apply
            # options across boards. Prefer a Glassdoor/Indeed option so
            # those postings surface with that board's apply link and
            # publisher label; otherwise take the primary link/publisher.
            url = item.get("job_apply_link", "")
            publisher = item.get("job_publisher") or None
            options = item.get("apply_options") or []
            preferred = _preferred_option(options)
            if preferred and preferred.get("apply_link"):
                url = preferred["apply_link"]
                publisher = preferred.get("publisher") or publisher
            elif not url and options:
                url = options[0].get("apply_link", "")
                publisher = options[0].get("publisher") or publisher
            if not url or not title:
                continue
            raw_type = (item.get("job_employment_type") or "").strip().lower()
            employment_type = (_EMPLOYMENT_MAP.get(raw_type)
                              or guess_employment_type(title))
            location = ", ".join(p for p in (item.get("job_city"),
                                             item.get("job_state"),
                                             item.get("job_country")) if p)
            posted_at = None
            if item.get("job_posted_at_timestamp"):
                try:
                    posted_at = datetime.fromtimestamp(
                        item["job_posted_at_timestamp"])
                except (ValueError, OSError, OverflowError):
                    pass
            # Salary only when explicitly yearly: mapping an hourly figure
            # into salary_max would falsely trip the deterministic
            # salary-floor filter (e.g. $40/hr < $80,000 floor).
            salary_min = salary_max = None
            if (item.get("job_salary_period") or "").upper() == "YEAR":
                salary_min = int(item["job_min_salary"]) if item.get(
                    "job_min_salary") else None
                salary_max = int(item["job_max_salary"]) if item.get(
                    "job_max_salary") else None
            jobs.append(
                Job(
                    id=make_job_id(url, title, company),
                    title=strip_html(title),
                    company=company,
                    employment_type=employment_type,
                    location=location,
                    remote="remote" if item.get("job_is_remote") else "unknown",
                    salary_min=salary_min,
                    salary_max=salary_max,
                    description=strip_html(item.get("job_description", ""))[:4000],
                    url=url,
                    source=self.name,
                    publisher=publisher,
                    posted_at=posted_at,
                )
            )
        return jobs[: query.limit_per_source]
