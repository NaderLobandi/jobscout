# JobScout — Technical Design

This spec is the source of truth. If code and spec conflict, the spec wins.

## 1. Product

JobScout is a personal job-search **concierge agent**. It:

1. Interviews the user about preferences (intake wizard → `profile/profile.yaml`)
   and optionally ingests supplementary documents (LinkedIn export, past
   cover letters, reference letters) from `profile/documents/`
2. Searches many job boards through **one** normalized MCP tool
3. Deterministically filters hard dealbreakers before any LLM call
4. Scores each surviving job against the (PII-masked) resume + supplementary
   documents + preferences, with a weighted per-dimension breakdown and
   plain-language rationale
5. Drafts a tailored cover letter, resume tweak suggestions, and an
   ATS-optimized CV PDF for strong matches
6. **Stops at a human-in-the-loop gate.** The user reviews and applies manually
   via the job URL. JobScout never auto-submits.

## 2. Architecture

```
┌────────────┐   stdio    ┌──────────────────────────────┐
│ Orchestrator│◄─────────►│ MCP Server (job_search)      │
│ (agent loop)│           │  search_jobs / get_job_details│
└─────┬──────┘           │  / list_sources               │
      │                   └───────┬──────────────────────┘
      │ Claude API                │ concurrent fan-out
┌─────▼──────────┐        ┌───────▼───────────────────────┐
│ Sub-agents     │        │ Adapters: remoteok, themuse,  │
│  search        │        │ remotive, arbeitnow,          │
│  scoring       │        │ greenhouse, lever, ashby,     │
│  drafting      │        │ (adzuna, usajobs)             │
└────────────────┘        └───────────────────────────────┘
Guardrails wrap everything: PII masking in/out, audit log, HITL gate.
Memory (.jobscout_memory.json) dedupes across sessions.
```

### Agent loop (src/orchestrator.py)

Five components per the course framework: **model** (Claude API),
**tools** (MCP server), **memory** (JSON state file), **orchestration**
(the loop), **deployment** (Docker + docs).

1. Intake: if `profile/profile.yaml` missing/incomplete → run wizard
2. Search: Search Agent builds `SearchQuery` from profile → MCP `search_jobs`
3. Filter: deterministic dealbreaker + employment-type + salary-floor +
   posting-age filters BEFORE scoring. `guardrails.posting_is_recent()`
   drops anything older than `preferences.max_posting_age_days` — and,
   unlike the other filters, an UNDATED posting does NOT pass when this
   is set, since the point is a freshness guarantee.
4. Score: Scoring Agent per job (masked resume + prefs) → weighted score,
   per-dimension breakdown, rationale (structured output, JSON schema).
   `--min-matches N` (CLI) turns the fixed-batch scoring pass into a
   goal-seeking loop: keep scoring jobs, in relevance order, up to the
   `--max-score` ceiling, until N score ≥ `draft_threshold` or the pool
   (or ceiling) is exhausted — printing a clear warning if the goal isn't
   met rather than silently returning fewer matches than asked for.
5. Draft: for jobs ≥ threshold → Drafting Agent → cover letter + resume tweaks
5b. Review: a second, fresh-context call (Drafting Agent's `review_draft`)
   critiques the masked cover letter for unsupported claims, missed
   keywords, generic phrasing, and tone mismatch, and returns a revised
   letter + a one-sentence summary. Runs on masked text, before unmask.
5c. Keyword coverage: `src/keyword_coverage.py` deterministically extracts
   the posting's key terms (title words + frequent non-stopword terms,
   filtered against a small job-posting-filler list) and checks which
   appear in the final cover letter — no LLM call, a second, independent
   check on the same claim the drafting/review skills already instruct
   for ("use the posting's terminology, don't stuff keywords").
5d. ATS CV generation: `src/agents/drafting_agent.py`'s `tailor_cv()`
   restructures the candidate's REAL resume (full masked text, not the
   condensed skills profile, so the model has real dates/companies to
   draw from) into CV sections for this posting — selecting, reordering,
   and rephrasing only, never inventing an employer, title, date, or
   metric (`skills/cv-tailoring/SKILL.md`). `src/cv_render.py` then
   renders those sections into a PDF locally with **no LLM call** —
   deterministic layout, core PDF fonts only (no embedded/subset font,
   which is what breaks text-layer extraction in some LaTeX-generated
   resumes), single column, ASCII-only structural characters. PII is
   unmasked ONLY at this final local render step, same pattern as the
   cover letter. The PDF is written to `output/cvs/<job_id>.pdf`
   (gitignored); only the path is stored in Records.
