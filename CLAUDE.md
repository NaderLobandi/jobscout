# JobScout — Agent Operating Rules

JobScout is a personal job-search concierge agent: it interviews the user,
searches many job boards through one MCP interface, scores jobs against the
user's resume and preferences, drafts application materials, and STOPS at a
human approval gate. It never auto-submits applications.

## Operating rules

- **Think before coding.** State assumptions explicitly. If a requirement is
  ambiguous, stop and ask rather than guessing silently.
- **Write the minimum code required.** No speculative features, no unrequested
  abstractions.
- **Make surgical edits.** Only touch lines necessary for the task. Match the
  existing style of the file you are editing.
- **Goal-driven execution.** Break tasks into steps with success criteria.
  Prefer writing a failing test first, then loop until it passes.
- **Never hardcode secrets.** All credentials come from environment variables.
  `.env` is gitignored; `.env.example` documents required vars with no values.
- **Comment design rationale.** Where course concepts are demonstrated, mark
  them with `COURSE CONCEPT:` comments so reviewers can find them.
- **specs/ is the source of truth.** If code and spec conflict, the spec wins:
  update the spec first, then regenerate the code.

## Hard product constraints (do not relax these)

1. The agent NEVER submits applications — the HITL gate in
   `src/guardrails.py` is a hard stop.
2. PII (name, email, phone, address) is masked before ANY LLM call and
   reinjected only at final local render.
3. The MCP server is read-only against job APIs. No write operations.
4. No scrapers. Only official/public JSON APIs (Indeed/Glassdoor are
   deliberately excluded — their ToS prohibit scraping).
   **One user-authorized exception (2026-07): LinkedIn**, via its
   unauthenticated public guest endpoint only. The owner explicitly chose
   this knowing it is against LinkedIn's ToS, because most postings appear
   there first. Mitigations are mandatory and must not be weakened:
   disabled by default; requires an explicit ToS-risk acknowledgment flag
   in the profile; never uses login credentials or cookies; GET-only;
   strictly capped request volume with delays between requests; backs off
   permanently for the run on any rate-limit response.
5. Dealbreaker/threshold filtering is deterministic Python, never LLM
   judgment, so it cannot be prompt-injected by job-posting text.
