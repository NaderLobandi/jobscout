"""Contact discovery — Hunter.io Domain Search (Tier B, opt-in, keyed).

CLAUDE.md constraint 2 exception: this is the only feature that fetches
and stores a THIRD PARTY's personal data (a recruiter/HR contact's name,
title, work email) rather than the user's own. Off by default; requires
HUNTER_API_KEY. Sourced from one official, keyed, GET-only API — never a
scraper. NO LLM call anywhere in this module: Hunter's data is already
real and sourced, so a model has nothing to add except hallucination
risk. JobScout only ever displays a contact for the human to reach out
to themselves — there is no code path that emails or messages anyone.

specs/technical_design.md §2 step 9.
"""

from __future__ import annotations

import os

import httpx

API_URL = "https://api.hunter.io/v2/domain-search"
USER_AGENT = "JobScout/1.0 (personal job-search agent; educational project)"

# Deterministic relevance signal, not a guess: real hiring-adjacent roles
# almost always self-identify with one of these words in their title or
# department — the same self-labeling logic already relied on for
# internship detection (guess_employment_type in mcp-server/schema.py).
_HIRING_KEYWORDS = ("recruit", "talent", "people", "hiring", "hr",
                   "human resources", "people operations", "staffing")


def available() -> bool:
    return bool(os.getenv("HUNTER_API_KEY"))


def find_contacts(company: str, role_hint: str = "", limit: int = 5) -> list[dict]:
    """Best-effort discovery of recruiter/hiring-manager contacts at a
    company. Returns [] on any failure, rate limit, or when unconfigured
    — a missing/failed lookup must never block the rest of the pipeline.

    Ranking is deterministic, not Hunter's raw order: hiring-adjacent
    titles/departments first, then title-overlap with the posting's own
    role, then Hunter's own confidence score. This is a relevance
    heuristic, not certainty — always shown with its source citations so
    the human can judge for themselves."""
    if not available() or not company:
        return []
    try:
        resp = httpx.get(
            API_URL,
            params={"company": company, "api_key": os.environ["HUNTER_API_KEY"],
                   "limit": 25},
            headers={"User-Agent": USER_AGENT}, timeout=15.0,
        )
        if resp.status_code in (401, 403, 429):
            return []  # bad/exhausted key or rate limit — degrade, don't crash
        resp.raise_for_status()
        emails = resp.json().get("data", {}).get("emails", [])
    except Exception:
        return []

    role_words = [w.lower() for w in (role_hint or "").split() if len(w) > 3]

    def rank_key(email: dict) -> tuple:
        position = (email.get("position") or "").lower()
        department = (email.get("department") or "").lower()
        text = f"{position} {department}"
        is_hiring = any(k in text for k in _HIRING_KEYWORDS)
        role_overlap = any(w in position for w in role_words)
        return (not is_hiring, not role_overlap, -(email.get("confidence") or 0))

    contacts = []
    for email in sorted(emails, key=rank_key):
        if not email.get("value"):
            continue
        name = " ".join(p for p in
                        [email.get("first_name"), email.get("last_name")] if p)
        contacts.append({
            "name": name or None,
            "position": email.get("position"),
            "department": email.get("department"),
            "email": email["value"],
            "confidence": email.get("confidence"),
            "linkedin": email.get("linkedin") or None,
            "sources": [s["uri"] for s in (email.get("sources") or [])
                       if s.get("uri")][:3],
        })
        if len(contacts) >= limit:
            break
    return contacts
