"""keyword_coverage: pure string matching, no LLM call — deterministic
and directly testable."""

from src.keyword_coverage import extract_keywords, keyword_coverage

JOB = {
    "title": "Machine Learning Engineer",
    "description": (
        "We are looking for a Machine Learning Engineer with strong "
        "PyTorch and distributed systems experience. You will build "
        "recommendation models and deploy them with Kubernetes. "
        "Experience with Node.js is a plus. PyTorch experience is a must."
    ),
}


def test_title_words_always_included():
    keywords = extract_keywords(JOB["description"], JOB["title"], top_n=20)
    assert "machine" in keywords
    assert "learning" in keywords
    assert "engineer" in keywords


def test_stopwords_excluded():
    keywords = extract_keywords(JOB["description"], JOB["title"], top_n=50)
    assert "with" not in keywords
    assert "a" not in keywords
    assert "is" not in keywords
    assert "you" not in keywords


def test_frequency_ranks_within_top_n():
    # "pytorch" appears twice in the description — should make the cut
    # even with a tight top_n, ahead of single-occurrence terms.
    keywords = extract_keywords(JOB["description"], JOB["title"], top_n=6)
    assert "pytorch" in keywords


def test_compound_tech_terms_survive_as_one_token():
    keywords = extract_keywords(JOB["description"], JOB["title"], top_n=50)
    assert "node.js" in keywords


def test_coverage_exact_and_missing():
    # top_n=15 comfortably covers all distinct content words in JOB's
    # short description — ties at frequency=1 are broken by first
    # occurrence, which is a reasonable, deterministic choice but not
    # one this test should assert an exact order for.
    letter = "I have deep PyTorch experience and have deployed with Kubernetes."
    result = keyword_coverage(JOB, letter, top_n=15)
    assert "pytorch" in result["covered"]
    assert "kubernetes" in result["covered"]
    assert "node.js" in result["missing"]
    assert set(result["covered"]) | set(result["missing"]) == set(
        extract_keywords(JOB["description"], JOB["title"], top_n=15))


def test_coverage_matches_morphological_variant():
    # letter says "engineering", posting title says "engineer" — should count
    result = keyword_coverage(JOB, "I have years of engineering leadership.",
                              top_n=20)
    assert "engineer" in result["covered"]


def test_empty_description_and_letter():
    result = keyword_coverage({"title": "", "description": ""}, "")
    assert result == {"covered": [], "missing": []}


def test_no_double_counting_between_covered_and_missing():
    result = keyword_coverage(JOB, "some generic text", top_n=10)
    assert not (set(result["covered"]) & set(result["missing"]))
