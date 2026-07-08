"""LinkedIn adapter — unauthenticated public guest endpoints. OPT-IN ONLY.

⚠️ ToS WARNING: LinkedIn's User Agreement prohibits automated access, and
LinkedIn exposes no official jobs API. This adapter exists as an explicit,
documented owner decision (specs/technical_design.md §5 Tier C; CLAUDE.md
constraint 4): most postings — especially internships — appear on LinkedIn
first. Every mitigation below is deliberate; do not weaken them:

- Hard-gated: available() is False unless the profile sets BOTH
  `linkedin` in sources.enabled AND sources.linkedin_tos_acknowledged.
- No login, no cookies, no credentials — only the same public guest
  endpoints a logged-out browser sees, under the honest JobScout
  User-Agent. Nothing ties the traffic to the user's LinkedIn account,
  so the realistic worst case is an IP rate-limit, not an account ban.
- Minimal volume: at most MAX_SEARCH_ROUNDS (2) search requests per run —
  round 2 only fires when outcome-driven deepening is starved, with a
  DIFFERENT keyword (rotation), never page-scrolling — plus at most
  MAX_DETAIL_FETCHES description fetches per search, ≥1s apart. The cap
  is stateless (`query.page > 2 → []`), so no caller can push past it.
- Any 429/999 (LinkedIn's rate-limit codes) aborts every remaining
  LinkedIn request for this run.
- Server-side f_JT/f_WT filters narrow the search, but are NOT trusted as
  ground truth — LinkedIn's guest search does not strictly enforce them,
  so every result's employment_type is still inferred from its own title
  (and description, once fetched), never assumed from the request filter.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

from .base import JobSourceAdapter, http_client, rotation_keyword
from schema import Job, SearchQuery, guess_employment_type, make_job_id, strip_html

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

MAX_DETAIL_FETCHES = 8
MAX_SEARCH_ROUNDS = 2  # hard per-run cap on search requests (ToS budget)
DETAIL_DELAY_S = 1.0
_RATE_LIMIT_CODES = (429, 999)

# f_JT: LinkedIn's server-side employment-type filter codes.
_F_JT = {"full-time": "F", "part-time": "P", "internship": "I", "contract": "C"}

_CARD_URL_RE = re.compile(r'base-card__full-link[^>]*href="([^"]+)"')
_TITLE_RE = re.compile(r'base-search-card__title">\s*(.*?)\s*</h3>', re.DOTALL)
_COMPANY_RE = re.compile(
    r'base-search-card__subtitle">.*?<a[^>]*>\s*(.*?)\s*</a>', re.DOTALL)
_LOCATION_RE = re.compile(
    r'job-search-card__location">\s*(.*?)\s*</span>', re.DOTALL)
_DATE_RE = re.compile(r'datetime="(\d{4}-\d{2}-\d{2})"')
_DESCRIPTION_RE = re.compile(
    r'show-more-less-html__markup[^>]*>(.*?)</div>', re.DOTALL)


class LinkedInAdapter(JobSourceAdapter):
    name = "linkedin"
    requires_key = False

    def __init__(self, employment_types: list[str] | None = None,
                 tos_acknowledged: bool = False):
        self.employment_types = employment_types or []
        self.tos_acknowledged = tos_acknowledged

    def available(self) -> bool:
        # SECURITY/COMPLIANCE gate: silent enablement is not possible — the
        # user must set sources.linkedin_tos_acknowledged in their profile.
        return self.tos_acknowledged

    async def search(self, query: SearchQuery) -> list[Job]:
        if not self.tos_acknowledged:
            return []
        # Stateless hard cap on per-run search volume (ToS budget): rounds
        # past MAX_SEARCH_ROUNDS get nothing, regardless of the caller.
        if query.page > MAX_SEARCH_ROUNDS:
            return []
        kw = rotation_keyword(query)
        if kw is None:
            return []  # keyword rotation exhausted — nothing new to ask
        params: dict[str, str] = {"start": "0"}
        # ONE search phrase, ONE request per round: LinkedIn already ranks
        # by relevance server-side; a deeper round asks a DIFFERENT
        # keyword (rotation) rather than page-scrolling the starved one.
        if kw:
            params["keywords"] = kw
        if query.locations:
            params["location"] = query.locations[0]
        if query.remote_only:
            params["f_WT"] = "2"
        jt = ",".join(_F_JT[t] for t in self.employment_types if t in _F_JT)
        if jt:
            params["f_JT"] = jt

        try:
            async with http_client() as client:
                resp = await client.get(SEARCH_URL, params=params)
                if resp.status_code in _RATE_LIMIT_CODES:
                    return []
                resp.raise_for_status()
                jobs = self._parse_cards(resp.text, query)
                await self._fetch_descriptions(client, jobs)
                return jobs[: query.limit_per_source]
        except Exception:
            return []

    def _parse_cards(self, html_text: str, query: SearchQuery) -> list[Job]:
        # No client-side matches_keywords() here: LinkedIn applied the
        # keyword search server-side, and its relevant titles don't always
        # contain the query phrase verbatim.
        jobs: list[Job] = []
        chunks = html_text.split('data-entity-urn="urn:li:jobPosting:')[1:]
        for chunk in chunks:
            url_m = _CARD_URL_RE.search(chunk)
            title_m = _TITLE_RE.search(chunk)
            if not url_m or not title_m:
                continue
            url = url_m.group(1).split("?")[0]
            title = strip_html(title_m.group(1))
            company_m = _COMPANY_RE.search(chunk)
            company = strip_html(company_m.group(1)) if company_m else ""
            location_m = _LOCATION_RE.search(chunk)
            location = strip_html(location_m.group(1)) if location_m else ""
            posted_at = None
            date_m = _DATE_RE.search(chunk)
            if date_m:
                try:
                    posted_at = datetime.fromisoformat(date_m.group(1))
                except ValueError:
                    pass
            # NEVER trust f_JT as ground truth: LinkedIn's guest/public
            # search does not strictly enforce it — a full-time posting
            # like "Machine Learning Engineer" can and does come back even
            # under f_JT=I (internship-only). Treating the request filter
            # as proof of the result's type mass-mislabels real full-time
            # roles as internships. Always infer per-item from the actual
            # title text instead.
            employment_type = guess_employment_type(title)
            jobs.append(
                Job(
                    id=make_job_id(url, title, company),
                    title=title,
                    company=company,
                    employment_type=employment_type,
                    location=location,
                    remote="remote" if "remote" in location.lower() else "unknown",
                    url=url,
                    source=self.name,
                    posted_at=posted_at,
                )
            )
        return jobs

    async def _fetch_descriptions(self, client, jobs: list[Job]) -> None:
        """Fill descriptions for the first few jobs only — each one is an
        extra request against the ToS-risk budget. Any rate-limit response
        stops ALL remaining LinkedIn fetches for this run."""
        for job in jobs[:MAX_DETAIL_FETCHES]:
            await asyncio.sleep(DETAIL_DELAY_S)
            job_id = job.url.rstrip("/").rsplit("-", 1)[-1]
            if not job_id.isdigit():
                continue
            try:
                resp = await client.get(DETAIL_URL.format(job_id=job_id))
            except Exception:
                return
            if resp.status_code in _RATE_LIMIT_CODES:
                return  # back off for the whole run, keep what we have
            if resp.status_code != 200:
                continue
            desc_m = _DESCRIPTION_RE.search(resp.text)
            if desc_m:
                job.description = strip_html(desc_m.group(1))[:4000]
                # Re-infer with the full body in hand — a title alone can
                # miss an internship the posting states explicitly inside.
                job.employment_type = guess_employment_type(
                    f"{job.title} {job.description}")
