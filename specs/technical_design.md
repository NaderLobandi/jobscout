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
5. Drafts a tailored cover letter + resume tweak suggestions for strong matches
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
│  scoring       │        │ greenhouse, (adzuna, usajobs) │
│  drafting      │        └───────────────────────────────┘
└────────────────┘
Guardrails wrap everything: PII masking in/out, audit log, HITL gate.
Memory (.jobscout_memory.json) dedupes across sessions.
```

### Agent loop (src/orchestrator.py)

Five components per the course framework: **model** (Claude API),
**tools** (MCP server), **memory** (JSON state file), **orchestration**
(the loop), **deployment** (Docker + docs).

1. Intake: if `profile/profile.yaml` missing/incomplete → run wizard
2. Search: Search Agent builds `SearchQuery` from profile → MCP `search_jobs`
3. Filter: deterministic dealbreaker + employment-type filters BEFORE scoring
4. Score: Scoring Agent per job (masked resume + prefs) → weighted score,
   per-dimension breakdown, rationale (structured output, JSON schema)
5. Draft: for jobs ≥ threshold → Drafting Agent → cover letter + resume tweaks
5b. Review: a second, fresh-context call (Drafting Agent's `review_draft`)
   critiques the masked cover letter for unsupported claims, missed
   keywords, generic phrasing, and tone mismatch, and returns a revised
   letter + a one-sentence summary. Runs on masked text, before unmask.
6. HITL gate: present package (including reviewer notes), hard stop, user
   applies manually
7. Memory: record seen/approved job IDs; reruns skip duplicates
8. Insights (on demand, UI History page only): `src/insights.py` computes
   average score per dimension across every Records entry ever scored —
   plain aggregation, no LLM call — surfacing which dimension recurringly
   drags the overall score down and how often it was the single weakest
   link per job. Insights Agent's `suggest_focus` turns the aggregate for
   the worst dimension into a short, evidence-grounded suggestion —
   spends a token only when the user explicitly asks for it.

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
| source | str | adapter name |
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

## 5. Sources

Tier A (no key): remoteok, themuse, remotive, arbeitnow, greenhouse
(per-company tokens). Tier B (free key, stubbed if not built): adzuna,
usajobs. Deliberately excluded: LinkedIn/Indeed/Glassdoor (no public API;
scraping violates ToS).

## 6. Testing strategy

- `tests/` (pytest, deterministic parts): adapter parsing from recorded JSON
  fixtures (no live calls), dedup, dealbreaker filtering, PII mask round-trip.
- `evals/` (non-deterministic parts): golden set of labeled job/profile pairs;
  LLM-as-judge checks the Scoring Agent's score lands in the expected band and
  the rationale mentions expected factors. Tests verify code; evals verify
  model behavior — you need both.
