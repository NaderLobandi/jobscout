"""Deterministic tests for the normalized Job schema helpers.

Spec: specs/scenarios.feature — "Duplicate jobs across sources are merged".
"""

from schema import Job, dedupe, guess_employment_type, make_job_id, strip_html


def _job(url: str, title: str = "ML Engineer", company: str = "Acme",
         source: str = "remoteok") -> Job:
    return Job(id=make_job_id(url, title, company), title=title,
               company=company, url=url, source=source)


def test_dedupe_by_url():
    a = _job("https://boards.example/job/1")
    b = _job("https://boards.example/job/1?utm=x")  # same canonical URL
    assert len(dedupe([a, b])) == 1


def test_dedupe_same_role_across_sources():
    # Scenario: same job on RemoteOK and The Muse -> one record
    a = _job("https://remoteok.com/l/123", source="remoteok")
    b = _job("https://themuse.com/jobs/456", source="themuse")
    assert len(dedupe([a, b])) == 1  # merged on (title, company)


def test_dedupe_keeps_distinct_jobs():
    a = _job("https://x.example/1", title="ML Engineer")
    b = _job("https://x.example/2", title="Data Engineer")
    assert len(dedupe([a, b])) == 2


def test_strip_html():
    assert strip_html("<p>Build <b>ML</b>&nbsp;systems</p>") == "Build ML systems"


def test_strip_html_entity_escaped_tags():
    # Regression: Greenhouse's content=true field returns markup that is
    # itself HTML-entity-escaped ('&lt;div&gt;', not '<div>'). Decoding
    # must happen BEFORE tag-stripping, or the tag regex has nothing to
    # match and merely unescapes the tags back into literal, un-stripped
    # HTML that then flows straight through to the LLM.
    escaped = ("&lt;div class=&quot;content-intro&quot;&gt;"
              "&lt;h2&gt;&lt;strong&gt;About&lt;/strong&gt;&lt;/h2&gt;"
              "&lt;/div&gt;")
    result = strip_html(escaped)
    assert "<" not in result and "&lt;" not in result
    assert result == "About"


def test_strip_html_numeric_entities():
    # html.unescape() (not a hand-rolled entity list) handles arbitrary
    # numeric entities too, e.g. a right single quotation mark.
    assert strip_html("Anthropic&#8217;s mission") == "Anthropic’s mission"


def test_guess_employment_type():
    assert guess_employment_type("Summer Intern - ML") == "internship"
    assert guess_employment_type("Full-time role") == "full-time"
    assert guess_employment_type("whatever") == "unknown"
