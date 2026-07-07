"""JobScout orchestrator — the agent loop.

COURSE CONCEPT (agent architecture): the five components of an agent are
all here — MODEL (Claude via the Anthropic SDK), TOOLS (the job-search
MCP server), MEMORY (.jobscout_memory.json), ORCHESTRATION (this loop),
and DEPLOYMENT (Dockerfile + README path-to-production).

Flow: intake → search (MCP) → deterministic filter → score → draft →
HITL gate → memory update. The gate is a hard stop: JobScout has no code
path that submits an application anywhere.

Usage:
    python -m src.orchestrator                # full run
    python -m src.orchestrator --dry-run      # search+filter only, no LLM
    python -m src.orchestrator --max-score 4  # cap LLM scoring calls
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.table import Table

from .agents import scoring_agent, drafting_agent, search_agent
from .guardrails import (PIIMasker, audit, employment_type_allowed, hitl_gate,
                         violates_dealbreakers)
from .intake import extract_profile_text, load_profile, run_wizard
from .memory import Memory

REPO_ROOT = Path(__file__).resolve().parent.parent
console = Console()


def _relevance_rank(job: dict, target_roles: list[str]) -> int:
    """Cheap deterministic tie-breaker so the (budget-capped) LLM scoring
    calls go to the most obviously relevant jobs first, rather than
    whatever order dedupe/fan-out happened to produce. A full target-role
    phrase in the title scores highest; partial word overlap scores lower;
    no overlap sorts last."""
    title = job["title"].lower()
    best = 0
    for role in target_roles:
        role_l = role.lower().strip()
        if role_l and role_l in title:
            best = max(best, 2)
            continue
        words = [w for w in role_l.split() if len(w) > 2]
        if words and any(w in title for w in words):
            best = max(best, 1)
    return best


def deterministic_filter(jobs: list[dict], profile: dict, memory: Memory) -> list[dict]:
    """SECURITY (deterministic guardrail): hard filters run BEFORE any LLM
    call — cheaper, and immune to prompt injection from job-posting text.
    Order: already-seen → employment type → dealbreakers → salary floor."""
    prefs = profile.get("preferences", {})
    dealbreakers = prefs.get("dealbreakers", [])
    allowed_types = prefs.get("employment_types", [])
    salary_floor = prefs.get("salary_floor_usd", 0) or 0

    kept: list[dict] = []
    dropped = {"seen": 0, "type": 0, "dealbreaker": 0, "salary": 0}
    for job in jobs:
        if memory.is_seen(job["id"]):
            dropped["seen"] += 1
            continue
        if not employment_type_allowed(job["employment_type"], allowed_types):
            dropped["type"] += 1
            continue
        if violates_dealbreakers(f"{job['title']} {job['description']}", dealbreakers):
            dropped["dealbreaker"] += 1
            continue
        # Only enforce the floor when the posting states a max salary below it
        if salary_floor and job.get("salary_max") and job["salary_max"] < salary_floor:
            dropped["salary"] += 1
            continue
        kept.append(job)

    audit("deterministic_filter", {"in": len(jobs), "kept": len(kept), **dropped})
    console.print(
        f"[dim]Filter: {len(jobs)} in → {len(kept)} kept "
        f"(seen {dropped['seen']}, type {dropped['type']}, "
        f"dealbreaker {dropped['dealbreaker']}, salary {dropped['salary']})[/dim]"
    )
    return kept


async def run(max_score: int, dry_run: bool) -> None:
    load_dotenv(REPO_ROOT / ".env")

    # ---- 1. Intake ------------------------------------------------------
    profile = load_profile()
    if profile is None:
        console.print("[yellow]No profile found — starting intake wizard.[/yellow]")
        profile = run_wizard()

    candidate = profile.get("candidate", {})
    masker = PIIMasker(
        name=candidate.get("name", ""),
        email=candidate.get("email", ""),
        phone=candidate.get("phone", ""),
        address=candidate.get("address", ""),
    )
    memory = Memory()

    # ---- 2. Search via MCP ----------------------------------------------
    console.print("[bold cyan]🔎 Searching job boards via MCP…[/bold cyan]")
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(REPO_ROOT / "mcp-server" / "job_search_server.py")],
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            jobs = await search_agent.search(session, profile)
    console.print(f"Found [bold]{len(jobs)}[/bold] normalized, deduped jobs.")

    # ---- 3. Deterministic filter (before ANY LLM call) --------------------
    jobs = deterministic_filter(jobs, profile, memory)
    if not jobs:
        console.print("[yellow]Nothing new to score — try broadening your "
                      "profile keywords or clearing .jobscout_memory.json[/yellow]")
        return
    if dry_run:
        _print_table(jobs[:20])
        console.print("[dim]--dry-run: stopping before LLM scoring.[/dim]")
        return

    # ---- 4. Score (masked resume; per-dimension; weighted in code) --------
    client = Anthropic()  # key resolved from env / .env — never hardcoded
    resume_text = masker.mask(extract_profile_text(profile))
    summary = masker.mask(candidate.get("summary", ""))
    console.print("[bold cyan]🧠 Analyzing resume + supplementary "
                  "documents (PII-masked)…[/bold cyan]")
    skills_profile = scoring_agent.analyze_resume(client, resume_text, summary)

    prefs = profile.get("preferences", {})
    weights = profile.get("weights", {})
    # Rank by title relevance before capping — the scoring budget should go
    # to the jobs most likely to matter, not whatever order dedupe produced.
    jobs.sort(key=lambda j: _relevance_rank(j, prefs.get("target_roles", [])),
             reverse=True)
    to_score = jobs[:max_score]
    console.print(f"[bold cyan]⚖️  Scoring {len(to_score)} jobs…[/bold cyan]")
    scored: list[dict] = []
    for job in to_score:
        try:
            result = scoring_agent.score_job(client, skills_profile, prefs,
                                             job, weights)
        except Exception as exc:  # one bad job must not kill the run
            console.print(f"[red]scoring failed for {job['title']!r}: {exc}[/red]")
            continue
        scored.append({"job": job, **result})
        console.print(f"  {result['score']:5.1f}  {job['title'][:55]} @ {job['company']}")

    scored.sort(key=lambda s: s["score"], reverse=True)
    threshold = profile.get("draft_threshold", 70)

    # ---- 5 + 6. Draft for strong matches, then HITL gate -------------------
    for package in scored:
        job = package["job"]
        if package["score"] >= threshold:
            console.print(f"[bold cyan]✍️  Drafting package for "
                          f"{job['title']} @ {job['company']}…[/bold cyan]")
            try:
                style = candidate.get("communication_style", "")
                drafts = drafting_agent.draft_package(client, skills_profile,
                                                      job, package, style)
                review = drafting_agent.review_draft(
                    client, skills_profile, job, drafts["cover_letter"], style)
                # SECURITY: unmask ONLY here — final local render for human
                # eyes; the unmasked text never goes back through the model.
                package["cover_letter"] = masker.unmask(review["revised_cover_letter"])
                package["resume_tweaks"] = drafts["resume_tweaks"]
                package["review_notes"] = review["revision_summary"]
                package["review_issues"] = review["issues_found"]
            except Exception as exc:
                console.print(f"[red]drafting failed: {exc}[/red]")

            # HARD STOP — the human decides; JobScout never submits.
            decision = hitl_gate(package)
            if decision == "quit":
                memory.mark_seen(job["id"], job["title"], "skipped")
                console.print("[dim]Stopping review for this run — "
                              "remaining matches will reappear next run.[/dim]")
                break
        else:
            decision = "below_threshold"
            console.print(f"[dim]{package['score']:5.1f} (below {threshold}) "
                          f"{job['title'][:55]} — no draft[/dim]")

        # ---- 7. Memory update ------------------------------------------
        memory.mark_seen(job["id"], job["title"],
                         "approved" if decision == "approved" else decision)

    console.print(
        f"\n[green]Done. {memory.seen_count} jobs remembered, "
        f"{memory.approved_count} approved so far. "
        f"Audit trail: logs/audit.jsonl[/green]"
    )


def _print_table(jobs: list[dict]) -> None:
    table = Table(title="Filtered jobs (dry run)")
    table.add_column("Title", max_width=40)
    table.add_column("Company")
    table.add_column("Loc", max_width=20)
    table.add_column("Source")
    for j in jobs:
        table.add_row(j["title"], j["company"], j["location"], j["source"])
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="JobScout — AI job matching agent")
    parser.add_argument("--max-score", type=int, default=6,
                        help="max jobs to score with the LLM per run (cost cap)")
    parser.add_argument("--dry-run", action="store_true",
                        help="search + filter only; no LLM calls")
    args = parser.parse_args()
    asyncio.run(run(args.max_score, args.dry_run))


if __name__ == "__main__":
    main()
