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
2. Search: Search Agent builds `SearchQuery` from profile → MCP `search_jobs`.
   `build_query()` broadens the profile's `target_roles` into a wider
   keyword set via `src/query_expansion.py` (deterministic, no LLM) UNLESS
   `preferences.strict_keyword_match` is true. Rationale (recall vs.
   precision): the board-side keyword match is a RECALL filter — surface
   every plausible posting — while PRECISION is the scorer's job (0-100 per
   dimension). Exact-phrase role titles ("Machine Learning Engineer")
   match almost nothing on real boards, which starved results: the same
   few jobs surfaced every run and the seen-dedup then reported "nothing
   new." Expansion adds the seniority-stripped core, the role-noun-stripped
   domain ("machine learning"), and abbreviation equivalents (ML ↔ machine
   learning, AI ↔ artificial intelligence). Originals stay first because
   query-based adapters search one keyword per round (see 2b) and the
   user's primary role must be round 1's query.
   Employment-type awareness: when the profile is internship-only,
   expansion inserts intern-targeted compound phrases ("machine learning
   intern", "ai intern") right after the primary role — query-based boards
   need the word in the QUERY to surface internships; a bare "intern"
   keyword is deliberately never emitted (it would match internships in
   any field and waste scoring budget).
   `adapters/base.matches_keywords()` is anchored to word boundaries (not
   raw substring) so short abbreviations ("ml", "ai") match the WORD, not
   the "ai" inside "training" — this is what makes broadening safe.
2b. Outcome-driven search rounds: one fixed-depth fetch is hope, not a
   guarantee — so search is a LOOP that deepens until it has collected
   `max_score` NEW jobs that survive the deterministic filter (the "Max
   jobs to score" knob is the outcome target, not a visit budget), or
   `MAX_SEARCH_ROUNDS` (3) is reached, or a round returns nothing at all.
   `SearchQuery.page` (default 1) carries the round number; each adapter
   interprets it per its own API, statelessly:
   - Feed/company boards (RemoteOK, Remotive, Arbeitnow, Greenhouse,
     Lever, Ashby): their entire inventory arrives on round 1, so
     `page > 1` returns `[]` immediately — zero extra HTTP.
   - The Muse: real API pagination — round N fetches its pages
     (N-1)*3+1 … N*3.
   - Query-based boards (LinkedIn, JSearch, Adzuna, USAJOBS): round N
     queries `keywords[N-1]` (keyword ROTATION — a fresh query pulls
     different inventory than page 2 of a starved query); `[]` once
     keywords run out. LinkedIn additionally hard-caps at 2 rounds inside
     the adapter (stateless `page > 2 → []`) so its worst-case per-run
     request volume stays strictly capped per the CLAUDE.md mitigation
     (2 search GETs + ≤2×limit detail GETs, delays and permanent
     rate-limit backoff unchanged). JSearch's free tier budgets 200
     requests/month: deeper rounds only fire when the run is starved.
   Cross-round dedup is by job id in the caller (`collect_new_jobs()` in
   `src/pipeline.py` for the UI; the same loop inline in the CLI
   orchestrator). Round progress is narrated in both surfaces.
3. Filter: deterministic dealbreaker + employment-type + salary-floor +
   posting-age filters BEFORE scoring. `guardrails.posting_is_recent()`
   drops anything older than `preferences.max_posting_age_days` — and,
   unlike the other filters, an UNDATED posting does NOT pass when this
   is set, since the point is a freshness guarantee.
3b. Archetype tag: `src/archetype.py` classifies every job that survives
   the filter into the user's own role taxonomy (`profile.yaml`
   `archetypes`, or `DEFAULT_ARCHETYPES` if that key is absent) —
   literal keyword substring matching, same discipline as
   `violates_dealbreakers()`, no LLM call. First configured archetype
   with a matching keyword wins; `None` ("Unclassified") if nothing
   matches. Stored as `job["archetype"]`, so it flows into Records
   automatically (`Records.upsert()` always persists the whole job
   dict) — no separate storage field needed. Surfaced as a tag on every
   job card and as a filter dimension in the Streamlit History page.
3c. Legitimacy check ("Block G"): `guardrails.legitimacy_check()` — a
   ghost-job/scam heuristic, always on, no LLM call. Every signal is
   either the posting's own text (scam-tell phrases, contractor language
   paired with no-benefits language, a junior/entry/intern title
   demanding 5+ years, a suspiciously short description, generic salary
   language with no stated range) or data JobScout already has in
   Records (the same normalized title+company reappearing across
   multiple past search runs under a new job id — the classic
   ghost-job-recycling pattern, detected via `_count_reposts()` with no
   date-gap math needed, since `make_job_id()` hashes the URL: a second
   Records entry with the same title+company can only exist if it truly
   arrived from a different posting). Weighted signals bucket into
   `high_confidence` / `caution` / `suspicious`. Stored as
   `job["legitimacy"]`, flows into Records the same way `archetype`
   does. Badge-only by default — flagged postings are shown with their
   reasons, not hidden, since a heuristic can misfire; a heuristic that
   silently removes a real job is worse than one that occasionally
   over-flags. `preferences.drop_suspicious_postings` (default false)
   opts into hard-dropping the `suspicious` tier before scoring, same
   category as a dealbreaker.
