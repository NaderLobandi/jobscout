"""Glue between the CV-tailoring LLM call and the local PDF renderer —
shared by the CLI orchestrator and the Streamlit UI so both produce a CV
the same way (COURSE CONCEPT: same pipeline as CLI, no drift).
"""

from __future__ import annotations

from pathlib import Path

from anthropic import Anthropic

from .agents import drafting_agent
from .cv_render import render_cv_pdf
from .guardrails import PIIMasker


def generate_cv_pdf(client: Anthropic, masked_resume: str, skills_profile: str,
                    job: dict, candidate: dict, masker: PIIMasker,
                    output_dir: Path) -> str:
    """Tailor + render + write to `output_dir/<job_id>.pdf`. Returns the
    path as a string (for storing in Records) — raises on failure, same
    as draft_package/review_draft, so callers can catch alongside them."""
    sections = drafting_agent.tailor_cv(client, masked_resume, skills_profile, job)
    pdf_bytes = render_cv_pdf(sections, candidate, masker)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{job['id']}.pdf"
    path.write_bytes(pdf_bytes)
    return str(path)
