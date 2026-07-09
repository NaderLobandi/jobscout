# JobScout 🔭 your personal job-search concierge agent

![JobScout banner](./docs/banner.gif)

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
                 │  intake → search → filter → tag → score →    │
                 │  draft → HITL gate → memory                  │
                 └──────┬──────────────────────┬────────────────┘
              Claude API│                      │ MCP (stdio)
        ┌───────────────▼───────┐   ┌──────────▼──────────────────┐
        │ Specialist sub-agents │   │ Job-Search MCP Server       │
        │  · search (no LLM)    │   │  search_jobs                │
        │  · scoring + voice    │   │  get_job_details            │
        │  · drafting + CV      │   │  list_sources               │
        │  · insights           │   └──────────┬──────────────────┘
        └───────────────────────┘             │ concurrent fan-out, GET-only
          ┌──────────┬──────────┼──────────┬───────────┬─────────┬─────────┐
       RemoteOK   The Muse  Remotive  Arbeitnow  Greenhouse   Lever     Ashby
     (+ JSearch, Adzuna, USAJOBS with free keys · LinkedIn opt-in, see below)

  Guardrails wrap everything (src/guardrails.py):
  PII masking ⇄ unmasking · audit log · HITL hard stop · ghost-job/scam
  check (Block G) · Hunter.io contact lookup (opt-in, third-party PII)
  Memory (.jobscout_memory.json) dedupes across sessions.

  "tag" = archetype label + Block G legitimacy check (always on, no LLM).
  Opt-in extras not shown above: Playwright liveness verification before
  scoring, a learned voice profile shaping the draft, Hunter.io contact
  lookup after drafting — each off by default, each documented below.
```

The MCP server normalizes every board into one `Job` schema and dedupes by
URL and by (title, company) — the agent integrates with **one** tool surface
no matter how many boards exist behind it (the NxM integration problem).

## Course concepts demonstrated

| Concept | Where |
|---|---|
| **Multi-agent system** | Orchestrator + search/scoring/drafting/review/insights sub-agents (`src/agents/`) |
| **Custom MCP server** | `mcp-server/job_search_server.py`, stdio transport, official Python SDK |
| **Security features** | HITL gate, PII masking, audit log, least privilege, deterministic filters, ghost-job/scam heuristic, prompt-injection defense (`src/guardrails.py`) |
| **Agent Skills** | Seven SKILL.md skills with progressive disclosure (`skills/`) |
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

# Optional, only if you want Playwright liveness verification (off by
# default — see "Liveness Verification" below):
pip install playwright && playwright install chromium
```

Optional: drop your resume at `profile/resume.pdf`. For richer scoring,
also drop a LinkedIn export, past cover letters, or reference letters into
`profile/documents/` (see `profile/documents/README.md`) — everything
there is combined with your resume, masked the same way, before analysis.
On the **👤 Profile** page, a "🔍 Preview PDF text extraction" panel lets
you check what text actually got pulled out of your PDFs before any of it
reaches an LLM — useful for catching a scanned/image-only resume with no
real text layer. You can also drop past cover letters or emails into
`profile/documents/writing_samples/` (or upload them on the Profile
page) — see "Voice Matching" below.

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

- **👤 Profile** — full intake form: contact info, resume PDF upload +
  supplementary documents, a "🔍 Preview PDF text extraction" panel to
  verify what actually got pulled out of a PDF before it reaches an LLM,
  a **writing-samples uploader** that learns your actual tone instead of
  (or on top of) picking a `communication_style` preset (direct /
  collaborative / enthusiastic), target roles, preferences, dealbreakers,
  an **only-show-postings-from-the-last-N-days** filter, optional
  Playwright liveness verification, an opt-in to auto-drop postings the
  ghost-job/scam check flags "suspicious," per-dimension scoring
  weights, draft threshold, and job sources (including Lever/Ashby
  company tokens and the LinkedIn ToS acknowledgment). Saves to
  `profile/profile.yaml` (gitignored).
