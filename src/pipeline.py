"""Sync pipeline helpers shared by the Streamlit UI (app.py).

The CLI orchestrator owns the terminal flow; the UI needs the same steps
as individually callable, synchronous functions (Streamlit reruns a plain
script per interaction). Everything here delegates to the exact same
building blocks the CLI uses — same MCP server, same guardrails, same
agents — so both surfaces stay behaviorally identical.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .agents import search_agent
from .liveness import filter_dead_postings

REPO_ROOT = Path(__file__).resolve().parent.parent

# Outcome-driven search: keep deepening until the target number of NEW
# jobs survives the deterministic filter, up to this many rounds. Feed
# boards contribute round 1 only; deeper rounds cost a handful of extra
# requests against the query-based boards (LinkedIn self-caps at 2).
MAX_SEARCH_ROUNDS = 3


def fetch_jobs(profile: dict, page: int = 1) -> list[dict]:
    """Search all enabled boards via the MCP server (blocking wrapper).
    `page` is the search round — see MAX_SEARCH_ROUNDS."""

    async def _run() -> list[dict]:
        server = StdioServerParameters(
            command=sys.executable,
            args=[str(REPO_ROOT / "mcp-server" / "job_search_server.py")],
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await search_agent.search(session, profile, page=page)

    return asyncio.run(_run())


def collect_new_jobs(fetch_page, keep_filter, target: int,
                     max_rounds: int = MAX_SEARCH_ROUNDS,
                     on_round=None) -> list[dict]:
    """Search until `target` new jobs survive the filter — the outcome is
    the goal, not the visit count.

    fetch_page(page) -> raw jobs for that round; keep_filter(jobs) -> the
    subset worth scoring (seen/type/dealbreaker/salary/age filtering).
    Rounds stop early once `target` is reached or a round returns nothing
    at all (every board exhausted). Cross-round duplicates are dropped by
    job id — query-based boards can resurface the same posting under a
    rotated keyword. on_round(page, found, kept_this_round, kept_total)
    lets the caller narrate progress."""
    kept: list[dict] = []
    seen_ids: set[str] = set()
    for page in range(1, max_rounds + 1):
        raw = fetch_page(page)
        fresh = [j for j in raw if j["id"] not in seen_ids]
        seen_ids.update(j["id"] for j in fresh)
        new_kept = keep_filter(fresh)
        kept.extend(new_kept)
        if on_round:
            on_round(page, len(raw), len(new_kept), len(kept))
        if len(kept) >= target or not raw:
            break
    return kept


def verify_liveness(jobs: list[dict]) -> tuple[list[dict], int]:
    """Blocking wrapper around filter_dead_postings() for Streamlit."""
    return asyncio.run(filter_dead_postings(jobs))