3d. Liveness verification (opt-in, off by default): `src/liveness.py`
   augments the recency filter for the specific failure mode
   `posting_is_recent()` can't see — a posting whose page returns HTTP
   200 but says "no longer accepting applications"/"position filled"/
   etc., which only shows up in the rendered page, not the API's
   `posted_at` field. Runs on `to_score` only (after the relevance sort
   and `--max-score` cap), never the full search-result set, so
   Playwright cost scales with the LLM scoring budget, not the whole
   pool. ONE headless Chromium instance per run, one page-load per job,
   closed after each check. Text-pattern matching only (a fixed list of
   generic "closed/filled/expired" phrases) — no site-specific
   scraping, no clicks, no form interaction. Fails OPEN on any
   error/timeout/missing-Playwright-install: a job is only ever dropped
   when a dead-posting phrase was positively found, never because the
   check itself failed. CLAUDE.md constraint 4 exception.
4. Score: Scoring Agent per job (masked resume + prefs) → weighted score,
   per-dimension breakdown, rationale (structured output, JSON schema).
   `--min-matches N` (CLI) turns the fixed-batch scoring pass into a
   goal-seeking loop: keep scoring jobs, in relevance order, up to the
   `--max-score` ceiling, until N score ≥ `draft_threshold` or the pool
   (or ceiling) is exhausted — printing a clear warning if the goal isn't
   met rather than silently returning fewer matches than asked for.
4b. Voice matching (optional, once per session/run): if the candidate
   has uploaded writing samples to `profile/documents/writing_samples/`,
   `scoring_agent.extract_voice_profile()` (skill:
   `skills/voice-matching/SKILL.md`) distills them — masked, same as the
   resume — into a compact style descriptor (sentence rhythm, formality,
   vocabulary; explicitly NOT facts or claims, that's resume-analysis's
   job on a different source). Empty when no samples exist — no LLM call
   is made in that case. The descriptor is passed to `draft_package`,
   `review_draft`, and `tailor_cv` and takes priority over the coarser
   `communication_style` preset when both are set, since a learned voice
   is strictly more specific than a category label.
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
10. Notion sync (opt-in): `src/notion_sync.py` mirrors Records into the
   user's OWN Notion database — a remote copy of data JobScout already
   keeps locally, via the official keyed API, so CLAUDE.md constraint 3
   (MCP read-only against job APIs) is untouched. **No LLM call**;
   deterministic mapping. Privacy line: cover letters (unmasked name
   after render) and all candidate PII never sync — only job metadata,
   score, decision, archetype, legitimacy tier, and the summary (which
   was generated from masked input), and the legitimacy REASONS as text
   (a field named "Red Flags"/"Flags"/"Risks"/"Concerns" is a common,
   better-fitting target than the bare tier). Adaptive schema: the
   database's own properties are fetched (`GET /v1/databases/{id}`,
   pinned Notion-Version 2022-06-28) and only name+type-compatible ones
   are filled; the sole requirement is the title property every database
   has. Verified against a real user database whose column names
   (`Job URL`, `Why it fits`, `Date found`, `Red flags`) differ from the
   suggested defaults — candidate name lists were extended per field to
   cover common real-world aliases. That database also had a `Status`
   column of Notion's distinct `status` type (not `select`) holding the
   user's OWN separate application-tracking workflow — confirmed
   `status`-type properties are NEVER written to, deliberately: the
   `decision` field only maps onto `select`-type columns, so a user's
   real hand-managed tracking stage can never be corrupted by a name
   coincidence. Created page ids are stored back into Records
   (`notion_page_id`) so re-syncs PATCH in place instead of duplicating.
   Triggered by the History-page button, or automatically at the end of
   an `--auto` run (scheduled runs land results where the human will
   see them). Requires `NOTION_API_KEY` + `NOTION_DATABASE_ID`; any
   failure degrades to a warning, never blocks the pipeline.
10b. HITL over Notion (`notion_sync.pull_decisions()`): Notion webhooks
   require a public HTTPS endpoint ("localhost is not reachable" per
   Notion's own docs) — unreachable for a local personal tool, so a live
   PUSH from Notion isn't possible. This is the honest pull equivalent:
   the human changes the Decision select cell in Notion (already
   populated with approved/rejected/skipped/undecided by sync), and
   JobScout reads it back via `GET /v1/pages/{id}` and applies it to
   Records + Memory — the identical decision class as clicking
   Approve/Reject/Skip in the UI or answering the CLI prompt (never a
   submission), so CLAUDE.md constraint 1's hard stop is untouched; this
   only adds an async surface for making that same human decision. Runs
   automatically at the START of every `--auto` run (before searching,
   so an already-decided job's memory state is current when the
   seen-filter runs) and on demand via a History-page button. Only
   entries already synced (carry a `notion_page_id`) are checked.
10c. Daily digest (`notion_sync.push_digest()`): one standalone Notion
   page per `--auto` run summarizing its outcome (jobs found/kept/
   scored/matched) as bulleted page content — not a job row, so it
   never pollutes the per-job table. Posted even on a 0-kept run, so a
   scheduled run leaves a trail on days it finds nothing new. No LLM
   call; built from counters the orchestrator already tracks.

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
9. **Ghost-job/scam heuristic ("Block G")** — `legitimacy_check()` (§2
   step 3c) protects the *user*, not the agent's own integrity: every
   signal is either the posting's own text or data already in Records,
   no LLM call, no prompt-injection surface. Badge-only by default, same
   "warn, don't silently remove" posture as the rest of JobScout's
   deterministic filters.

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
