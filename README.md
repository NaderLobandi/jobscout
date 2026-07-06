# JobScout 🔭 — a personal job-search concierge agent

**Kaggle "AI Agents: Intensive Vibe Coding Capstone" — Concierge Agents track.**

JobScout interviews you about what you want, searches many job boards through
**one custom MCP server**, scores every job against your (PII-masked) resume
with a per-dimension rationale, drafts tailored application materials for
strong matches — and then **stops at a human approval gate**. It never
auto-submits an application. That's a feature: most job platforms prohibit
automated submission, auto-blasted generic applications hurt candidates, and
the human-in-the-loop checkpoint is the core of JobScout's security design.

> The build process is the story: the spec (`specs/`) was written first, and
> an AI coding agent implemented against it. Structure scales; vibes don't.

---

## Architecture

```
                 ┌──────────────────────────────────────────────┐
                 │ Orchestrator (src/orchestrator.py)           │
                 │  the agent loop: intake → search → filter →  │
                 │  score → draft → HITL gate → memory          │
                 └──────┬──────────────────────┬────────────────┘
              Claude API│                      │ MCP (stdio)
        ┌───────────────▼───────┐   ┌──────────▼──────────────────┐
        │ Specialist sub-agents │   │ Job-Search MCP Server       │
        │  · search (no LLM)    │   │  search_jobs                │
        │  · scoring + skills   │   │  get_job_details            │
        │  · drafting + skills  │   │  list_sources               │
        └───────────────────────┘   └──────────┬──────────────────┘
                                               │ concurrent fan-out, GET-only
                       ┌───────────┬───────────┼───────────┬─────────────┐
                   RemoteOK    The Muse    Remotive    Arbeitnow    Greenhouse
                                     (+ Adzuna, USAJOBS with free keys)

  Guardrails wrap everything (src/guardrails.py):
  PII masking ⇄ unmasking · audit log (logs/audit.jsonl) · HITL hard stop
  Memory (.jobscout_memory.json) dedupes across sessions.
```

The MCP server normalizes every board into one `Job` schema and dedupes by
URL and by (title, company) — the agent integrates with **one** tool surface
no matter how many boards exist behind it (the NxM integration problem).

## Course concepts demonstrated

| Concept | Where |
|---|---|
| **Multi-agent system** | Orchestrator + search/scoring/drafting sub-agents (`src/agents/`) |
| **Custom MCP server** | `mcp-server/job_search_server.py`, stdio transport, official Python SDK |
| **Security features** | HITL gate, PII masking, audit log, least privilege, deterministic filters, prompt-injection defense (`src/guardrails.py`) |
| **Agent Skills** | Three SKILL.md skills with progressive disclosure (`skills/`) |
| **Memory** | Cross-session seen/approved tracking (`src/memory.py`) |
| **Evals + tests** | pytest for deterministic parts, LLM-as-judge for the scoring agent (`tests/`, `evals/`) |
| **Deployability** | `Dockerfile` + path to production below |

## Setup

Requires Python 3.11+ and an Anthropic API key.

```bash
git clone <this-repo> && cd <this-repo>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then put your ANTHROPIC_API_KEY in .env
```

Optional: drop your resume at `profile/resume.pdf`.

**Cost tip:** the agents default to `claude-opus-4-8`. For development, demo
runs, and eval iterations, set `JOBSCOUT_MODEL=claude-haiku-4-5` in `.env` —
a full run typically costs a few cents instead of tens of cents. Structured
outputs work identically on Haiku; the code automatically skips the
`thinking` param there since Haiku doesn't support extended thinking.

## Usage

```bash
# First run interviews you and writes profile/profile.yaml (gitignored):
python -m src.orchestrator

# Search + deterministic filtering only — no LLM calls, no key needed:
python -m src.orchestrator --dry-run

# Cap LLM scoring calls per run (default 6):
python -m src.orchestrator --max-score 10
```

A full run: searches all enabled boards concurrently via MCP → drops
already-seen jobs, wrong employment types, dealbreakers, and salary-floor
misses **in code, before any LLM call** → analyzes your masked resume once →
scores each job per dimension with rationale → drafts a cover letter +
resume tweaks for jobs above your threshold → presents each package at the
approval gate. You review, then apply yourself at the job URL.

