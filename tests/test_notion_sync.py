"""Deterministic tests for the opt-in Notion sync — no real network
calls, no LLM calls (the module makes none).

Contract under test: adaptive schema mapping (fill only properties the
user's database actually has), create-then-update by stored page id,
graceful per-page failure, and — critically — cover letters / candidate
PII never appearing in anything sent to Notion.
"""

import json

from src import notion_sync
from src.records import Records

# A user database with SOME of the suggested columns (no Archetype, no
# Location) plus a custom-named title property — mapping must adapt.
SCHEMA_PAYLOAD = {
    "properties": {
        "Job": {"type": "title"},
        "Company": {"type": "rich_text"},
        "Score": {"type": "number"},
        "Decision": {"type": "select"},
        "URL": {"type": "url"},
        "Summary": {"type": "rich_text"},
    }
}

ENTRY = {
    "job": {"id": "j1", "title": "ML Intern", "company": "Acme, Inc.",
            "url": "https://jobs.example/1", "source": "linkedin",
            "location": "Remote", "archetype": "Applied ML / MLOps",
            "legitimacy": {"tier": "high_confidence"}},
    "score": 82.5,
    "decision": "approved",
    "summary": "Strong fit for the candidate's production ML background.",
    "cover_letter": "Dear team, I am Jordan Rivera, reach me at "
                    "jordan.rivera@example.com …",
    "updated": "2026-07-09T12:00:00+00:00",
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _configure(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret_test")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db123")


def test_unavailable_without_both_env_vars(monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    assert notion_sync.available() is False
    monkeypatch.setenv("NOTION_API_KEY", "k")
    assert notion_sync.available() is False  # database id still missing
    assert notion_sync.sync_records(None) is None  # no-op, no crash


def test_build_properties_adapts_to_the_databases_schema():
    schema = {k.lower(): (k, v["type"])
              for k, v in SCHEMA_PAYLOAD["properties"].items()}
    props = notion_sync.build_properties(ENTRY, schema)

    # Title lands in the database's own title property, whatever its name.
    assert props["Job"]["title"][0]["text"]["content"] == "ML Intern @ Acme, Inc."
    assert props["Score"]["number"] == 82.5
    assert props["Decision"]["select"]["name"] == "approved"
    assert props["URL"]["url"] == "https://jobs.example/1"
    assert "fit" in props["Summary"]["rich_text"][0]["text"]["content"]
    # Fields the database lacks are skipped, never an error.
    assert not any("archetype" in k.lower() for k in props)
    assert not any("location" in k.lower() for k in props)


def test_select_values_never_contain_commas():
    # Notion rejects commas in select option names.
    schema = {"company": ("Company", "select"), "job": ("Job", "title")}
    props = notion_sync.build_properties(ENTRY, schema)
    assert "," not in props["Company"]["select"]["name"]


def test_cover_letter_and_pii_never_sent(monkeypatch):
    _configure(monkeypatch)
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        return _FakeResponse(200, {"id": "page-1"})

    monkeypatch.setattr(notion_sync.httpx, "post", fake_post)
    schema = {k.lower(): (k, v["type"])
              for k, v in SCHEMA_PAYLOAD["properties"].items()}
    notion_sync.sync_entry(ENTRY, schema)

    body = json.dumps(sent[0])
    assert "Jordan Rivera" not in body
    assert "jordan.rivera@example.com" not in body
    assert "cover_letter" not in body


def test_sync_records_creates_then_updates(tmp_path, monkeypatch):
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert(ENTRY["job"], scoring={"score": 82.5, "dimensions": {},
                                          "summary": ENTRY["summary"]})
    calls = {"get": 0, "post": 0, "patch": 0}

    monkeypatch.setattr(notion_sync.httpx, "get",
                        lambda *a, **k: (calls.__setitem__("get", calls["get"] + 1),
                                         _FakeResponse(200, SCHEMA_PAYLOAD))[1])
    monkeypatch.setattr(notion_sync.httpx, "post",
                        lambda *a, **k: (calls.__setitem__("post", calls["post"] + 1),
                                         _FakeResponse(200, {"id": "page-1"}))[1])
    monkeypatch.setattr(notion_sync.httpx, "patch",
                        lambda *a, **k: (calls.__setitem__("patch", calls["patch"] + 1),
                                         _FakeResponse(200, {}))[1])

    # First sync: creates the page and remembers its id.
    assert notion_sync.sync_records(records) == (1, 0, 0)
    assert records.get("j1")["notion_page_id"] == "page-1"
    # Second sync: updates that page instead of duplicating it.
    assert notion_sync.sync_records(records) == (0, 1, 0)
    assert calls == {"get": 2, "post": 1, "patch": 1}


def test_sync_records_none_when_database_unreachable(tmp_path, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(notion_sync.httpx, "get",
                        lambda *a, **k: _FakeResponse(404))
    assert notion_sync.sync_records(Records(tmp_path / "r.json")) is None


def test_one_failed_page_never_blocks_the_rest(tmp_path, monkeypatch):
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert({**ENTRY["job"], "id": "j1"})
    records.upsert({**ENTRY["job"], "id": "j2"})

    outcomes = iter([_FakeResponse(500), _FakeResponse(200, {"id": "p2"})])
    monkeypatch.setattr(notion_sync.httpx, "get",
                        lambda *a, **k: _FakeResponse(200, SCHEMA_PAYLOAD))
    monkeypatch.setattr(notion_sync.httpx, "post",
                        lambda *a, **k: next(outcomes))

    assert notion_sync.sync_records(records) == (1, 0, 1)


# ---- HITL over Notion: pull_decisions --------------------------------------

def _page_response(decision_name):
    return _FakeResponse(200, {"properties": {
        "Decision": {"type": "select",
                    "select": {"name": decision_name} if decision_name else None}}})


def _routed_get(schema_payload, page_payloads):
    """Fake httpx.get that returns the database schema for /databases/
    and the right canned page for /pages/{id}, keyed by the id in the URL."""
    def handler(url, *a, **k):
        if "/databases/" in url:
            return _FakeResponse(200, schema_payload)
        page_id = url.rstrip("/").rsplit("/", 1)[-1]
        return page_payloads[page_id]
    return handler


def test_pull_decisions_applies_a_changed_decision(tmp_path, monkeypatch):
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert(ENTRY["job"])
    records.set_notion_page_id("j1", "page-1")

    monkeypatch.setattr(notion_sync.httpx, "get", _routed_get(
        SCHEMA_PAYLOAD, {"page-1": _page_response("approved")}))

    applied, checked = notion_sync.pull_decisions(records)
    assert (applied, checked) == (1, 1)
    assert records.get("j1")["decision"] == "approved"


def test_pull_decisions_updates_memory_when_provided(tmp_path, monkeypatch):
    from src.memory import Memory
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert(ENTRY["job"])
    records.set_notion_page_id("j1", "page-1")
    memory = Memory(tmp_path / "memory.json")

    monkeypatch.setattr(notion_sync.httpx, "get", _routed_get(
        SCHEMA_PAYLOAD, {"page-1": _page_response("rejected")}))

    notion_sync.pull_decisions(records, memory)
    assert memory.is_seen("j1")


def test_pull_decisions_skips_unchanged_and_unsynced_entries(tmp_path, monkeypatch):
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert({**ENTRY["job"], "id": "j1"})
    records.set_notion_page_id("j1", "page-1")
    records.upsert({**ENTRY["job"], "id": "j2"})  # never synced — no page id

    monkeypatch.setattr(notion_sync.httpx, "get", _routed_get(
        SCHEMA_PAYLOAD, {"page-1": _page_response("undecided")}))

    # j1's Notion cell still says "undecided", same as local -> no-op.
    # j2 has no notion_page_id -> not even checked.
    applied, checked = notion_sync.pull_decisions(records)
    assert (applied, checked) == (0, 1)


def test_pull_decisions_ignores_invalid_or_empty_cell(tmp_path, monkeypatch):
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert(ENTRY["job"])
    records.set_notion_page_id("j1", "page-1")

    monkeypatch.setattr(notion_sync.httpx, "get", _routed_get(
        SCHEMA_PAYLOAD, {"page-1": _page_response(None)}))
    applied, _ = notion_sync.pull_decisions(records)
    assert applied == 0


def test_pull_decisions_zero_when_database_has_no_decision_column(tmp_path, monkeypatch):
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert(ENTRY["job"])
    records.set_notion_page_id("j1", "page-1")

    no_decision_schema = {"properties": {"Job": {"type": "title"}}}
    monkeypatch.setattr(notion_sync.httpx, "get",
                        lambda *a, **k: _FakeResponse(200, no_decision_schema))
    assert notion_sync.pull_decisions(records) == (0, 0)


def test_pull_decisions_none_when_unavailable(monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    assert notion_sync.pull_decisions(None) is None


def test_pull_decisions_one_bad_page_does_not_block_the_rest(tmp_path, monkeypatch):
    _configure(monkeypatch)
    records = Records(tmp_path / "records.json")
    records.upsert({**ENTRY["job"], "id": "j1"})
    records.set_notion_page_id("j1", "page-1")
    records.upsert({**ENTRY["job"], "id": "j2"})
    records.set_notion_page_id("j2", "page-2")

    monkeypatch.setattr(notion_sync.httpx, "get", _routed_get(
        SCHEMA_PAYLOAD,
        {"page-1": _FakeResponse(500), "page-2": _page_response("skipped")}))

    applied, checked = notion_sync.pull_decisions(records)
    assert applied == 1 and checked == 2


# ---- Daily digest: push_digest ---------------------------------------------

def test_push_digest_posts_a_summary_page(monkeypatch):
    _configure(monkeypatch)
    sent = []

    monkeypatch.setattr(notion_sync.httpx, "get",
                        lambda *a, **k: _FakeResponse(200, SCHEMA_PAYLOAD))
    monkeypatch.setattr(notion_sync.httpx, "post",
                        lambda url, headers=None, json=None, timeout=None:
                            (sent.append(json), _FakeResponse(200, {"id": "digest-1"}))[1])

    page_id = notion_sync.push_digest(
        {"date": "2026-07-09", "found": 22, "kept": 8, "scored": 6, "matches": 3})

    assert page_id == "digest-1"
    body = sent[0]
    assert "2026-07-09" in body["properties"]["Job"]["title"][0]["text"]["content"]
    lines = [b["bulleted_list_item"]["rich_text"][0]["text"]["content"]
            for b in body["children"]]
    assert any("22" in l for l in lines)
    assert any("Matches" in l and "3" in l for l in lines)


def test_push_digest_none_when_unavailable_or_unreachable(monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    assert notion_sync.push_digest({}) is None

    _configure(monkeypatch)
    monkeypatch.setattr(notion_sync.httpx, "get",
                        lambda *a, **k: _FakeResponse(404))
    assert notion_sync.push_digest({}) is None
