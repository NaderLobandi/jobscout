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

## `writing_samples/` — a different purpose, kept separate on purpose

Files placed directly in this folder feed **resume analysis** (facts:
skills, achievements, experience). Files placed in the `writing_samples/`
subfolder instead feed **voice matching** (style only: sentence rhythm,
formality, vocabulary — see `skills/voice-matching/SKILL.md`), so drafted
cover letters and tailored CVs sound like you actually wrote them. The
two are deliberately never mixed: `extract_profile_text()` doesn't
recurse into subfolders, so a writing sample never leaks into your
skills profile, and voice-matching never extracts facts from a sample —
just how it's written. Add samples via the Streamlit Profile page's
"Writing samples" uploader, or drop files directly into
`profile/documents/writing_samples/`. Same supported formats, same PII
handling, same gitignore coverage as above.
