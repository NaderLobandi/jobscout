"""Deterministic tests for Hunter.io contact discovery — no real network
calls, no LLM calls (the module makes none).

Spec: specs/technical_design.md §2 step 9; CLAUDE.md constraint 2
exception (third-party PII, opt-in, display-only).
"""

from src import contacts

# A representative Domain Search response: one hiring-adjacent contact,
# one unrelated exec, one role-title-overlapping engineer, one entry with
# no email (must be skipped).
PAYLOAD = {
    "data": {
        "emails": [
            {"value": "ceo@acme.com", "confidence": 99,
             "first_name": "Casey", "last_name": "Exec",
             "position": "CEO", "department": "executive", "sources": []},
            {"value": "recruiter@acme.com", "confidence": 80,
             "first_name": "Robin", "last_name": "Recruiter",
             "position": "Technical Recruiter", "department": "hr",
             "linkedin": "https://linkedin.com/in/robin",
             "sources": [{"uri": "https://acme.com/team"},
                        {"uri": "https://example.com/mention"}]},
            {"value": "eng@acme.com", "confidence": 90,
             "first_name": "Sam", "last_name": "Engineer",
             "position": "Machine Learning Engineer Manager",
             "department": "engineering", "sources": []},
            {"value": None, "confidence": 50, "position": "Nobody",
             "department": "sales", "sources": []},
        ]
    }
}


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _mock_get(monkeypatch, status_code=200, payload=PAYLOAD):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(status_code, payload)
    monkeypatch.setattr(contacts.httpx, "get", fake_get)


def test_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    assert contacts.available() is False
    assert contacts.find_contacts("Acme") == []


def test_available_with_key(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    assert contacts.available() is True


def test_hiring_adjacent_contact_ranks_first(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    _mock_get(monkeypatch)
    found = contacts.find_contacts("Acme", role_hint="Machine Learning Engineer")
    assert found[0]["name"] == "Robin Recruiter"
    assert found[0]["position"] == "Technical Recruiter"


def test_role_title_overlap_ranks_above_unrelated_exec(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    _mock_get(monkeypatch)
    found = contacts.find_contacts("Acme", role_hint="Machine Learning Engineer")
    names = [c["name"] for c in found]
    # engineer (role overlap) ranks above the CEO (neither hiring-adjacent
    # nor role-overlapping) even though the CEO has a higher confidence
    assert names.index("Sam Engineer") < names.index("Casey Exec")


def test_entries_without_email_are_skipped(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    _mock_get(monkeypatch)
    found = contacts.find_contacts("Acme")
    assert all(c["email"] for c in found)
    assert len(found) == 3  # the null-email entry is dropped


def test_sources_and_linkedin_surfaced(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    _mock_get(monkeypatch)
    found = contacts.find_contacts("Acme", role_hint="Machine Learning Engineer")
    recruiter = next(c for c in found if c["name"] == "Robin Recruiter")
    assert recruiter["linkedin"] == "https://linkedin.com/in/robin"
    assert recruiter["sources"] == ["https://acme.com/team",
                                    "https://example.com/mention"]


def test_limit_caps_results(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    _mock_get(monkeypatch)
    found = contacts.find_contacts("Acme", limit=1)
    assert len(found) == 1


def test_rate_limit_and_auth_errors_degrade_to_empty(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    for code in (401, 403, 429):
        _mock_get(monkeypatch, status_code=code)
        assert contacts.find_contacts("Acme") == []


def test_network_failure_degrades_to_empty(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")

    def raise_get(*a, **k):
        raise ConnectionError("boom")
    monkeypatch.setattr(contacts.httpx, "get", raise_get)
    assert contacts.find_contacts("Acme") == []


def test_no_company_short_circuits(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    assert contacts.find_contacts("") == []
