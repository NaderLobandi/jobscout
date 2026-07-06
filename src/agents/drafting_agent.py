"""Drafting Agent: tailored cover letter + resume tweaks for one job.

COURSE CONCEPT (multi-agent system): the second specialist sub-agent,
dispatched only for jobs that clear the deterministic draft threshold —
no tokens spent drafting for weak matches.

SECURITY: inputs are PII-masked; the letter is written WITH placeholders
({{CANDIDATE_NAME}} etc.) and real values are reinjected locally only
after the human approves at the HITL gate. Job text is untrusted and
wrapped in <job_posting> tags.
"""

from __future__ import annotations

import json

from anthropic import Anthropic

from . import MODEL, load_skill, thinking_kwargs
from ..guardrails import audit

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
                  scoring: dict) -> dict:
    audit("llm.draft_package", {"job_id": job["id"], "title": job["title"]})
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=load_skill("cover-letter-drafting"),
        output_config={"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": (
                f"CANDIDATE SKILLS PROFILE (PII-masked):\n{skills_profile}\n\n"
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
