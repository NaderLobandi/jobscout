"""Deterministic archetype tagging: classify a job into the user's own
configured role categories, for organizing History by role type.

COURSE CONCEPT (deterministic vs. LLM judgment): same discipline as
guardrails.violates_dealbreakers() / matches_keywords() — literal phrase
substring matching, not bag-of-words, so a posting can't accidentally
qualify for a category by mentioning unrelated words separately. Cheap
enough to tag every job that survives the deterministic filter, no LLM
call, no prompt-injection surface.

The taxonomy is USER-CONFIGURABLE (profile.yaml `archetypes`), not
hardcoded — one candidate's meaningful categories (research vs. applied
ML vs. agentic systems) are a different taxonomy than the next
candidate's (frontend vs. backend vs. platform). DEFAULT_ARCHETYPES below
is only the fallback when a profile doesn't define its own.
"""

from __future__ import annotations

DEFAULT_ARCHETYPES = [
    {"name": "Research", "keywords": [
        "research scientist", "research engineer", "research intern",
        "publication", "phd"]},
    {"name": "Applied ML / MLOps", "keywords": [
        "machine learning engineer", "ml engineer", "mlops",
        "model deployment", "production ml", "inference", "model training"]},
    {"name": "Agentic / LLM Systems", "keywords": [
        "agentic", "llm", "rag", "orchestration", "chatbot", "multi-agent",
        "agent"]},
    {"name": "Data Science", "keywords": [
        "data scientist", "analytics", "experimentation", "a/b test",
        "forecasting"]},
    {"name": "Software Engineering", "keywords": [
        "software engineer", "backend", "full stack", "distributed systems"]},
    {"name": "Product / Program", "keywords": [
        "product manager", "program manager", "roadmap", "stakeholder"]},
]


def guess_archetype(text: str, archetypes: list[dict] | None = None) -> str | None:
    """First configured archetype with a matching keyword wins (profile
    order = priority order). None ("Unclassified" in the UI) if nothing
    matches — a job not fitting the user's own categories is a real,
    informative outcome, not an error to paper over with a guess."""
    archetypes = DEFAULT_ARCHETYPES if archetypes is None else archetypes
    t = (text or "").lower()
    for archetype in archetypes:
        for kw in archetype.get("keywords", []):
            if kw.strip() and kw.strip().lower() in t:
                return archetype["name"]
    return None
