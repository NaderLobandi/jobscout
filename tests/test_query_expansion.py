"""Tests for deterministic query expansion (src/query_expansion.py).

The point of expansion is recall: exact-phrase role titles match almost
nothing on real boards, so the same handful of jobs surfaced every run.
These lock in that broadening happens, stays deterministic, keeps the
primary role first (LinkedIn searches only keywords[0]), and doesn't emit
dangerous single-word tokens.
"""

from src.query_expansion import expand_keywords


def test_expands_multiword_role_into_core_and_abbreviation():
    kw = expand_keywords(["Machine Learning Engineer"])
    assert "machine learning engineer" in kw   # original kept
    assert "machine learning" in kw            # role-noun-stripped domain
    assert "ml" in kw                          # abbreviation


def test_original_role_stays_first_for_linkedin():
    # LinkedIn's adapter searches only keywords[0]; the user's primary
    # role must remain primary after expansion.
    kw = expand_keywords(["AI Researcher", "Data Scientist"])
    assert kw[0] == "ai researcher"


def test_deterministic_and_deduped():
    a = expand_keywords(["Machine Learning Engineer", "ML Engineer"])
    b = expand_keywords(["Machine Learning Engineer", "ML Engineer"])
    assert a == b                       # stable order, run to run
    assert len(a) == len(set(a))        # no duplicates


def test_seniority_stripped_to_core():
    kw = expand_keywords(["Senior Machine Learning Engineer"])
    assert "machine learning engineer" in kw
    assert "machine learning" in kw


def test_no_bare_single_domain_word_from_two_word_role():
    # "Data Scientist" must NOT collapse to a bare "data" (matches almost
    # anything); it expands via the abbreviation class instead.
    kw = expand_keywords(["Data Scientist"])
    assert "data" not in kw
    assert "data science" in kw


def test_abbreviation_input_expands_to_long_form():
    kw = expand_keywords(["ML Engineer"])
    assert "machine learning" in kw     # ml -> machine learning
    assert "ml" in kw


def test_empty_and_blank_roles_are_safe():
    assert expand_keywords([]) == []
    assert expand_keywords(["", "  "]) == []


def test_internship_profiles_get_intern_compounds_early():
    # Query-based boards rotate one keyword per round, and LinkedIn hard
    # caps at round 2 — so intern compounds must land right after the
    # primary role, not at the tail of the list.
    kw = expand_keywords(["Machine Learning Researcher", "AI Researcher"],
                         employment_types=["internship"])
    assert kw[0] == "machine learning researcher"   # primary stays primary
    assert kw[1] == "machine learning intern"        # round 2's query
    assert "ai intern" in kw[:6]


def test_intern_compounds_never_include_bare_intern():
    # A bare "intern" keyword would match internships in ANY field and
    # waste scoring budget on marketing/finance internships.
    kw = expand_keywords(["Machine Learning Engineer"],
                         employment_types=["internship"])
    assert "intern" not in kw
    assert "internship" not in kw


def test_non_internship_profiles_get_no_intern_compounds():
    kw = expand_keywords(["Machine Learning Engineer"],
                         employment_types=["full-time"])
    assert not any("intern" in k for k in kw)
