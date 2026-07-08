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


def fetch_jobs(profile: dict) -> list[dict]:
    """Search all enabled boards via the MCP server (blocking wrapper)."""

    async def _run() -> list[dict]:
        server = StdioServerParameters(
            command=sys.executable,
            args=[str(REPO_ROOT / "mcp-server" / "job_search_server.py")],
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await search_agent.search(session, profile)

    return asyncio.run(_run())


def verify_liveness(jobs: list[dict]) -> tuple[list[dict], int]:
    """Blocking wrapper around filter_dead_postings() for Streamlit."""
    return asyncio.run(filter_dead_postings(jobs))
