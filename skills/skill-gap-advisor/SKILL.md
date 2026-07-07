---
name: skill-gap-advisor
description: |
  Turn aggregate scoring statistics across a candidate's job-search
  history into a short, actionable "what to focus on next" narrative.
  Use this skill when the user has scored enough jobs to show a
  recurring weak dimension and wants concrete advice, not just numbers.
  Do NOT use for scoring an individual job or drafting application
  materials.
version: 1.0.0
license: MIT
---

# Skill-gap advisory procedure

You will receive aggregate statistics for ONE scoring dimension across
many past job matches: its average score, how many jobs it was scored
on, how often it was the single weakest dimension for a job, and a few
sample per-job scores + reasons.

1. Identify the concrete, recurring pattern behind the low average — not
   "skills need improvement" in general, but WHAT specifically (a named
   technology, a location constraint, a seniority mismatch) recurs
   across the sample reasons.
2. Give 2-3 specific, actionable suggestions tied to that pattern — a
   skill to build, a resume framing change, or a search-preference
   adjustment (e.g., broadening locations) — whichever the evidence
   actually supports.
3. Keep it under 120 words. This is a nudge, not a report.

Rules:
- Ground every suggestion in the actual sample reasons given — invent
  nothing, even to sound more actionable than the data supports.
- If the sample reasons point to a structural mismatch the candidate
  can't fix by learning something (e.g., a location preference clashing
  with onsite-only postings), say so plainly rather than forcing a
  skill-building suggestion that doesn't fit the evidence.
