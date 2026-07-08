"""Deterministic tests for archetype tagging.

Spec: specs/technical_design.md §2 step 3b — literal keyword substring
matching against the user's own (or default) taxonomy, no LLM call.
"""

from src.archetype import DEFAULT_ARCHETYPES, guess_archetype


def test_default_taxonomy_matches_research():
    assert guess_archetype("Research Scientist, Applied AI") == "Research"


def test_default_taxonomy_matches_applied_ml():
    assert guess_archetype("Machine Learning Engineer, Platform") == \
        "Applied ML / MLOps"


def test_default_taxonomy_matches_agentic():
    assert guess_archetype("Software Engineer, Agentic Workflows Team") == \
        "Agentic / LLM Systems"


def test_no_match_returns_none():
    assert guess_archetype("Regional Sales Director") is None


def test_case_insensitive():
    assert guess_archetype("RESEARCH SCIENTIST") == "Research"


def test_literal_phrase_not_bag_of_words():
    # Same discipline as matches_keywords()/violates_dealbreakers(): a
    # multi-word keyword must appear as a phrase, not as separately
    # scattered words, or unrelated postings would false-positive.
    text = "Data entry clerk. We use science-based hiring and value research into pricing."
    # "research" and "scientist" both appear but never as the phrase
    # "research scientist" — must not match Research.
    assert guess_archetype(text) is None


def test_custom_taxonomy_overrides_default():
    custom = [{"name": "Frontend", "keywords": ["react", "frontend"]}]
    assert guess_archetype("Senior Frontend Engineer (React)", custom) == "Frontend"
    # A term that WOULD match the default taxonomy must not match when a
    # custom taxonomy is supplied instead — custom fully replaces default.
    assert guess_archetype("Research Scientist", custom) is None


def test_first_matching_archetype_wins_priority_order():
    custom = [
        {"name": "A", "keywords": ["engineer"]},
        {"name": "B", "keywords": ["senior engineer"]},
    ]
    # Both keywords match; "A" is listed first, so it wins even though
    # "B" is the more specific phrase — priority is profile order, not
    # specificity.
    assert guess_archetype("Senior Engineer", custom) == "A"


def test_empty_text_returns_none():
    assert guess_archetype("") is None
    assert guess_archetype(None) is None


def test_default_archetypes_are_well_formed():
    for archetype in DEFAULT_ARCHETYPES:
        assert archetype["name"]
        assert archetype["keywords"]
