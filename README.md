# JobScout 🔭 — a personal job-search concierge agent

**Kaggle "AI Agents: Intensive Vibe Coding Capstone" — Concierge Agents track.**

## The problem

Job searching is mostly mechanical: opening tabs across a dozen boards,
re-reading the same boilerplate per posting, and rewriting a cover letter
that says the same four things in a different order. The part that actually
requires judgment — does this specific posting fit this specific person's
skills, preferences, and dealbreakers — is a small fraction of the time
spent. The tempting fix is to automate the whole thing end to end, including
submission. JobScout automates everything **except** that last step.

## The solution

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
          ┌──────────┬──────────┼──────────┬───────────┬─────────┬─────────┐
       RemoteOK   The Muse  Remotive  Arbeitnow  Greenhouse   Lever     Ashby
     (+ JSearch, Adzuna, USAJOBS with free keys · LinkedIn opt-in, see ⚠️)

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
| **Multi-agent system** | Orchestrator + search/scoring/drafting/review/insights sub-agents (`src/agents/`) |
| **Custom MCP server** | `mcp-server/job_search_server.py`, stdio transport, official Python SDK |
| **Security features** | HITL gate, PII masking, audit log, least privilege, deterministic filters, prompt-injection defense (`src/guardrails.py`) |
| **Agent Skills** | Five SKILL.md skills with progressive disclosure (`skills/`) |
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

Optional: drop your resume at `profile/resume.pdf`. For richer scoring,
also drop a LinkedIn export, past cover letters, or reference letters into
`profile/documents/` (see `profile/documents/README.md`) — everything
there is combined with your resume, masked the same way, before analysis.
On the **👤 Profile** page, a "🔍 Preview PDF text extraction" panel lets
you check what text actually got pulled out of your PDFs before any of it
reaches an LLM — useful for catching a scanned/image-only resume with no
real text layer.

**Cost tip:** the agents default to `claude-opus-4-8`. For development, demo
runs, and eval iterations, set `JOBSCOUT_MODEL=claude-haiku-4-5` in `.env` —
a full run typically costs a few cents instead of tens of cents. Structured
outputs work identically on Haiku; the code automatically skips the
`thinking` param there since Haiku doesn't support extended thinking.

## Usage

### Web UI (recommended)

```bash
streamlit run app.py
```

Three pages, same pipeline as the CLI underneath (identical MCP server,
guardrails, and agents):

- **👤 Profile** — full intake form: contact info, resume PDF upload,
  target roles, preferences, dealbreakers, per-dimension scoring weights,
  draft threshold, and job sources. Saves to `profile/profile.yaml`
  (gitignored).
- **🚀 Run JobScout** — one click runs search → deterministic filter →
  resume analysis → per-job scoring with live progress. Each match expands
  into a score-dimension breakdown, a drafted cover letter that's already
  been through a second-pass reviewer critique + resume tweaks, a
  deterministic **keyword-coverage check** against the posting (no LLM
  call — which of the posting's own key terms actually made it into the
  letter), and **Approve / Reject / Skip** buttons — the HITL gate as a UI.
- **📚 History** — every job ever scored, with scores, decisions, the date
  you decided, and saved cover letters (`.jobscout_records.json`,
  gitignored), plus a JSON export. Each entry expands into its full
  per-dimension score breakdown and draft, so the summary table's score
  always has somewhere to drill into. Opens with a **recurring-gaps**
  view: which scoring dimension consistently drags you down across your
  whole history (pure aggregation, free, no LLM call), with an on-demand
  button to get a short, evidence-grounded suggestion for the weakest one.

### CLI

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
resume tweaks for jobs above your threshold → a second, fresh-context
reviewer agent critiques the draft (unsupported claims, missed keywords,
generic phrasing, tone) and returns a revised letter → presents each
package, including the reviewer's notes, at the approval gate. You
review, then apply yourself at the job URL.

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
8. **Repeated anti-fabrication constraints** — "invent nothing, even to
   make the case stronger" and "acknowledge a genuine gap rather than
   hide it" are restated independently in all five skill files, not
   centralized in one. Each skill call is a separate LLM invocation with
   only its own system prompt — there's no shared context for one
   skill's discipline to "carry over" into another's, so each skill
   states its own version of the same rule rather than relying on it.

