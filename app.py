"""JobScout Streamlit UI — profile intake, agent runs, and history.

Run:  streamlit run app.py

Same pipeline as the CLI (python -m src.orchestrator): the UI reuses the
identical MCP server, guardrails, and sub-agents, so both surfaces behave
the same. The HITL gate here is the Approve / Reject / Skip buttons —
JobScout still has no code path that submits an application anywhere.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from dotenv import load_dotenv

from src.agents import MODEL, drafting_agent, insights_agent, scoring_agent
from src.guardrails import PIIMasker
from src.insights import aggregate_dimension_gaps
from src.keyword_coverage import keyword_coverage
from src.intake import (DOCUMENTS_DIR, PROFILE_PATH, extract_all_saved_documents,
                        extract_profile_text, list_profile_documents, load_profile)
from src.memory import Memory
from src.orchestrator import _relevance_rank, deterministic_filter
from src.pipeline import fetch_jobs
from src.records import Records

REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")

st.set_page_config(page_title="JobScout", page_icon="🔭", layout="wide")

ALL_SOURCES = ["remoteok", "themuse", "remotive", "arbeitnow", "greenhouse",
               "lever", "ashby", "linkedin", "jsearch", "adzuna", "usajobs"]
REMOTE_PREFS = ["remote_or_hybrid", "remote_only", "hybrid", "onsite", "any"]
EMPLOYMENT_TYPES = ["full-time", "part-time", "internship", "contract"]
SENIORITY = ["junior", "mid", "senior", "staff"]
WEIGHT_DIMS = ["skills_match", "role_title_match", "industry_match",
               "location_match", "seniority_match"]

records = Records()
memory = Memory()


def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def score_badge(score: float, threshold: int) -> str:
    dot = "🟢" if score >= threshold else ("🟡" if score >= 50 else "🔴")
    return f"{dot} {score:.0f}"


def _source_label(job: dict) -> str:
    """Aggregator sources (jsearch) carry a distinct origin board in
    `publisher` — show it so Glassdoor/Indeed listings are identifiable."""
    src = job.get("source", "")
    pub = job.get("publisher")
    return f"{src} ({pub})" if pub else src


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🔭 JobScout")
    st.caption("Personal job-search concierge agent. Searches, scores, and "
               "drafts — **you** decide and apply.")
    page = st.radio("Navigate", ["👤 Profile", "🚀 Run JobScout", "📚 History"],
                    label_visibility="collapsed")
    st.divider()
    st.metric("Jobs reviewed", memory.seen_count)
    st.metric("Approved", memory.approved_count)
    st.caption(f"Model: `{MODEL}`")
    st.caption("Audit trail: `logs/audit.jsonl`")


# ---------------------------------------------------------------------------
# Page 1 — Profile
# ---------------------------------------------------------------------------

def page_profile() -> None:
    st.header("👤 Your profile")
    st.caption("Everything stays local (`profile/profile.yaml`, gitignored). "
               "Your name, email, and phone are masked with placeholders "
               "before any text reaches the LLM.")

    existing = load_profile() or {}
    cand = existing.get("candidate", {})
    prefs = existing.get("preferences", {})
    weights = existing.get("weights", {})
    sources = existing.get("sources", {})

    with st.form("profile_form"):
        st.subheader("About you")
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Full name", cand.get("name", ""))
        email = c2.text_input("Email", cand.get("email", ""))
        phone = c3.text_input("Phone", cand.get("phone", ""))
        summary = st.text_area("One-line summary of yourself (optional)",
                               cand.get("summary", ""), height=68)
        style_options = ["", "direct", "collaborative", "enthusiastic"]
        communication_style = st.selectbox(
            "Cover letter tone (optional)", style_options,
            index=style_options.index(cand.get("communication_style", ""))
            if cand.get("communication_style", "") in style_options else 0,
            help="Calibrates the drafting agent's tone. Blank = natural, "
                 "confident default.")

        resume_file = st.file_uploader("Resume (PDF)", type=["pdf"])
        current_resume = REPO_ROOT / "profile" / "resume.pdf"
        if current_resume.exists():
            st.caption(f"✅ Current resume on file: `{current_resume.name}` "
                       "(upload to replace)")

        extra_docs = st.file_uploader(
            "Additional documents (optional) — LinkedIn export, past cover "
            "letters, reference letters",
            type=["pdf", "txt", "md"], accept_multiple_files=True,
            help="Combined with your resume for richer grounding when "
                 "analyzing your skills. PII-masked the same way. A "
                 "reference letter's AUTHOR isn't detected as third-party "
                 "PII — redact their name yourself first if that matters "
                 "to you.")
        existing_docs = list_profile_documents()
        if existing_docs:
            st.caption(f"📎 Already on file: {', '.join(existing_docs)} "
                       "(uploads add to this list, don't replace it)")

        st.subheader("What you're looking for")
        c1, c2 = st.columns(2)
        target_roles = c1.text_input(
            "Target roles (comma-separated)",
            ", ".join(prefs.get("target_roles", ["Machine Learning Engineer"])))
        locations = c2.text_input(
            "Locations (comma-separated)",
            ", ".join(prefs.get("locations", ["Remote US"])))
        c1, c2, c3 = st.columns(3)
        employment_types = c1.multiselect(
            "Employment types", EMPLOYMENT_TYPES,
            default=[t for t in prefs.get("employment_types", ["full-time"])
                     if t in EMPLOYMENT_TYPES])
        seniority = c2.multiselect(
            "Seniority", SENIORITY,
            default=[s for s in prefs.get("seniority", ["mid", "senior"])
                     if s in SENIORITY])
        remote_pref = c3.selectbox(
            "Remote preference", REMOTE_PREFS,
            index=REMOTE_PREFS.index(prefs.get("remote_preference",
                                               "remote_or_hybrid"))
            if prefs.get("remote_preference") in REMOTE_PREFS else 0)
        c1, c2 = st.columns(2)
        industries = c1.text_input("Preferred industries (comma-separated)",
                                   ", ".join(prefs.get("industries", ["AI/ML"])))
        salary_floor = c2.number_input("Salary floor USD (0 = ignore)",
                                       min_value=0, step=5000,
                                       value=int(prefs.get("salary_floor_usd", 0)))
        max_posting_age = st.number_input(
            "Only show postings from the last N days (0 = ignore)",
            min_value=0, step=1,
            value=int(prefs.get("max_posting_age_days") or 0),
            help="Deterministic filter, applied before any LLM call. "
                 "Postings with no stated date are dropped when this is "
                 "set — an unstated date isn't a reliable 'recent enough.'")
        c1, c2 = st.columns(2)
        must_haves = c1.text_input("Must-haves (comma-separated, optional)",
                                   ", ".join(prefs.get("must_haves", [])))
        dealbreakers = c2.text_input(
            "Dealbreakers (comma-separated, optional)",
            ", ".join(prefs.get("dealbreakers", [])),
            help="Deterministic filter — jobs containing these phrases are "
                 "dropped before any LLM call.")

        st.subheader("Scoring")
        st.caption("Relative importance of each dimension (auto-normalized "
                   "to sum to 1.0). The weighted total is computed in code, "
                   "never by the LLM.")
        cols = st.columns(len(WEIGHT_DIMS))
        raw_weights = {}
        defaults = {"skills_match": 40, "role_title_match": 20,
                    "industry_match": 15, "location_match": 15,
                    "seniority_match": 10}
        for col, dim in zip(cols, WEIGHT_DIMS):
            raw_weights[dim] = col.slider(
                dim.replace("_", " "), 0, 100,
                int(weights.get(dim, defaults[dim] / 100) * 100))
        draft_threshold = st.slider(
            "Draft threshold — jobs scoring at or above this get a drafted "
            "application package", 0, 100,
            int(existing.get("draft_threshold", 70)))

        st.subheader("Job sources")
        enabled = st.multiselect(
            "Enabled boards", ALL_SOURCES,
            default=[s for s in sources.get(
                "enabled", ["remoteok", "themuse", "remotive", "arbeitnow",
                            "greenhouse", "lever", "ashby"]) if s in ALL_SOURCES],
            help="JSearch (Google for Jobs — includes Indeed/Glassdoor "
                 "postings), Adzuna, and USAJOBS also need free API keys "
                 "in .env")
        gh_companies = st.text_input(
            "Greenhouse companies to watch (board tokens, comma-separated)",
            ", ".join(sources.get("greenhouse_companies", ["anthropic"])))
        c1, c2 = st.columns(2)
        lever_companies = c1.text_input(
            "Lever companies to watch (board tokens, comma-separated)",
            ", ".join(sources.get("lever_companies", [])),
            help="Startup-heavy ATS. Postings label internships explicitly, "
                 "so JobScout detects them exactly instead of guessing.")
        ashby_companies = c2.text_input(
            "Ashby companies to watch (org names, comma-separated)",
            ", ".join(sources.get("ashby_companies", [])),
            help="The dominant ATS among recent YC-batch startups — good "
                 "coverage if you're hunting for internships there.")

        st.warning(
            "⚠️ **LinkedIn is different from every other source.** It has no "
            "official jobs API; JobScout can only reach it through LinkedIn's "
            "public no-login guest endpoint, and automated access to it "
            "violates LinkedIn's User Agreement. JobScout minimizes the risk "
            "— no login or cookies ever touch LinkedIn, requests are few and "
            "slow, and any rate-limit response stops all LinkedIn traffic "
            "for the run — but the ToS risk cannot be reduced to zero. "
            "Enabling it above does nothing until you also accept this here.")
        linkedin_ack = st.checkbox(
            "I understand automated access violates LinkedIn's ToS and I "
            "enable the LinkedIn source at my own risk",
            value=bool(sources.get("linkedin_tos_acknowledged", False)))

        saved = st.form_submit_button("💾 Save profile", type="primary")

    if saved:
        total = sum(raw_weights.values()) or 1
        profile = {
            "candidate": {
                "name": name, "email": email, "phone": phone,
                "resume_path": "./profile/resume.pdf", "summary": summary,
                "communication_style": communication_style,
            },
            "preferences": {
                "employment_types": employment_types or ["full-time"],
                "target_roles": _csv(target_roles),
                "seniority": seniority,
                "industries": _csv(industries),
                "locations": _csv(locations),
                "remote_preference": remote_pref,
                "salary_floor_usd": int(salary_floor),
                "max_posting_age_days": int(max_posting_age) or None,
                "visa_sponsorship_required": bool(
                    prefs.get("visa_sponsorship_required", False)),
                "must_haves": _csv(must_haves),
                "dealbreakers": _csv(dealbreakers),
            },
            "weights": {d: round(v / total, 4) for d, v in raw_weights.items()},
            "draft_threshold": int(draft_threshold),
            "sources": {
                "enabled": enabled,
                "greenhouse_companies": _csv(gh_companies),
                "lever_companies": _csv(lever_companies),
                "ashby_companies": _csv(ashby_companies),
                "linkedin_tos_acknowledged": bool(linkedin_ack),
            },
        }
        if resume_file is not None:
            current_resume.parent.mkdir(exist_ok=True)
            current_resume.write_bytes(resume_file.getvalue())
        if extra_docs:
            DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
            for f in extra_docs:
                # sanitize: strip any path component from the browser-supplied
                # filename before writing, so an upload can't traverse out of
                # profile/documents/
                safe_name = Path(f.name).name
                if safe_name:
                    (DOCUMENTS_DIR / safe_name).write_bytes(f.getvalue())
        PROFILE_PATH.parent.mkdir(exist_ok=True)
        PROFILE_PATH.write_text(yaml.safe_dump(profile, sort_keys=False))
        # A changed resume/profile/documents invalidates the cached analysis
        st.session_state.pop("skills_profile", None)
        st.success(f"Profile saved to `{PROFILE_PATH.relative_to(REPO_ROOT)}` "
                   "(gitignored). Head to **🚀 Run JobScout**.")
        if "linkedin" in enabled and not linkedin_ack:
            st.error("LinkedIn is in your enabled boards but the ToS-risk "
                     "acknowledgment box is unchecked — LinkedIn will stay "
                     "OFF until you check it and re-save.")

    st.divider()
    with st.expander("🔍 Preview PDF text extraction"):
        st.caption("Runs the same extraction used before scoring, on whatever "
                   "resume/documents are currently saved — catches a scanned "
                   "or image-only PDF with no real text layer before it "
                   "silently produces an empty or garbled profile.")
        if st.button("Extract now"):
            extracted = extract_all_saved_documents()
            if not extracted.strip():
                st.warning("No text extracted. Either no resume/documents are "
                           "saved yet, or the PDF has no selectable text layer "
                           "(common with scanned/image-only PDFs) — try "
                           "re-exporting it from a text editor instead.")
            else:
                st.text_area("Extracted text", extracted, height=300)
                st.caption(f"{len(extracted)} characters extracted.")


# ---------------------------------------------------------------------------
# Page 2 — Run
# ---------------------------------------------------------------------------

def _draft_for(package: dict, masker: PIIMasker, skills_profile: str,
               communication_style: str = "") -> None:
    job = package["job"]
    client = st.session_state["client"]
    with st.spinner(f"Drafting application package for {job['title']}…"):
        drafts = drafting_agent.draft_package(client, skills_profile, job,
                                              package, communication_style)
    with st.spinner("Second pass: reviewing the draft for a fresh critique…"):
        review = drafting_agent.review_draft(
            client, skills_profile, job, drafts["cover_letter"],
            communication_style)
        # SECURITY: unmask ONLY here — final local render for human eyes;
        # the unmasked text never goes back through the model.
        drafts["cover_letter"] = masker.unmask(review["revised_cover_letter"])
        drafts["review_notes"] = review["revision_summary"]
        drafts["review_issues"] = review["issues_found"]
        drafts["keyword_coverage"] = keyword_coverage(job, drafts["cover_letter"])
    records.upsert(job, drafts=drafts)
    st.rerun()


def _decide(job: dict, decision: str) -> None:
    records.upsert(job, decision=decision)
    memory.mark_seen(job["id"], job["title"], decision)
    st.rerun()


def render_package(package: dict, threshold: int, masker: PIIMasker,
                   skills_profile: str, communication_style: str = "") -> None:
    job = package["job"]
    record = records.get(job["id"]) or {}
    decision = record.get("decision")
    badge = {"approved": "✅ approved", "rejected": "❌ rejected",
             "skipped": "⏭ skipped"}.get(decision, "")
    label = (f"{score_badge(package['score'], threshold)} — "
             f"**{job['title']}** @ {job['company']}  {badge}")

    with st.expander(label, expanded=package["score"] >= threshold and not decision):
        meta, dims = st.columns([1, 2])
        with meta:
            st.markdown(f"**{job['company']}**")
            st.caption(f"{job['location'] or '—'} · {job['remote']} · "
                       f"via {_source_label(job)}")
            st.link_button("Open job posting ↗", job["url"])
            st.metric("Weighted score", f"{package['score']:.0f}/100")
        with dims:
            for dim, d in package["dimensions"].items():
                # structured outputs can't enforce a 0-100 range, so clamp
                # before st.progress (which raises outside [0, 1])
                clamped = max(0, min(int(d["score"]), 100))
                st.progress(clamped / 100,
                            text=f"**{dim.replace('_', ' ')} — {d['score']}**"
                                 f"  ·  {d['reason']}")
        st.markdown(f"*{package['summary']}*")
        st.divider()

        # Draft package (auto-suggested above threshold; on-demand below)
        if record.get("cover_letter"):
            st.text_area("✉️ Cover letter (edit before sending)",
                         record["cover_letter"], height=320,
                         key=f"letter_{job['id']}")
            st.markdown("**📄 Suggested resume tweaks**")
            st.markdown(record.get("resume_tweaks", ""))
            if record.get("review_notes"):
                with st.expander("🔍 Reviewer notes (second-pass critique)"):
                    st.caption(record["review_notes"])
                    for issue in record.get("review_issues") or []:
                        st.markdown(f"- **{issue['category'].replace('_', ' ')}** "
                                    f"— {issue['detail']}")
            kw = record.get("keyword_coverage")
            if kw and (kw["covered"] or kw["missing"]):
                total = len(kw["covered"]) + len(kw["missing"])
                st.caption(f"🔑 Keyword coverage: {len(kw['covered'])}/{total}")
                c1, c2 = st.columns(2)
                c1.markdown("✅ " + (", ".join(kw["covered"]) or "—"))
                c2.markdown("⚠️ " + (", ".join(kw["missing"]) or "—"))
        else:
            hint = ("" if package["score"] >= threshold else
                    " (below your draft threshold — drafting is optional)")
            if st.button(f"✍️ Draft cover letter + resume tweaks{hint}",
                         key=f"draft_{job['id']}"):
                _draft_for(package, masker, skills_profile, communication_style)

        # HITL gate — the human decides; JobScout never submits.
        st.info("🔒 JobScout never submits applications. If you approve, "
                "apply manually at the job URL above.")
        c1, c2, c3, _ = st.columns([1, 1, 1, 3])
        if c1.button("✅ Approve", key=f"approve_{job['id']}",
                     type="primary", disabled=decision == "approved"):
            _decide(job, "approved")
        if c2.button("❌ Reject", key=f"reject_{job['id']}",
                     disabled=decision == "rejected"):
            _decide(job, "rejected")
        if c3.button("⏭ Skip", key=f"skip_{job['id']}",
                     disabled=decision == "skipped"):
            _decide(job, "skipped")


def page_run() -> None:
    st.header("🚀 Run JobScout")
    profile = load_profile()
    if profile is None:
        st.warning("No profile yet — create one on the **👤 Profile** page first.")
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        st.error("`ANTHROPIC_API_KEY` is not set. Add it to `.env` "
                 "(see `.env.example`), then restart the app.")
        return

    prefs = profile.get("preferences", {})
    threshold = int(profile.get("draft_threshold", 70))
    st.caption(f"Searching for **{', '.join(prefs.get('target_roles', []))}** "
               f"across **{', '.join(profile.get('sources', {}).get('enabled', []))}** "
               f"· draft threshold **{threshold}**")

    c1, c2, c3 = st.columns([1, 1, 1])
    max_score = c1.number_input("Max jobs to score (cost cap)", 1, 40, 6)
    min_matches = c2.number_input(
        f"Stop early once this many ≥ {threshold} found (0 = off)",
        0, 20, 0,
        help="Keeps scoring more jobs, up to the cost cap above, instead "
             "of stopping after a fixed batch.")
    run = c3.button("🔎 Search & score", type="primary", width="stretch")

    if run:
        cand = profile.get("candidate", {})
        masker = PIIMasker(name=cand.get("name", ""),
                           email=cand.get("email", ""),
                           phone=cand.get("phone", ""),
                           address=cand.get("address", ""))
        from anthropic import Anthropic
        st.session_state["client"] = Anthropic()

        with st.status("Running the agent pipeline…", expanded=True) as status:
            st.write("🔎 Searching job boards via MCP (concurrent fan-out)…")
            jobs = fetch_jobs(profile)
            st.write(f"Found **{len(jobs)}** normalized, deduped jobs.")

            st.write("🛡️ Deterministic filters (before any LLM call)…")
            jobs = deterministic_filter(jobs, profile, memory)
            st.write(f"**{len(jobs)}** kept after seen/type/dealbreaker/"
                     "salary filters.")
            if not jobs:
                status.update(label="Nothing new to review", state="complete")
                st.session_state["scored"] = []
                st.warning("No new jobs to score — broaden your target roles "
                           "or review History.")
                return

            jobs.sort(key=lambda j: _relevance_rank(
                j, prefs.get("target_roles", [])), reverse=True)
            to_score = jobs[:int(max_score)]

            if "skills_profile" not in st.session_state:
                st.write("🧠 Analyzing your resume + supplementary "
                        "documents (PII-masked)…")
                resume_text = masker.mask(extract_profile_text(profile))
                summary = masker.mask(cand.get("summary", ""))
                st.session_state["skills_profile"] = scoring_agent.analyze_resume(
                    st.session_state["client"], resume_text, summary)

            goal = f", stopping early at {int(min_matches)} matches" if min_matches else ""
            st.write(f"⚖️ Scoring up to {len(to_score)} jobs{goal}…")
            bar = st.progress(0.0)
            scored = []
            hits = 0
            for i, job in enumerate(to_score):
                try:
                    result = scoring_agent.score_job(
                        st.session_state["client"],
                        st.session_state["skills_profile"],
                        prefs, job, profile.get("weights", {}))
                except Exception as exc:  # one bad job must not kill the run
                    st.write(f"⚠️ Scoring failed for {job['title']!r}: {exc}")
                    continue
                package = {"job": job, **result}
                scored.append(package)
                records.upsert(job, scoring=result)
                memory.mark_seen(job["id"], job["title"], "scored")
                bar.progress((i + 1) / len(to_score),
                             text=f"{result['score']:.0f} — {job['title']}")
                if result["score"] >= threshold:
                    hits += 1
                    if min_matches and hits >= int(min_matches):
                        st.write(f"✅ Reached the goal: {hits} matches "
                                f"≥ {threshold} after scoring {len(scored)}.")
                        break
            if min_matches and hits < int(min_matches):
                st.warning(
                    f"Only {hits}/{int(min_matches)} matches ≥ {threshold} "
                    f"after scoring all {len(scored)} available jobs (capped "
                    "by the cost cap above). Raise the cost cap, broaden "
                    "target roles/locations, or loosen the posting-age "
                    "limit on the Profile page to find more.")

            scored.sort(key=lambda p: p["score"], reverse=True)
            st.session_state["scored"] = scored
            st.session_state["masker_fields"] = {
                "name": cand.get("name", ""), "email": cand.get("email", ""),
                "phone": cand.get("phone", ""), "address": cand.get("address", ""),
            }
            status.update(label="Pipeline complete ✅", state="complete",
                          expanded=False)

    scored = st.session_state.get("scored")
    if not scored:
        return

    matches = sum(1 for p in scored if p["score"] >= threshold)
    m1, m2, m3 = st.columns(3)
    m1.metric("Jobs scored", len(scored))
    m2.metric(f"Matches ≥ {threshold}", matches)
    m3.metric("Top score", f"{scored[0]['score']:.0f}" if scored else "—")

    masker = PIIMasker(**st.session_state.get("masker_fields", {}))
    if "client" not in st.session_state:
        from anthropic import Anthropic
        st.session_state["client"] = Anthropic()
    communication_style = profile.get("candidate", {}).get("communication_style", "")
    for package in scored:
        render_package(package, threshold, masker,
                       st.session_state.get("skills_profile", ""),
                       communication_style)


# ---------------------------------------------------------------------------
# Page 3 — History
# ---------------------------------------------------------------------------

def render_skill_gaps(entries: list[dict]) -> None:
    """Recurring dimension gaps across every job ever scored — pure
    aggregation, no LLM call, always available for free. The narrative
    suggestion below it is a separate, explicit, on-demand LLM call."""
    gaps = aggregate_dimension_gaps(entries)
    if not gaps:
        return
    st.subheader("📈 Recurring gaps")
    st.caption("Where your scores consistently land, across every job "
              "JobScout has ever scored for you.")
    for row in gaps:
        clamped = max(0, min(int(row["avg_score"]), 100))
        st.progress(clamped / 100,
                   text=f"**{row['dimension'].replace('_', ' ')} — "
                        f"{row['avg_score']}/100 avg**  ·  scored on "
                        f"{row['count']} jobs  ·  weakest link in "
                        f"{row['weakest_count']} of them")

    worst = gaps[0]
    if st.button(f"🎯 Get suggestions for {worst['dimension'].replace('_', ' ')}",
                key="suggest_focus"):
        if "client" not in st.session_state:
            from anthropic import Anthropic
            st.session_state["client"] = Anthropic()
        with st.spinner("Thinking about what would actually move this number…"):
            suggestion = insights_agent.suggest_focus(st.session_state["client"], worst)
        st.info(suggestion)


DECISION_CATEGORIES = [
    ("undecided", "🕓 Undecided"), ("approved", "✅ Approved"),
    ("rejected", "❌ Rejected"), ("skipped", "⏭ Skipped"),
]


def _history_decide(job: dict, decision: str) -> None:
    records.upsert(job, decision=decision)
    memory.mark_seen(job["id"], job["title"], decision)
    st.rerun()


def render_history_entry(e: dict) -> None:
    """One record's full detail — score breakdown, draft, and Approve /
    Reject / Skip. Same decide buttons as the Run page, so a job you left
    undecided there isn't stranded once its buttons scroll out of that
    session — you can always come back and decide from here."""
    job = e["job"]
    score = e.get("score")
    decision = e.get("decision") or "undecided"
    badge = {"approved": "✅ approved", "rejected": "❌ rejected",
             "skipped": "⏭ skipped"}.get(decision, "🕓 undecided")
    score_label = f"{score:.0f}/100" if score is not None else "—"
    with st.expander(f"{score_label} — **{job['title']}** @ "
                     f"{job['company']}  {badge}"):
        meta, dims = st.columns([1, 2])
        with meta:
            st.caption(f"{job.get('location') or '—'} · "
                      f"{job.get('remote', '')} · via {_source_label(job)}")
            st.link_button("Open job posting ↗", job["url"],
                           key=f"hist_link_{job['id']}")
            st.metric("Weighted score", score_label)
            st.caption(f"Decision: **{decision}**")
            if e.get("decided_at"):
                st.caption(f"Date applied: {e['decided_at'][:10]}")
        with dims:
            for dim, d in (e.get("dimensions") or {}).items():
                clamped = max(0, min(int(d["score"]), 100))
                st.progress(clamped / 100,
                           text=f"**{dim.replace('_', ' ')} — {d['score']}**"
                                f"  ·  {d['reason']}")
        if e.get("summary"):
            st.markdown(f"*{e['summary']}*")

        if e.get("cover_letter"):
            st.divider()
            st.text_area("✉️ Cover letter", e["cover_letter"], height=280,
                         key=f"hist_letter_{job['id']}")
            if e.get("resume_tweaks"):
                st.markdown("**Resume tweaks**")
                st.markdown(e["resume_tweaks"])
            if e.get("review_notes"):
                st.markdown("**🔍 Reviewer notes**")
                st.caption(e["review_notes"])
            kw = e.get("keyword_coverage")
            if kw and (kw["covered"] or kw["missing"]):
                total = len(kw["covered"]) + len(kw["missing"])
                st.markdown(f"**🔑 Keyword coverage: "
                           f"{len(kw['covered'])}/{total}**")
                st.caption(f"✅ {', '.join(kw['covered']) or '—'}")
                st.caption(f"⚠️ {', '.join(kw['missing']) or '—'}")

        st.divider()
        c1, c2, c3 = st.columns(3)
        if c1.button("✅ Approve", key=f"hist_approve_{job['id']}",
                     type="primary", disabled=decision == "approved"):
            _history_decide(job, "approved")
        if c2.button("❌ Reject", key=f"hist_reject_{job['id']}",
                     disabled=decision == "rejected"):
            _history_decide(job, "rejected")
        if c3.button("⏭ Skip", key=f"hist_skip_{job['id']}",
                     disabled=decision == "skipped"):
            _history_decide(job, "skipped")


def page_history() -> None:
    st.header("📚 History")
    entries = records.all()
    if not entries:
        st.info("No records yet — run JobScout first.")
        return

    render_skill_gaps(entries)
    st.divider()

    df = pd.DataFrame([{
        "updated": e.get("updated", ""),
        "score": e.get("score"),
        "title": e["job"]["title"],
        "company": e["job"]["company"],
        "location": e["job"].get("location", ""),
        "source": e["job"].get("source", ""),
        "publisher": e["job"].get("publisher") or "",
        "decision": e.get("decision") or "undecided",
        "date_applied": (e.get("decided_at") or "")[:10],
        "url": e["job"]["url"],
    } for e in entries])
    st.dataframe(
        df, width="stretch", hide_index=True,
        column_config={
            "url": st.column_config.LinkColumn("posting", display_text="open ↗"),
            "score": st.column_config.NumberColumn(format="%.0f"),
            "date_applied": st.column_config.TextColumn("date applied"),
            "publisher": st.column_config.TextColumn(
                "publisher", help="Origin board for aggregator sources "
                "(e.g. Glassdoor via jsearch)"),
        })

    st.subheader("🔍 Job details")
    st.caption("Grouped by decision. Undecided is where a job lands if "
              "you never clicked Approve/Reject/Skip on the Run page (or "
              "it came from an unattended `--auto` run) — decide on it "
              "here any time. Every tab's buttons work the same, so you "
              "can change your mind later too.")

    buckets: dict[str, list[dict]] = {key: [] for key, _ in DECISION_CATEGORIES}
    for e in entries:
        buckets[e.get("decision") or "undecided"].append(e)

    tabs = st.tabs([f"{label} ({len(buckets[key])})"
                   for key, label in DECISION_CATEGORIES])
    for tab, (key, _) in zip(tabs, DECISION_CATEGORIES):
        with tab:
            if not buckets[key]:
                st.caption("Nothing here.")
            for e in buckets[key]:
                render_history_entry(e)

    st.download_button(
        "⬇️ Export all records (JSON)",
        data=json.dumps(records.all(), indent=2, default=str),
        file_name="jobscout_records.json", mime="application/json")


# ---------------------------------------------------------------------------

if page == "👤 Profile":
    page_profile()
elif page == "🚀 Run JobScout":
    page_run()
else:
    page_history()
