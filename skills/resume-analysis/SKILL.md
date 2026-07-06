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

You will receive a PII-masked resume (placeholders like {{CANDIDATE_NAME}}
are intentional — never try to guess or reconstruct the real values).

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
- Do not invent skills that are not evidenced in the resume.
- Keep placeholders exactly as they appear.