6. HITL gate: present package (including reviewer notes, keyword
   coverage, and the tailored CV), hard stop, user applies manually.
   `--auto` (CLI): for unattended/scheduled runs, where nobody is at a
   terminal to answer the interactive prompt. The gate itself is NOT
   skipped or weakened — it's deferred: drafted packages are written to
   `.jobscout_records.json` with no decision, the same store and the
   same "undecided" state the Streamlit UI already uses before a human
   clicks Approve/Reject/Skip. There remains no code path anywhere that
   sets a decision other than an explicit human action.
7. Memory: record seen/approved job IDs; reruns skip duplicates
8. Insights (on demand, UI History page only): `src/insights.py` computes
   average score per dimension across every Records entry ever scored —
   plain aggregation, no LLM call — surfacing which dimension recurringly
   drags the overall score down and how often it was the single weakest
   link per job. Insights Agent's `suggest_focus` turns the aggregate for
   the worst dimension into a short, evidence-grounded suggestion —
   spends a token only when the user explicitly asks for it.
9. Contact Discovery (on demand, per posting, opt-in): `src/contacts.py`
   queries Hunter.io's Domain Search API for a company and returns
   recruiter/HR-adjacent contacts (name, title, email, Hunter's own
   confidence score, source citation URLs). **No LLM call** — Hunter's
   data is already real and sourced, so a model has nothing to add
   except hallucination risk. Ranking is deterministic: hiring-adjacent
   titles/departments (recruiter, talent, HR, people ops) first, then
   title-overlap with the posting's own role, then Hunter's confidence
   score. Off unless `HUNTER_API_KEY` is set. Results are stored in
   Records (`contacts` field) alongside the job — the one place JobScout
   persists a THIRD PARTY's personal data, not the user's own (CLAUDE.md
   constraint 2 exception). JobScout only displays a contact; there is
   no code path that emails, messages, or otherwise contacts anyone.

## 3. Data contracts

### Job (mcp-server/schema.py)

| field | type | notes |
|---|---|---|
| id | str | sha1 of canonical URL (fallback: title+company) |
| title | str | |
| company | str | |
| employment_type | str | full-time, part-time, internship, contract, unknown |
| location | str | |
| remote | str | onsite, hybrid, remote, unknown |
| industry | str? | |
| salary_min / salary_max | int? | USD/yr where known |
| description | str | plain text, HTML stripped |
| url | str | apply link |
| source | str | adapter name that fetched it |
| publisher | str? | origin board for aggregators (e.g. "Glassdoor" via jsearch); None for direct adapters |
| posted_at | datetime? | |

### SearchQuery

`keywords: list[str]`, `locations: list[str]`, `remote_only: bool`,
`limit_per_source: int`

### Adapter interface (adapters/base.py)

```python
class JobSourceAdapter(ABC):
    name: str
    requires_key: bool
    async def search(self, query: SearchQuery) -> list[Job]: ...
```

The MCP server fans out across enabled adapters concurrently, normalizes,
and dedupes by URL hash then by (title, company) hash. The agent sees ONE
clean tool regardless of source count — this solves the **NxM integration
problem** (Day 2 course concept).

### Scoring output (structured JSON, enforced via output_config.format)

```json
{
  "dimensions": {
    "skills_match":     {"score": 0-100, "reason": "..."},
    "role_title_match": {"score": 0-100, "reason": "..."},
    "industry_match":   {"score": 0-100, "reason": "..."},
    "location_match":   {"score": 0-100, "reason": "..."},
    "seniority_match":  {"score": 0-100, "reason": "..."}
  },
  "summary": "plain-language rationale"
}
```

The weighted total is computed in **deterministic Python** from
`profile.weights` — never by the LLM — so weights cannot be prompt-injected.