### Testing & evals

```bash
pytest                      # deterministic parts: parsing, masking, dedupe, memory
python -m evals.judge       # scoring-agent evals: golden set + LLM-as-judge
```

The eval golden set includes a **prompt-injection case** — a job description
that orders the model to score it 100/100. The eval passes only if the
injection fails.

### Inspecting the MCP server directly

```bash
npx @modelcontextprotocol/inspector .venv/bin/python mcp-server/job_search_server.py
```

## Security design

1. **HITL checkpoint gate** — the agent has *no code path* that submits an
   application. This mitigates the Confused Deputy problem: JobScout wields
   your authority to search and draft, never your authority to apply.
2. **PII masking (context hygiene)** — your name/email/phone/address become
   `{{CANDIDATE_NAME}}`-style placeholders before any LLM call; real values
   are reinjected only at final local render, never through the model.
3. **Least privilege** — the MCP server is read-only (GET-only HTTP), and the
   Docker image runs as a non-root user.
4. **Audit log** — every tool and LLM call is appended to `logs/audit.jsonl`
   with timestamp, actor, tool, and inputs.
5. **No hardcoded credentials** — env vars only; `.env` is gitignored and
   `.env.example` documents the variables with no values.
6. **Deterministic dealbreaker/threshold logic** — plain Python, so a
   malicious job posting can't prompt-inject its way past your filters.
7. **Untrusted input handling** — job descriptions are wrapped in
   `<job_posting>` tags and the agents are instructed to ignore any
   instructions embedded in them.

## Job sources

| Source | Key needed | Status |
|---|---|---|
| RemoteOK | no | ✅ live |
| The Muse | no | ✅ live |
| Remotive | no | ✅ live |
| Arbeitnow | no | ✅ live |
| Greenhouse (per-company) | no | ✅ live |
| Adzuna | free key | ✅ implemented, enabled when keys present |
| USAJOBS | free key | ✅ implemented, enabled when keys present |

LinkedIn, Indeed, and Glassdoor are **deliberately excluded**: they expose no
public API and scraping violates their ToS. JobScout only talks to
official/public JSON APIs — a compliance decision, not a technical gap.
Adding a board = one adapter file implementing `JobSourceAdapter.search()`.

## Deployment / path to production

Local container (works today):

```bash
docker build -t jobscout .
docker run -it --env-file .env -v $(pwd)/profile:/app/profile -v $(pwd)/logs:/app/logs jobscout
```

Path to production:

1. **Scheduled runs** — the container on a daily cron (Cloud Run Jobs /
   ECS Scheduled Tasks); results land in a queue instead of the terminal.
2. **HITL over a real channel** — replace the CLI gate with an email/Slack
   approval message; the gate contract (`hitl_gate()`) is already isolated.
3. **State** — move `.jobscout_memory.json` and the audit log to a small
   database; both are behind single-file modules.
4. **Secrets** — env vars already; swap `.env` for a secret manager.
5. **Multi-user** — profile-per-user, per-user memory, per-user rate limits
   on the scoring budget (`--max-score` is already the cost knob).

## Honest limitations

- **No auto-submit, by design** — JobScout prepares; you apply.
- Adapter keyword matching is substring-based; niche phrasing can miss.
- Tier B adapters (Adzuna, USAJOBS) are implemented but exercised less than
  the keyless Tier A boards.
- Scoring costs tokens: default caps at 6 jobs/run (`--max-score` to change).
- Salary data is sparse on most boards; the salary-floor filter only fires
  when a posting states a max salary below your floor.

## Repo map

```
CLAUDE.md                    agent operating rules (spec-first, security)
specs/                       source of truth: design + BDD scenarios
skills/                      3 Agent Skills (progressive disclosure)
mcp-server/                  MCP server + normalized schema + 7 adapters
src/                         orchestrator, sub-agents, guardrails, memory, intake
profile/profile.example.yaml committed template (real profile is gitignored)
evals/                       golden set + LLM-as-judge harness
tests/                       pytest for the deterministic parts
Dockerfile                   deployability
```
