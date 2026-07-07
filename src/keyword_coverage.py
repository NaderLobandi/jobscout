"""Deterministic keyword-coverage check: does the drafted cover letter
actually use the job posting's own terminology, or does it talk around
the requirements in different words?

COURSE CONCEPT (deterministic vs. LLM judgment): pure string matching,
no LLM call — same discipline as guardrails.violates_dealbreakers().
Cheap enough to run on every drafted letter automatically; flags gaps
rather than encouraging keyword stuffing (the cover-letter-drafting and
cover-letter-review skills already instruct against that — this is the
deterministic check that verifies it, rather than trusting the model's
own judgment about its own output).
"""

from __future__ import annotations

import re
from collections import Counter

# Standard English function words — not a hand-curated "job-posting
# boilerplate" list, which would be arbitrary. Function words carry no
# role-specific signal in any posting, technical or not.
_STOPWORDS = frozenset("""
a an and are as at be been being but by for from had has have if in into
is it its of on or our that the their them there these they this to was
we were what when where which who will with you your can may might must
shall should would could not no nor so than then too very just also other
about above after again all am any because before below between both
down during each few further here how more most now off once only over
same some such under until up while does did doing having those im ive
youre youll hes shes were theyre isnt arent wasnt werent hasnt havent
hadnt doesnt dont didnt wont wouldnt shant shouldnt cant cannot couldnt
mustnt lets thats whos whats heres theres whens wheres whys
""".split())

# Words that appear in nearly every job posting regardless of role or
# domain, so they carry no signal about what's SPECIFIC to this one —
# same justification as _STOPWORDS, just job-posting-domain rather than
# general English. Deliberately short: this isn't trying to be an
# exhaustive filter, just enough to stop generic filler from outranking
# genuinely distinctive terms by raw frequency.
_GENERIC_JOB_WORDS = frozenset("""
experience strong excellent ability abilities looking must plus join
working work team role company opportunity opportunities environment
ensure including etc years year candidate position skills skill
knowledge understanding familiarity background related responsibilities
requirements qualifications preferred required responsible strongly
""".split())

_MIN_LEN = 3
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+/#.\-]*[a-zA-Z0-9]|[a-zA-Z]")


def _tokenize(text: str) -> list[str]:
    """Lowercase words, keeping '.', '+', '#', '-' inside a token so
    compound tech terms ('Node.js', 'C++', 'CI/CD') survive as one unit."""
    return _TOKEN_RE.findall(text.lower())


def extract_keywords(description: str, title: str = "", top_n: int = 15) -> list[str]:
    """Top N significant terms from a job posting. Title words are
    always included first — they're the strongest signal a posting
    gives — then filled out with the most frequent non-stopword terms
    from the description."""
    title_words = [w for w in _tokenize(title)
                   if len(w) >= _MIN_LEN and w not in _STOPWORDS
                   and w not in _GENERIC_JOB_WORDS]
    keywords = dict.fromkeys(title_words)  # dedupe, preserve order

    counts = Counter(w for w in _tokenize(description)
                     if len(w) >= _MIN_LEN and w not in _STOPWORDS
                     and w not in _GENERIC_JOB_WORDS and w not in keywords)
    for word, _ in counts.most_common():
        if len(keywords) >= top_n:
            break
        keywords[word] = None
    return list(keywords)[:top_n]


def _mentions(keyword: str, text_lower: str) -> bool:
    """Exact match, or as a prefix of a longer word — catches plurals and
    -ing/-ed variants without real stemming (e.g. 'engineer' matches
    'engineering'). Not linguistically precise; cheap and good enough for
    a coverage nudge, not a guarantee."""
    if keyword in text_lower:
        return True
    return re.search(rf"\b{re.escape(keyword)}[a-z]", text_lower) is not None


def keyword_coverage(job: dict, cover_letter: str, top_n: int = 15) -> dict:
    """Compare a job posting's key terms against a drafted cover letter.
    Returns {"covered": [...], "missing": [...]}, both in the posting's
    own keyword order (title words first) for stable, meaningful display."""
    keywords = extract_keywords(job.get("description", ""), job.get("title", ""),
                                top_n)
    letter_lower = cover_letter.lower()
    covered, missing = [], []
    for k in keywords:
        (covered if _mentions(k, letter_lower) else missing).append(k)
    return {"covered": covered, "missing": missing}