## Job sources

| Source | Key needed | Status |
|---|---|---|
| RemoteOK | no | ✅ live |
| The Muse | no | ✅ live |
| Remotive | no | ✅ live |
| Arbeitnow | no | ✅ live |
| Greenhouse (per-company) | no | ✅ live |
| Lever (per-company) | no | ✅ live — structured internship detection |
| Ashby (per-company) | no | ✅ live — structured internship detection; dominant ATS among recent YC-batch startups |
| LinkedIn | no | ⚠️ opt-in only, disabled by default — read the disclaimer below |
| JSearch (Google for Jobs) | free key | ✅ implemented — includes postings published on Indeed, Glassdoor, ZipRecruiter |
| Adzuna | free key | ✅ implemented, enabled when keys present |
| USAJOBS | free key | ✅ implemented, enabled when keys present |

**Indeed and Glassdoor have no direct adapters — but their postings are
still covered.** Both sites sit behind active anti-bot walls (HTTP 403 +
CAPTCHA even for a logged-out browser), so unlike LinkedIn's open guest
endpoint there is nothing to access without *defeating* security
countermeasures — a line JobScout doesn't cross, opt-in or not. Instead,
the **JSearch** source queries Google for Jobs, which legitimately
indexes Indeed's and Glassdoor's listings, through a real keyed JSON API
(free tier, no card). Each job records the origin board in its
`publisher` field, so Glassdoor (and Indeed) postings stay identifiable:
the Run and History views show `via jsearch (Glassdoor)`, and History has
a dedicated **publisher** column you can scan. When a posting offers a
Glassdoor or Indeed apply link among its options, JobScout links to that
one (preferring a direct-apply link).
Adding a board = one adapter file implementing
`JobSourceAdapter.search()`.

### ⚠️ LinkedIn disclaimer — read before enabling

LinkedIn has **no official jobs API**, and its
[User Agreement](https://www.linkedin.com/legal/user-agreement) prohibits
automated access. The optional LinkedIn source exists because many
postings — internships especially — appear there first, but **enabling it
is a deliberate, at-your-own-risk decision that JobScout will not make
for you**: it stays off until you both add `linkedin` to your enabled
boards *and* check the explicit acknowledgment box (UI) / answer yes in
the wizard (CLI), which sets `sources.linkedin_tos_acknowledged: true`.

What JobScout does to keep the risk as low as it can be made:

- **Never touches your LinkedIn account.** No login, no cookies, no
  credentials — only the public guest endpoint a logged-out browser
  sees, under JobScout's own honest User-Agent. The realistic worst
  case is a temporary IP rate-limit, not an account ban.
- **Minimal request volume.** One search request per run (first page
  only), plus full-description fetches for at most 8 jobs, at least one
  second apart.
- **Backs off immediately.** Any rate-limit response (HTTP 429/999)
  stops every remaining LinkedIn request for that run.
- **Read-only**, like every other adapter — GET requests only.

None of that changes what it is: automated access that LinkedIn's terms
prohibit. If that trade-off isn't acceptable to you, leave it off — every
other source is unaffected.

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
skills/                      5 Agent Skills (progressive disclosure)
mcp-server/                  MCP server + normalized schema + 11 adapters
src/                         orchestrator, sub-agents, guardrails, memory,
                             intake, pipeline (UI helpers), records (history)
app.py                       Streamlit UI (profile / run / history)
profile/profile.example.yaml committed template (real profile is gitignored)
profile/documents/           optional supplementary docs (gitignored except README)
evals/                       golden set + LLM-as-judge harness
tests/                       pytest for the deterministic parts
Dockerfile                   deployability
```
