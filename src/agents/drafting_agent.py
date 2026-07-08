"""Drafting Agent: tailored cover letter + resume tweaks for one job, then
a second-pass reviewer that critiques and revises the draft.

COURSE CONCEPT (multi-agent system): two specialist sub-agents in
sequence. The drafter writes; a separate reviewer call — fresh context,
no memory of drafting it — critiques for unsupported claims, missed
keywords, generic phrasing, and tone mismatch, then returns a revised
letter. A model rereading its own work in the same context tends to miss
what it just wrote; a fresh pass catches more of it. Dispatched only for
jobs that clear the deterministic draft threshold — no tokens spent on
weak matches, and only two calls, not a loop.

SECURITY: inputs are PII-masked; both the draft and the review operate on
masked text WITH placeholders ({{CANDIDATE_NAME}} etc.), and real values
are reinjected locally only after the human approves at the HITL gate —
never sent back through the model at any stage. Job text is untrusted and
wrapped in <job_posting> tags in both calls.
"""

from __future__ import annotations

import json

from anthropic import Anthropic

from . import MODEL, load_skill, thinking_kwargs
from ..guardrails import audit

def _style_line(communication_style: str, voice_profile: str = "") -> str:
    """Formats the optional tone guidance for the drafting/review/CV
    prompts. A learned voice_profile — distilled from the candidate's own
    uploaded writing samples — takes priority over the coarse
    communication_style preset when both are set: it's strictly more
    specific, and layering a generic label on top of a real learned
    style would just muddy the guidance. Empty string (no line at all)
    when neither is set, so an unset profile changes nothing about the
    prompt an existing setup would have produced before this feature
    existed."""
    if voice_profile:
        return ("\nWrite in the candidate's own voice, based on this "
                "style profile learned from their real writing samples:\n"
                f"{voice_profile}\n")
    if not communication_style:
        return ""
    return f"\nCommunication style: {communication_style}\n"


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "cover_letter": {"type": "string"},
        "resume_tweaks": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["cover_letter", "resume_tweaks"],
    "additionalProperties": False,
}


def draft_package(client: Anthropic, skills_profile: str, job: dict,
                  scoring: dict, communication_style: str = "",
                  voice_profile: str = "") -> dict:
    audit("llm.draft_package", {"job_id": job["id"], "title": job["title"]})
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=load_skill("cover-letter-drafting"),
        output_config={"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": (
                f"CANDIDATE SKILLS PROFILE (PII-masked):\n{skills_profile}\n"
                f"{_style_line(communication_style, voice_profile)}\n"
                f"WHY THIS JOB SCORED {scoring['score']}/100:\n{scoring['summary']}\n\n"
                "<job_posting>\n"
                f"Title: {job['title']}\nCompany: {job['company']}\n"
                f"Location: {job['location']} ({job['remote']})\n"
                f"Description: {job['description']}\n"
                "</job_posting>"
            ),
        }],
        **thinking_kwargs(),
    )
    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)
    return {
        "cover_letter": result["cover_letter"],
        "resume_tweaks": "\n".join(f"• {t}" for t in result["resume_tweaks"]),
    }


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "issues_found": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["unsupported_claim", "missed_keyword",
                                "generic_phrasing", "tone_mismatch"],
                    },
                    "detail": {"type": "string"},
                },
                "required": ["category", "detail"],
                "additionalProperties": False,
            },
        },
        "revised_cover_letter": {"type": "string"},
        "revision_summary": {"type": "string"},
    },
    "required": ["issues_found", "revised_cover_letter", "revision_summary"],
    "additionalProperties": False,
}


def review_draft(client: Anthropic, skills_profile: str, job: dict,
                 cover_letter: str, communication_style: str = "",
                 voice_profile: str = "") -> dict:
    """Fresh-context critique of an already-drafted cover letter. Call
    this AFTER draft_package() and BEFORE unmasking — it operates on the
    same masked text draft_package produced and must never see real PII.
    Returns issues_found (categorized critique), revised_cover_letter
    (the fixed version — use this, not the original draft), and
    revision_summary (one sentence, safe to show a human)."""
    audit("llm.review_draft", {"job_id": job["id"], "title": job["title"]})
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=load_skill("cover-letter-review"),
        output_config={"format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
        messages=[{
            "role": "user",
            "content": (
                f"CANDIDATE SKILLS PROFILE (PII-masked):\n{skills_profile}\n"
                f"{_style_line(communication_style, voice_profile)}\n"
                "<job_posting>\n"
                f"Title: {job['title']}\nCompany: {job['company']}\n"
                f"Description: {job['description']}\n"
                "</job_posting>\n\n"
                f"DRAFTED COVER LETTER TO REVIEW:\n{cover_letter}"
            ),
        }],
        **thinking_kwargs(),
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


CV_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "dates": {"type": "string"},
                    "location": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "company", "dates", "location", "bullets"],
                "additionalProperties": False,
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "degree": {"type": "string"},
                    "institution": {"type": "string"},
                    "dates": {"type": "string"},
                },
                "required": ["degree", "institution", "dates"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "skills", "experience", "education"],
    "additionalProperties": False,
}


def tailor_cv(client: Anthropic, masked_resume: str, skills_profile: str,
             job: dict, voice_profile: str = "") -> dict:
    """Restructure the candidate's REAL resume into ATS-friendly sections
    tailored to one job — selection, reordering, and rephrasing only,
    never new facts. Works from the full masked resume text (not just the
    condensed skills_profile) so the LLM has real dates/companies/bullets
    to draw from instead of inventing plausible-looking specifics.

    voice_profile (optional) applies mainly to the free-prose summary
    section — bullets and dates are terse structured facts with little
    room for "voice" — but is passed through regardless of section.

    Returns masked CV sections — src/cv_render.py unmasks locally, once,
    only at final PDF render."""
    audit("llm.tailor_cv", {"job_id": job["id"], "title": job["title"]})
    response = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=load_skill("cv-tailoring"),
        output_config={"format": {"type": "json_schema", "schema": CV_SCHEMA}},
        messages=[{
            "role": "user",
            "content": (
                f"CANDIDATE SKILLS PROFILE (PII-masked, condensed):\n"
                f"{skills_profile}\n"
                f"{_style_line('', voice_profile)}\n"
                f"FULL MASKED RESUME (source of truth for real facts):\n"
                f"{masked_resume or '(no resume provided)'}\n\n"
                "<job_posting>\n"
                f"Title: {job['title']}\nCompany: {job['company']}\n"
                f"Location: {job['location']} ({job['remote']})\n"
                f"Description: {job['description']}\n"
                "</job_posting>"
            ),
        }],
        **thinking_kwargs(),
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
