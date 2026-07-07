# Additional profile documents (optional)

Drop supplementary documents here to give the resume-analysis agent
richer context beyond your resume PDF. Everything here is combined with
your resume, masked for PII the same way, then analyzed once per session
(see `src/intake.py::extract_profile_text`).

## What to put here

- A LinkedIn profile export (PDF)
- Past cover letters (`.pdf`, `.txt`, or `.md`) — useful for surfacing
  achievements or phrasing you've already used successfully
- Reference letters / recommendations (`.pdf`, `.txt`, or `.md`)

You can add as many as you like via the Streamlit UI's Profile page, or
just drop files directly into this folder.

## What's supported

- `.pdf`, `.txt`, `.md`
- Not supported: `.docx`, scanned/image-only PDFs — convert to a real
  text PDF first; a scanned page has no text layer to extract.

## PII caveat

JobScout automatically masks *your* declared name, email, phone, and any
email/phone-shaped text before any of this reaches the LLM. It does
**not** know a reference letter's *author* is someone else's PII — if a
reference letter names your recommender, consider redacting their name
yourself before adding it here, or leave it out.

This whole folder is gitignored except this file — nothing you add here
is ever committed.
