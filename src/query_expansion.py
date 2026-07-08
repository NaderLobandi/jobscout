"""Deterministic query expansion for job search.

COURSE CONCEPT (retrieval design — recall vs. precision separation):
the keyword match against a job board is a RECALL filter — its job is to
surface every plausibly-relevant posting. PRECISION is the scorer's job:
it ranks each candidate 0-100 on skills/role/industry/etc. Exact-phrase
matching conflated the two — "Machine Learning Engineer" (verbatim) misses
a posting titled "ML Engineer" or "Machine Learning Scientist", so the same
handful of jobs surfaced every run and the seen-dedup then starved results.

This module widens the net deterministically (no LLM, no prompt-injection
surface): each target role expands into its seniority-stripped core, its
role-noun-stripped domain, and known abbreviation equivalents (ML ↔ machine
learning, AI ↔ artificial intelligence). Weak matches still surface but
simply score low downstream — they are no longer silently excluded.

Anchored word-boundary matching in adapters/base.matches_keywords() keeps
the short abbreviations ("ml", "ai") safe from substring false positives.
"""

from __future__ import annotations

import re

# Seniority/level modifiers stripped from the front of a role so
# "Senior Machine Learning Engineer" also searches as "Machine Learning
# Engineer" (and thus its core "machine learning").
_SENIORITY = {
    "senior", "sr", "sr.", "junior", "jr", "jr.", "staff", "principal",
    "lead", "entry", "entry-level", "mid", "mid-level", "associate",
    "chief", "head",
}

# Trailing role-type nouns. Dropping the noun yields the pure domain
# ("machine learning engineer" -> "machine learning"), but ONLY when at
# least two words remain, so we never emit a bare "data"/"software" that
# would match almost anything.
_ROLE_NOUNS = {
    "engineer", "scientist", "researcher", "developer", "analyst",
    "specialist", "manager", "architect", "consultant", "intern",
    "lead", "director",
}

# Abbreviation equivalence classes: if ANY member appears as a whole word
# in the role, all members are added as keywords. Kept intentionally small
# and high-signal — every abbreviation here is a strong domain term, not a
# generic word that would pull in unrelated roles.
_EQUIV_CLASSES: list[set[str]] = [
    {"machine learning", "ml"},
    {"artificial intelligence", "ai"},
    {"natural language processing", "nlp"},
    {"large language model", "large language models", "llm"},
    {"reinforcement learning", "rl"},
    {"computer vision"},
    {"data science", "data scientist"},
    {"software engineer", "software engineering", "swe"},
]

_WS_RE = re.compile(r"\s+")


def _word_in(needle: str, haystack: str) -> bool:
    """Whole-word (phrase) containment, mirroring adapters.matches_keywords."""
    left = r"\b" if needle[:1].isalnum() else ""
    right = r"\b" if needle[-1:].isalnum() else ""
    return re.search(left + re.escape(needle) + right, haystack) is not None


def expand_keywords(roles: list[str]) -> list[str]:
    """Broaden target roles into a recall-oriented keyword list.

    Originals come first and in order — LinkedIn's adapter searches only
    keywords[0], so the primary role must stay primary. The rest are
    appended deterministically (deduped, order-stable) so a given profile
    always produces the same query."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = _WS_RE.sub(" ", term).strip().lower()
        if len(term) >= 2 and term not in seen:
            seen.add(term)
            ordered.append(term)

    # Originals first, in the user's order.
    for role in roles:
        add(role)

    for role in roles:
        r = _WS_RE.sub(" ", (role or "")).strip().lower()
        if not r:
            continue
        words = r.split()
        # Strip leading seniority modifiers.
        i = 0
        while i < len(words) and words[i] in _SENIORITY:
            i += 1
        core = words[i:]
        if core:
            add(" ".join(core))
        # Drop a trailing role noun to get the pure domain (>= 2 words left).
        if len(core) >= 3 and core[-1] in _ROLE_NOUNS:
            add(" ".join(core[:-1]))
        # Abbreviation equivalences.
        for cls in _EQUIV_CLASSES:
            if any(_word_in(m, r) for m in cls):
                for member in cls:
                    add(member)

    return ordered