- **🚀 Run JobScout** — one click runs an **outcome-driven search** (it
  keeps deepening — rotating query keywords, paging further into boards
  that support it, up to 3 rounds — until your target number of NEW jobs
  survives the deterministic filters, instead of hoping one fixed fetch
  is enough) → deterministic filter →
  **archetype tagging** (🏷️ a role-category label — Research, Applied
  ML/MLOps, Agentic/LLM Systems, etc. — from a keyword taxonomy you can
  customize in `profile.yaml`, no LLM call) → **ghost-job/scam check**
  (🚩/⚠️ a Block G-style legitimacy badge, shown with its reasons — see
  below) → optional **🔎 liveness verification** (Playwright, off by
  default — see below) → resume
  analysis → per-job scoring with live progress, with an optional
  **"stop early once N found"** goal so it keeps scoring more jobs (up to
  your cost cap) instead of a fixed batch. Each match expands into a
  score-dimension breakdown, a drafted cover letter — in your own voice,
  if you've uploaded writing samples — that's already been through a
  second-pass reviewer critique + resume tweaks, a **tailored,
  ATS-optimized CV PDF** you can download directly, a deterministic
  **keyword-coverage check** against the posting (no LLM call — which of
  the posting's own key terms actually made it into the letter), an
  optional **"🔍 Find contacts"** button (recruiter/HR lookup via
  Hunter.io, see below), and **Approve / Reject / Skip** buttons — the
  HITL gate as a UI.
- **📚 History** — every job ever scored, with scores, decisions, the date
  you decided, the origin **publisher** for aggregator sources (e.g.
  `jsearch (Glassdoor)`), its **🏷️ archetype tag**, its **legitimacy
  badge** (Block G — 🚩/⚠️ shown with reasons when it's not a clean
  `high_confidence`), and saved cover letters (`.jobscout_records.json`,
  gitignored), plus a JSON export. Each entry expands into its full
  per-dimension score breakdown and draft, so the summary table's score
  always has somewhere to drill into — filter by decision (including
  `undecided`) or by **archetype** to see exactly what an unattended
  `--auto` run left for you to review, or to focus on one category of
  role at a time. Opens with a **recurring-gaps** view: which scoring
  dimension consistently drags you down across your whole history (pure
  aggregation, free, no LLM call), with an on-demand button to get a
  short, evidence-grounded suggestion for the weakest one.

### CLI

```bash
# First run interviews you and writes profile/profile.yaml (gitignored):
python -m src.orchestrator

# Search + deterministic filtering only — no LLM calls, no key needed:
python -m src.orchestrator --dry-run

# Cap LLM scoring calls per run (default 6):
python -m src.orchestrator --max-score 10

# Keep scoring (up to --max-score) until 5 jobs score >= draft_threshold,
# instead of stopping after a fixed batch:
python -m src.orchestrator --min-matches 5 --max-score 40

# Unattended (e.g. a daily cron job): no interactive prompt. Drafted
# packages are saved to .jobscout_records.json with NO decision — review
# and Approve/Reject/Skip later in the Streamlit UI, same as any other
# run. Nothing is ever auto-approved; this only defers the human gate,
# it does not remove it.
python -m src.orchestrator --auto --min-matches 5 --max-score 40

# Also look up recruiter/HR contacts at each match's company (requires
# HUNTER_API_KEY; display-only, JobScout never contacts anyone itself):
python -m src.orchestrator --find-contacts
```

A full run: searches all enabled boards concurrently via MCP → drops
already-seen jobs, wrong employment types, dealbreakers, salary-floor
misses, and (if `preferences.max_posting_age_days` is set) postings older
than that many days **in code, before any LLM call** → analyzes your
masked resume once → scores each job per dimension with rationale →
drafts a cover letter + resume tweaks + a tailored ATS CV PDF for jobs
above your threshold → a second, fresh-context reviewer agent critiques
the cover letter draft (unsupported claims, missed keywords, generic
phrasing, tone) and returns a revised letter → presents each package,
including the reviewer's notes and a link to the generated CV, at the
approval gate. You review, then apply yourself at the job URL.

**Tailored ATS CV.** Alongside the cover letter, JobScout restructures
your real resume — same employer names, titles, dates, and achievements,
just reordered and reframed toward this specific posting's terminology —
into a clean, single-column PDF built from core PDF fonts (not an
embedded/subset font, which is what breaks copy-paste text extraction in
some LaTeX-generated resumes). It never invents a job, degree, metric, or
skill that isn't already in your resume (`skills/cv-tailoring/SKILL.md`);
if a section is missing from your resume, it's omitted, not padded. PII
is unmasked only at the final local render, exactly like the cover
letter. Saved to `output/cvs/<job_id>.pdf` (gitignored).

**Only-recent-postings filter.** Set `preferences.max_posting_age_days`
(Profile page, or directly in `profile.yaml`) to drop anything older than
N days — deterministic, before any LLM call, same category as the
dealbreaker/employment-type/salary filters. A posting with no stated date
is dropped too when this is set, on purpose: an unstated date isn't a
reliable "recent enough."

**Liveness verification (opt-in).** The posting-age filter above can't
see everything — a page can return HTTP 200 while its own text says "no
longer accepting applications." Set `preferences.verify_liveness: true`
(Profile page checkbox, or CLI wizard) to have JobScout render each job
about to be scored with headless Chromium (Playwright) and check for
that. See "Liveness Verification" below for the full picture — it's off
by default and needs an extra install step.

**Running it daily.** JobScout has no built-in scheduler — `--auto` makes
a run safe to schedule, but starting the schedule itself is a decision
about your machine, not the repo, so it's opt-in via your OS's own tools.
Either way, open the Streamlit **History** page whenever you like to
review what it found (filter by `undecided`) — the run itself never
approves or submits anything.

#### macOS: `launchd` (recommended over cron on Mac — see note below)

Create `~/Library/LaunchAgents/com.jobscout.dailyrun.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jobscout.dailyrun</string>

    <key>ProgramArguments</key>
    <array>
        <string>/path/to/jobscout/.venv/bin/python</string>
        <string>-m</string>
        <string>src.orchestrator</string>
        <string>--auto</string>
        <string>--min-matches</string>
        <string>5</string>
        <string>--max-score</string>
        <string>40</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/path/to/jobscout</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>/path/to/jobscout/logs/launchd_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/path/to/jobscout/logs/launchd_stderr.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

Replace every `/path/to/jobscout` with your repo's absolute path (must
match exactly — launchd does not expand `~` or relative paths). What to
edit for common changes:

| Want to... | Edit |
|---|---|
| Run at a different time | `StartCalendarInterval` → `Hour` (0–23) / `Minute` |
| Run more than once a day | Change `StartCalendarInterval` to an **array** of `{Hour, Minute}` dicts |
| Find more/fewer matches before stopping | `--min-matches` value in `ProgramArguments` |
| Raise the cost ceiling if the goal is rarely met | `--max-score` value in `ProgramArguments` |
| Go back to a fixed batch instead of goal-seeking | Delete the `--min-matches`/`5` pair entirely |

Then load it (do this once, and again after every edit):

```bash
launchctl unload ~/Library/LaunchAgents/com.jobscout.dailyrun.plist 2>/dev/null  # ok if this errors the first time
launchctl load ~/Library/LaunchAgents/com.jobscout.dailyrun.plist
```

Other commands worth knowing:

```bash
# Pause it (stays installed, just won't fire):
launchctl unload ~/Library/LaunchAgents/com.jobscout.dailyrun.plist

# Resume it:
launchctl load ~/Library/LaunchAgents/com.jobscout.dailyrun.plist

# Check it's registered (a bare "-" in the PID column = loaded, not currently running):
launchctl list | grep jobscout

# Trigger it right now, without waiting for the scheduled time —
# the real way to test a change, since it exercises the actual plist:
launchctl start com.jobscout.dailyrun

# Remove it entirely:
launchctl unload ~/Library/LaunchAgents/com.jobscout.dailyrun.plist
rm ~/Library/LaunchAgents/com.jobscout.dailyrun.plist

# Watch what it's doing:
tail -f /path/to/jobscout/logs/launchd_stdout.log
```

**Sleep/wake:** modern macOS will generally run a missed `launchd` job
shortly after the Mac wakes up if it was asleep at the scheduled time —
but a fully powered-off Mac just skips that day; nothing catches up
retroactively.

#### Linux / anywhere else: cron

```cron
# crontab -e — daily at 8am, from the repo root
0 8 * * * cd /path/to/jobscout && .venv/bin/python -m src.orchestrator --auto --min-matches 5 --max-score 40 >> logs/cron.log 2>&1
```

Same flags, same behavior — cron just doesn't attempt to catch up a
missed run the way `launchd` does.

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
   The tailored CV PDF follows the identical pattern: `tailor_cv()` only
   ever sees masked text, and `src/cv_render.py` unmasks locally, once,
   at render time.
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

## Voice Matching

Upload past cover letters, emails, or anything else in your own words —
Profile page uploader, or drop files into
`profile/documents/writing_samples/` — and drafted cover letters and
tailored CVs will sound like you actually wrote them, not like the
default Claude voice.

How it stays honest: `skills/voice-matching/SKILL.md` distills your
samples into a compact descriptor of **style only** — sentence rhythm,
formality, vocabulary habits, how you open and close a piece of writing.
It's explicitly forbidden from extracting facts, achievements, or claims
from the samples (that's resume-analysis's job, working from your actual
resume) — a cover letter mentioning a real achievement doesn't let that
achievement leak into your skills profile through the back door, and
vice versa: `extract_profile_text()` never recurses into
`writing_samples/`, so a writing sample can't accidentally get read as
resume material either. The two pipelines are kept structurally
separate, not just instructed to behave.

If you upload samples, the learned voice profile overrides the
`communication_style` preset (direct/collaborative/enthusiastic) — a
real learned style is strictly more specific than a category label. No
samples uploaded, nothing changes: this is a pure opt-in, same
zero-behavior-change-when-unset discipline as every other optional
preference in this README.

## Archetype Tagging

Every job that survives the deterministic filter gets a 🏷️ role-category
tag — Research, Applied ML/MLOps, Agentic/LLM Systems, Data Science, and
so on — shown on its card and usable as a filter dimension in History.
It's plain keyword matching (`src/archetype.py`, first configured
category with a matching phrase wins), no LLM call, same substring
discipline as the dealbreaker filter. The taxonomy is yours to edit:
add an `archetypes:` list to `profile.yaml` (see
`profile/profile.example.yaml`) with your own category names and
keywords — omit it entirely to use the built-in default. A job matching
none of your categories is tagged "Unclassified," which is informative
in its own right (maybe your taxonomy needs a new category), not an
error.

## Ghost-Job / Scam Check ("Block G")

Every job that survives the deterministic filter also gets a legitimacy
check — always on, no opt-in needed, no LLM call. It looks for the same
signals a careful human would notice, all deterministic:

- **Scam-posting phrases** — "wire transfer," "processing fee," "gift
  card," "Telegram only," and similar tells.
- **Contractor risk** — "1099"/"independent contractor" language paired
  with "no benefits" language, flagged so you can verify the actual
  employment classification before applying.
- **Title/requirements mismatch** — a title that says "entry-level,"
  "junior," or "intern" while the description asks for 5+ years of
  experience.
- **Suspiciously thin descriptions** and **generic salary language**
  ("competitive salary") with no stated range.
- **Reposting** — the same title+company reappearing across multiple
  past JobScout runs under a new URL/job id — the classic ghost-job
  recycling pattern. This one uses data you already have: Records
  already stores one entry per unique job id (hashed from the URL), so
  a second entry with the same title+company can only exist because a
  genuinely different posting arrived later. No date-gap math needed.

Results in a tier — `high_confidence`, `caution`, or `suspicious` — shown
as a badge on the job card (Run and History) with its specific reasons,
never hidden by default: **a heuristic that can misfire should warn, not
silently disappear a real job.** Set
`preferences.drop_suspicious_postings: true` if you'd rather auto-drop
the `suspicious` tier before scoring instead (same category as a
dealbreaker); `caution`-tier postings are always shown regardless.

## Liveness Verification

Off by default. `preferences.max_posting_age_days` already catches most
stale postings from their stated date, but some ATS pages keep returning
HTTP 200 with the original content long after a role has closed — the
"no longer accepting applications" banner only exists in the rendered
page, not in any API's `posted_at` field. Turning on
`preferences.verify_liveness` has JobScout render each job **about to be
scored** (not the whole search-result set) with headless Chromium and
check its visible text against a fixed list of generic
closed/filled/expired phrases (`src/liveness.py`) — no LLM call, no
site-specific scraping, no clicks or form interaction, just reading text
off a page whose URL an official API already gave you.

Needs an extra install step most users won't want, which is exactly why
it's opt-in:

```bash
pip install playwright && playwright install chromium
```

Two things worth knowing:

- **It fails open, deliberately.** Any timeout, error, or missing
  Playwright install is treated as "assume live." The check's only job
  is to catch postings it can *positively* identify as dead — it must
  never risk dropping a real one because the check itself broke.
- **It's slower and heavier than everything else JobScout does.** A
  page render is not a plain API GET. That's why it's capped to jobs
  already selected for scoring (bounded by `--max-score`), not run
  against every search result.

## Contact Discovery

An optional, per-posting **"🔍 Find contacts"** button (Run and History
pages) or `--find-contacts` (CLI) looks up recruiter/HR contacts at a
job's company via [Hunter.io](https://hunter.io)'s Domain Search API —
name, title, work email, Hunter's own confidence score, and source
citation links. Off by default; requires a free `HUNTER_API_KEY`.

This is different from every other integration in this README in one
specific way: it's the only feature that stores **someone else's**
personal data rather than yours. Everything else about it stays
consistent with JobScout's security posture:

- **One official, keyed, GET-only API** — not a scraper, not LinkedIn
  people-search (a categorically different, and much riskier, ToS
  violation than the jobs guest endpoint JobScout already uses).
- **No LLM call anywhere in the lookup.** Hunter's data is already real
  and sourced — a model has nothing to add except hallucination risk.
  Ranking (hiring-adjacent titles first, then role overlap, then
  Hunter's confidence score) is deterministic Python.
- **Display-only.** JobScout shows you a contact with its source; it
  never emails, messages, or reaches out to anyone on its own — the
  same no-auto-action principle as the HITL gate, just applied to
  outreach instead of applications.
- Every contact carries its **source citation** so you can verify it
  yourself before reaching out.

## Notion sync (opt-in, off by default)

**"📤 Sync history to Notion"** (History page) mirrors your scored-job
records into your own Notion database — job title, company, score,
decision, archetype, legitimacy tier, source, URL, and the one-paragraph
summary. Unattended `--auto` runs sync automatically when configured, so
a scheduled JobScout run lands its results in a database you can check
from your phone, share, or turn into a kanban application tracker.

- **Your own workspace, official keyed API** — this is remote storage of
  data JobScout already keeps locally (`.jobscout_records.json`), not a
  write to any job platform. No LLM call anywhere in the sync.
- **Privacy line:** cover letters (which contain your unmasked name) and
  all personal details **never leave the machine** — only public job
  metadata, scores, and decisions are mirrored. The synced summary was
  generated from PII-masked input.
- **Adapts to your database.** JobScout reads your database's columns and
  fills whatever matches (title, plus any of these — several common
  aliases recognized per field): Company; Score/Match score; Decision;
  Archetype/Category; Legitimacy; Red Flags/Flags/Risks/Concerns (the
  Block G reasons as text, not just the tier); Source/Board;
  URL/Link/Posting/**Job URL**; Location; Summary/Notes/Analysis/**Why
  it fits**; Date/Scored/Updated/**Date found**. Missing columns are
  skipped, never an error. Re-syncs update existing pages instead of
  duplicating them.
- **Never touches a `status`-type property**, even one named "Decision"
  or "Status" — Notion's status columns commonly hold your OWN
  hand-managed workflow (e.g. Priority → Review → Applied → Archive).
  Only `select`-type columns get JobScout's decision written to them;
  your tracking stage is never at risk of being overwritten.

**HITL over Notion.** Notion webhooks require a public HTTPS endpoint —
its own docs say "localhost is not reachable" — so a live push from
Notion into a personal machine isn't possible. **"🔁 Pull decisions from
Notion"** (History page) is the honest equivalent: change a job's
Decision cell directly in Notion (from your phone, say), then pull, and
JobScout applies it here — the identical human decision as clicking
Approve/Reject/Skip in the app, never a submission, just made
asynchronously. `--auto` runs pull automatically at the START (so a
decision you made since the last run is already reflected before that
job could resurface in search).

**Daily digest.** Every `--auto` run posts one summary page to Notion
(found / kept / scored / matched) — even on a day it finds nothing new,
so a scheduled run always leaves a trail, not silence.

Setup (~2 minutes): create an internal integration at
[notion.so/my-integrations](https://www.notion.so/my-integrations), create
a database with whichever suggested columns you want, share the database
with the integration (**••• → Connections**), then set `NOTION_API_KEY`
and `NOTION_DATABASE_ID` (the 32-char hex segment in the database URL)
in `.env`.

## Deployment / path to production

Local container (works today):

```bash
docker build -t jobscout .
docker run -it --env-file .env -v $(pwd)/profile:/app/profile -v $(pwd)/logs:/app/logs -v $(pwd)/output:/app/output jobscout
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
- Adapter keyword matching is word-boundary phrase matching. By default
  JobScout **broadens** each target role (`src/query_expansion.py`) so
  "Machine Learning Engineer" also surfaces "ML Engineer", "Machine
  Learning Scientist", etc. — exact-phrase-only matching starved results
  to a handful that repeated every run. Broadening trades some precision
  for recall (the scorer ranks relevance downstream); set
  `preferences.strict_keyword_match: true` for verbatim-only matching.
  Internship-seeking profiles additionally get intern-targeted query
  compounds ("machine learning intern") so query-based boards actually
  ask for internships.
- Search is **outcome-driven**: up to 3 deepening rounds until the target
  number of new jobs survives the filters. Feed boards contribute round 1
  only (their whole inventory arrives at once); deeper rounds rotate
  keywords on LinkedIn (hard-capped at 2 rounds — its ToS-risk request
  budget is unchanged in spirit and strictly capped in code), JSearch,
  Adzuna, and USAJOBS, and page further into The Muse.
- Tier B adapters (Adzuna, USAJOBS) are implemented but exercised less than
  the keyless Tier A boards.
- Scoring costs tokens: default caps at 6 jobs/run (`--max-score` to change).
- Salary data is sparse on most boards; the salary-floor filter only fires
  when a posting states a max salary below your floor.
- **Employment-type detection is inference, not verification.** Lever and
  Ashby expose a genuine structured field, so those are exact. Everywhere
  else — including LinkedIn, where the `f_JT` search filter is *not*
  strictly enforced by LinkedIn itself — JobScout infers from the title
  and description text. This is reliable for internships specifically
  (real internships are almost always self-labeled), which is why an
  unlabeled ("unknown") posting is excluded outright when internship is
  your only selected type — but it's still text inference, not ground
  truth from the source.
- **A failed draft in `--auto` mode has no retry path yet.** If the
  drafting call errors (an occasional structured-output hiccup), the job
  is still marked "seen" — it won't resurface in a future search, and
  History has no "draft now" button for a score-only entry. Rare, but if
  you hit it, you'd need to draft that one manually another way.
- **The tailored CV is plain, deliberately.** Single column, core PDF
  fonts, no graphics or multi-column layout — that's an ATS-safety choice
  (fancy layouts are exactly what confuses parsers), not a limitation of
  the renderer, but it means it won't look like a designed resume
  template. It's still worth a skim before you send it, same as the
  cover letter.
- **Contact Discovery's relevance ranking is a heuristic, not a
  verified org chart.** It surfaces the most hiring-adjacent-looking
  title Hunter.io has on file for that company, not necessarily the
  actual recruiter for that specific posting. Hunter's free tier is
  also rate-limited (a handful of searches/month), so it's built to
  degrade to "no contacts found" rather than error, not to be your
  primary search method.
- **The ghost-job/scam check can both under- and over-flag.** It's a
  handful of deterministic signals, not a fraud model — a real posting
  with an unusually thin description or generic salary language can
  land in "caution" for no sinister reason, and a well-written scam
  that avoids the known tell phrases won't be caught. Treat the badge
  as "worth a second look," not a verdict — which is exactly why it's
  shown with its specific reasons and defaults to badge-only rather
  than silently dropping anything.

## Repo map

```
CLAUDE.md                    agent operating rules (spec-first, security)
specs/                       source of truth: design + BDD scenarios
skills/                      7 Agent Skills (progressive disclosure)
mcp-server/                  MCP server + normalized schema + 11 adapters
src/                         orchestrator, sub-agents, guardrails, memory,
                             intake, pipeline (UI helpers), records (history),
                             cv_render (ATS PDF layout), cv_pipeline (glue),
                             contacts (Hunter.io lookup), archetype (role tags),
                             liveness (opt-in Playwright dead-posting check)
app.py                       Streamlit UI (profile / run / history)
profile/profile.example.yaml committed template (real profile is gitignored)
profile/documents/           optional supplementary docs (gitignored except README)
output/cvs/                  generated ATS CV PDFs (gitignored)
evals/                       golden set + LLM-as-judge harness
tests/                       pytest for the deterministic parts
Dockerfile                   deployability
```
