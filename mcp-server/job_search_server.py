"""JobScout MCP server — one clean tool surface over many job boards.

COURSE CONCEPT (MCP server): the orchestrator speaks the Model Context
Protocol over stdio to this server. Behind the three tools below, searches
fan out concurrently across every enabled adapter and results are
normalized + deduped into one Job schema. Adding a job board never changes
the agent — this is MCP solving the NxM integration problem.

SECURITY (least privilege): this server is strictly read-only. Every
adapter issues GET requests only; there is no tool that can write to any
job platform. Every tool call is appended to logs/audit.jsonl.

Run standalone:  python mcp-server/job_search_server.py
Inspect:         npx @modelcontextprotocol/inspector python mcp-server/job_search_server.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import Job, SearchQuery, dedupe  # noqa: E402
from adapters.base import JobSourceAdapter  # noqa: E402
from adapters.remoteok import RemoteOKAdapter  # noqa: E402
from adapters.themuse import TheMuseAdapter  # noqa: E402
from adapters.remotive import RemotiveAdapter  # noqa: E402
from adapters.arbeitnow import ArbeitnowAdapter  # noqa: E402
from adapters.greenhouse import GreenhouseAdapter  # noqa: E402
from adapters.adzuna import AdzunaAdapter  # noqa: E402
from adapters.usajobs import USAJobsAdapter  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG = REPO_ROOT / "logs" / "audit.jsonl"

mcp = FastMCP("jobscout-job-search")

# In-memory cache so get_job_details can return the full description for a
# job the agent saw in (truncated) search results.
_job_cache: dict[str, Job] = {}


def _audit(tool: str, inputs: dict) -> None:
    """SECURITY (audit log): append every tool invocation with timestamp,
    tool name, and inputs, so a human can review exactly what the agent did."""
    AUDIT_LOG.parent.mkdir(exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": "mcp-server",
        "tool": tool,
        "inputs": inputs,
    }
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_source_config() -> tuple[list[str], list[str]]:
    """Read enabled sources + greenhouse company tokens from the profile.
    Falls back to all keyless sources if no profile exists yet."""
    for name in ("profile.yaml", "profile.example.yaml"):
        path = REPO_ROOT / "profile" / name
        if path.exists():
            cfg = yaml.safe_load(path.read_text()) or {}
            sources = cfg.get("sources", {})
            return (
                sources.get("enabled", []),
                sources.get("greenhouse_companies", []),
            )
    return ["remoteok", "themuse", "remotive", "arbeitnow"], []


def _build_adapters() -> list[JobSourceAdapter]:
    enabled, gh_companies = _load_source_config()
    registry: dict[str, JobSourceAdapter] = {
        "remoteok": RemoteOKAdapter(),
        "themuse": TheMuseAdapter(),
        "remotive": RemotiveAdapter(),
        "arbeitnow": ArbeitnowAdapter(),
        "greenhouse": GreenhouseAdapter(companies=gh_companies),
        "adzuna": AdzunaAdapter(),
        "usajobs": USAJobsAdapter(),
    }
    return [a for name, a in registry.items()
            if name in enabled and a.available()]


@mcp.tool()
async def search_jobs(
    keywords: list[str],
    locations: list[str] | None = None,
    remote_only: bool = False,
    limit_per_source: int = 25,
) -> list[dict]:
    """Search all enabled job boards at once and return normalized,
    deduplicated job postings.

    Args:
        keywords: role/skill phrases, e.g. ["machine learning engineer"].
        locations: preferred locations, e.g. ["Denver", "Remote US"].
        remote_only: drop onsite-only roles where the source exposes that.
        limit_per_source: cap results per board (keeps responses small).
    """
    _audit("search_jobs", {"keywords": keywords, "locations": locations,
                           "remote_only": remote_only,
                           "limit_per_source": limit_per_source})
    query = SearchQuery(
        keywords=keywords,
        locations=locations or [],
        remote_only=remote_only,
        limit_per_source=limit_per_source,
    )
    adapters = _build_adapters()
    # Concurrent fan-out: one slow board doesn't serialize the rest.
    results = await asyncio.gather(*(a.search(query) for a in adapters))
    jobs = dedupe([job for board in results for job in board])
    for job in jobs:
        _job_cache[job.id] = job
    # Truncate descriptions in list results to keep the agent's context lean;
    # get_job_details returns the full text on demand.
    out = []
    for job in jobs:
        d = job.model_dump(mode="json")
        d["description"] = (d["description"] or "")[:600]
        out.append(d)
    return out


@mcp.tool()
async def get_job_details(job_id: str) -> dict:
    """Return the full record (untruncated description) for a job id
    previously returned by search_jobs."""
    _audit("get_job_details", {"job_id": job_id})
    job = _job_cache.get(job_id)
    if job is None:
        return {"error": f"unknown job_id {job_id!r} — call search_jobs first"}
    return job.model_dump(mode="json")


@mcp.tool()
async def list_sources() -> list[dict]:
    """List every registered job source and whether it is enabled/available."""
    _audit("list_sources", {})
    enabled, gh_companies = _load_source_config()
    registry = {
        "remoteok": RemoteOKAdapter(),
        "themuse": TheMuseAdapter(),
        "remotive": RemotiveAdapter(),
        "arbeitnow": ArbeitnowAdapter(),
        "greenhouse": GreenhouseAdapter(companies=gh_companies),
        "adzuna": AdzunaAdapter(),
        "usajobs": USAJobsAdapter(),
    }
    return [
        {
            "name": name,
            "enabled": name in enabled,
            "available": adapter.available(),
            "requires_key": adapter.requires_key,
        }
        for name, adapter in registry.items()
    ]


if __name__ == "__main__":
    mcp.run()  # stdio transport — the orchestrator launches us as a subprocess
