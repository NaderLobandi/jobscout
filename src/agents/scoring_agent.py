"""Scoring Agent: resume analysis + per-job match scoring via Claude.

COURSE CONCEPT (multi-agent system): a specialist sub-agent with its own
skill, prompt, and structured-output contract. The orchestrator dispatches
it once per job.

SECURITY:
- Everything sent here is already PII-masked by the orchestrator.
- Job descriptions are UNTRUSTED input: wrapped in <job_posting> tags and
  the skill instructs the model to ignore embedded instructions
  (prompt-injection defense).
- The weighted total is computed in deterministic Python from the user's
  weights — the LLM scores dimensions but cannot set the final number.
"""

from __future__ import annotations

import json

from anthropic import Anthropic

from . import MODEL, load_skill, thinking_kwargs
from ..guardrails import audit

DIMENSIONS = ("skills_match", "role_title_match", "industry_match",
              "location_match", "seniority_match")

# Structured output schema: the API guarantees the response validates,
# so no fragile JSON-parsing of free text.
_DIM = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["score", "reason"],
    "additionalProperties": False,
}
SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "object",
            "properties": {d: _DIM for d in DIMENSIONS},
            "required": list(DIMENSIONS),
            "additionalProperties": False,
        },
        "summary": {"type": "string"},
    },
    "required": ["dimensions", "summary"],
    "additionalProperties": False,
}


def analyze_resume(client: Anthropic, masked_resume: str, summary: str) -> str:
    """One call per session: condense the masked resume into a dense skills
    profile that is reused for every job scored (token efficiency)."""
    audit("llm.analyze_resume", {"chars": len(masked_resume)})
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=load_skill("resume-analysis"),
        messages=[{
            "role": "user",
            "content": (
                f"Candidate self-summary: {summary or '(none)'}\n\n"
                f"Masked resume:\n{masked_resume or '(no resume provided)'}"
            ),
        }],
        **thinking_kwargs(),
    )
    return next(b.text for b in response.content if b.type == "text")


def score_job(client: Anthropic, skills_profile: str, preferences: dict,
              job: dict, weights: dict) -> dict:
    """Score one job. Returns dimensions, deterministic weighted total,
    and a plain-language summary."""
    audit("llm.score_job", {"job_id": job["id"], "title": job["title"]})
    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=load_skill("job-scoring"),
        output_config={"format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
        messages=[{
            "role": "user",
            "content": (
                f"CANDIDATE SKILLS PROFILE:\n{skills_profile}\n\n"
                f"CANDIDATE PREFERENCES:\n{json.dumps(preferences, indent=1)}\n\n"
                "<job_posting>\n"
                f"Title: {job['title']}\nCompany: {job['company']}\n"
                f"Location: {job['location']} ({job['remote']})\n"
                f"Type: {job['employment_type']}\n"
                f"Description: {job['description']}\n"
                "</job_posting>"
            ),
        }],
    )
    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)

    # SECURITY / correctness: weighted total in code, not LLM judgment.
    total = sum(
        result["dimensions"][d]["score"] * weights.get(d, 0.0)
        for d in DIMENSIONS
    )
    return {
        "dimensions": result["dimensions"],
        "summary": result["summary"],
        "score": round(total, 1),
    }
