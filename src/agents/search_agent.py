"""Search Agent: turns profile preferences into MCP search_jobs calls.

COURSE CONCEPT (tool use via MCP): this agent is the only component that
talks to the job-search MCP server. Query construction is deterministic —
no LLM needed to translate structured preferences into a structured query,
so we don't spend tokens where code suffices.
"""

from __future__ import annotations

import json

from mcp import ClientSession

from ..guardrails import audit
from ..query_expansion import expand_keywords


def build_query(profile: dict) -> dict:
    prefs = profile.get("preferences", {})
    roles = prefs.get("target_roles", [])
    # Broaden by default so exact-phrase role titles don't starve recall
    # (see src/query_expansion.py); precision is the scorer's job. Opt out
    # with strict_keyword_match: true for verbatim-only matching.
    keywords = roles if prefs.get("strict_keyword_match") else expand_keywords(roles)
    return {
        "keywords": keywords,
        "locations": prefs.get("locations", []),
        "remote_only": prefs.get("remote_preference") == "remote_only",
        "limit_per_source": 25,
    }


async def search(session: ClientSession, profile: dict) -> list[dict]:
    """Call the MCP search_jobs tool and parse the normalized job list."""
    query = build_query(profile)
    audit("mcp.search_jobs", query)
    result = await session.call_tool("search_jobs", query)
    jobs: list[dict] = []
    for content in result.content:
        if content.type != "text":
            continue
        parsed = json.loads(content.text)
        jobs.extend(parsed if isinstance(parsed, list) else [parsed])
    return jobs