## 4. Security design (scored course concept)

1. **HITL checkpoint gate** — mitigates the Confused Deputy problem: the
   agent holds the user's authority to search/draft but NOT to submit.
2. **PII masking** — `guardrails.mask_pii()` replaces name/email/phone/address
   with `{{CANDIDATE_NAME}}` etc. before any LLM call; real values reinjected
   only at final local render (`unmask_pii()`), never through the model.
3. **Least privilege** — MCP server is read-only (GET-only HTTP).
4. **Audit log** — every tool call → `logs/audit.jsonl` (timestamp, tool, inputs).
5. **No hardcoded credentials** — env vars only; `.env` gitignored.
6. **Deterministic filters** — dealbreakers/thresholds are Python string
   matching, not LLM judgment → not prompt-injectable.
7. **Untrusted input** — job descriptions are wrapped in delimiters and the
   scoring/drafting prompts instruct the model to ignore embedded instructions.
8. **Third-party PII is display-only** — Contact Discovery (§2 step 9) is
   the sole feature that stores someone else's personal data. It's
   opt-in (requires `HUNTER_API_KEY`), sourced from one official keyed
   API (never a scraper), and JobScout never messages a discovered
   contact — displaying it for the human is the entire feature.

## 5. Sources

Tier A (no key): remoteok, themuse, remotive, arbeitnow, greenhouse, lever,
ashby (the last three take per-company/org board tokens). Tier B (free
key, stubbed if not built): adzuna, usajobs, jsearch.

**Indeed and Glassdoor have no adapters, and won't.** Unlike LinkedIn's
open guest endpoint (plain HTTP 200, no protection to bypass), both sites
return HTTP 403 with active anti-bot walls — Cloudflare CAPTCHA on
Indeed, a hard block on Glassdoor — even to a logged-out browser
(verified 2026-07). Reaching them would mean *defeating* those
countermeasures (CAPTCHA solvers, stealth browsers, proxy rotation),
which is a different category of act than using an unprotected public
endpoint, and is out of scope regardless of opt-in. Their postings are
instead reachable through the front door: **jsearch** (Tier B) queries
Google for Jobs, which legitimately indexes Indeed's and Glassdoor's
listings; each result's publisher is visible via its apply URL.

Tier C (ToS-risk, explicit opt-in only): **linkedin**. Uses LinkedIn's
unauthenticated public guest endpoints (`jobs-guest/jobs/api/...`) — the
same public pages a logged-out browser sees, but automated access still
violates LinkedIn's User Agreement. Added as an explicit owner decision
(most postings appear on LinkedIn first, especially internships).
Safety posture, in priority order:

1. Disabled by default; enabling requires BOTH `linkedin` in
   `sources.enabled` AND `sources.linkedin_tos_acknowledged: true`.
2. No login, no cookies, no credentials — nothing that can tie traffic to
   the user's LinkedIn account, so the worst realistic outcome is an IP
   rate-limit, not an account ban.
3. GET-only, single search request per run (first result page only, ≤25
   jobs), plus description fetches for at most 8 jobs with a ≥1s delay
   between each.
4. Any 429/999 response aborts all remaining LinkedIn requests for the
   run — jobs already parsed are returned with whatever data they have.
5. Server-side filters (`f_JT` employment type, `f_WT` remote) narrow
   results at the source so no requests are spent on jobs the
   deterministic filter would drop anyway.

Lever and Ashby postings carry a structured commitment/employment-type
field ("Internship", "Intern", ...) instead of requiring free-text
guessing — `guess_employment_type()` is only a fallback for boards that
don't expose one. Both are heavily used by startups, including many
YC-backed companies, and by extension are a meaningfully denser source of
internship postings than the Tier A boards that only expose free text.

## 6. Testing strategy

- `tests/` (pytest, deterministic parts): adapter parsing from recorded JSON
  fixtures (no live calls), dedup, dealbreaker filtering, PII mask round-trip.
- `evals/` (non-deterministic parts): golden set of labeled job/profile pairs;
  LLM-as-judge checks the Scoring Agent's score lands in the expected band and
  the rationale mentions expected factors. Tests verify code; evals verify
  model behavior — you need both.
