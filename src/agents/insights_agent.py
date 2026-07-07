"""Insights Agent: turns aggregate skill-gap statistics into a short,
actionable focus suggestion.

COURSE CONCEPT (multi-agent system): a fourth specialist sub-agent,
dispatched on demand (not per job) — it operates on aggregate stats from
src/insights.py (already-scored dimension numbers + reasons), never on a
raw job posting, so there is no untrusted-input surface here the way
there is for scoring/drafting.
"""

from __future__ import annotations

from anthropic import Anthropic

from . import MODEL, load_skill, thinking_kwargs
from ..guardrails import audit


def suggest_focus(client: Anthropic, gap: dict) -> str:
    """gap is one row from insights.aggregate_dimension_gaps() — the
    weakest dimension is the natural choice, but any row works."""
    audit("llm.suggest_focus", {"dimension": gap["dimension"],
                                "avg_score": gap["avg_score"]})
    examples = "\n".join(
        f"- scored {r['score']}/100 on {r['job_title']!r}: {r['reason']}"
        for r in gap["sample_reasons"]
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=load_skill("skill-gap-advisor"),
        messages=[{
            "role": "user",
            "content": (
                f"DIMENSION: {gap['dimension']}\n"
                f"Average score: {gap['avg_score']}/100 across {gap['count']} jobs\n"
                f"Was the single weakest dimension in {gap['weakest_count']} "
                "of those jobs.\n\n"
                f"Sample low-scoring instances:\n{examples}"
            ),
        }],
        **thinking_kwargs(),
    )
    return next(b.text for b in response.content if b.type == "text")
