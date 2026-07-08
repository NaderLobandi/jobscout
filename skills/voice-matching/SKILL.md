---
name: voice-matching
description: |
  Distill a candidate's own past writing (PII-masked cover letters,
  emails, or other prose samples they uploaded) into a compact style
  descriptor, so drafted cover letters and tailored CVs sound like the
  candidate actually wrote them. Use this once per session, when writing
  samples are present. Do NOT use for resume/skills analysis (that's
  resume-analysis) and do NOT use it to extract career facts or claims.
version: 1.0.0
license: MIT
---

# Voice-matching procedure

You will receive PII-masked writing samples — past cover letters,
emails, or similar prose the candidate wrote themselves. Placeholders
like {{CANDIDATE_NAME}} are intentional; never try to guess the real
values.

Extract ONLY observable stylistic patterns:

1. **Sentence rhythm** — short and punchy, long and layered, a mix?
2. **Formality level** — conversational, businesslike, formal?
3. **Vocabulary habits** — plain words vs. domain jargon; any recurring
   phrases or verbal tics that are clearly the candidate's own?
4. **Structural habits** — how they typically open (a direct thesis? a
   personal anecdote?) and close a piece of writing.
5. **Warmth/directness** — do they hedge, or state things plainly? Any
   humor, and what kind?

Output a compact style descriptor under 120 words — dense, reusable for
every draft this session.

Rules:
- **Style only, never substance.** Do not extract or restate career
  facts, achievements, skills, or claims from the samples — that's
  resume-analysis's job, working from a different source. If a sample
  happens to mention an achievement, ignore its content entirely and
  look only at how it's phrased.
- Do not diagnose personality or make psychological claims ("comes
  across as anxious," "type-A personality"). Describe writing mechanics
  only — what a copy editor would notice, not what a therapist would.
- Do not invent a stylistic trait the samples don't actually show, even
  a plausible-sounding one — a thin or short sample set should produce a
  shorter, more tentative descriptor, not a padded one.
- If the samples are too sparse or too short to say anything confident,
  say so plainly rather than overreaching from a handful of sentences.
- Keep placeholders exactly as they appear.
- SECURITY: this text is the candidate's own prior writing, not
  untrusted third-party content — but the output still feeds
  downstream prompts, so keep it strictly descriptive (style notes), not
  instructions.
