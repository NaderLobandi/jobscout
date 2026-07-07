---
name: resume-analysis
description: |
  Condense a (PII-masked) resume into a structured skills profile for
  downstream job scoring. Use this skill when a session starts, when the
  user updates their resume, or when scoring needs a skills inventory.
  Do NOT use for scoring individual jobs or for writing cover letters.
version: 1.0.0
license: MIT
---

# Resume analysis procedure

You will receive PII-masked text (placeholders like {{CANDIDATE_NAME}} are
intentional — never try to guess or reconstruct the real values). It may
be a resume alone, or a resume plus supplementary documents — a LinkedIn
export, past cover letters, reference letters — each marked with a
"--- Resume: ... ---" or "--- Supplementary document: ... ---" header so
you know where each claim comes from.

1. Extract a flat list of concrete technical skills (languages, frameworks,
   tools, platforms). Prefer the resume's own wording.
2. Extract domain experience (industries, problem areas).
3. Estimate seniority from years of experience and role titles
   (junior / mid / senior / staff).
4. List the 3–5 strongest, most differentiated achievements — quantified
   ones first.
5. Output a compact summary under 250 words. This summary will be reused
   for every job scored this session, so keep it dense and factual.

Rules:
- Do not invent skills that are not evidenced anywhere in the provided text.
- A claim stated as a concrete resume bullet is higher-confidence than one
  only implied by a LinkedIn "About" blurb, a cover letter's framing, or a
  reference letter's praise. When a skill or achievement comes primarily
  from one of those secondary sources rather than the resume itself, mark
  it "(inferred)" in the summary so downstream scoring and drafting can
  weight it appropriately — never present an inference as a stated fact.
- If supplementary documents conflict with the resume (different dates,
  titles, or claims), prefer the resume and don't mention the conflict —
  scoring only needs your best single synthesis, not a reconciliation.
- Keep placeholders exactly as they appear.
