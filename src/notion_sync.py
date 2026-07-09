"""Notion sync — mirror scored-job records into the user's own Notion
database (Tier B, opt-in, keyed).

This is remote storage of data JobScout already keeps locally
(.jobscout_records.json), written to the USER'S OWN workspace via
Notion's official keyed API — not a write to any job platform, so
CLAUDE.md constraint 3 (MCP read-only against job APIs) is untouched.
NO LLM call anywhere in this module: the mapping is deterministic.

PRIVACY: cover letters (which contain the candidate's unmasked name
after render) and all candidate PII are NEVER synced. Only public job
metadata, the score/decision, and the LLM summary (generated from
masked input, so it contains no PII) leave the machine.

Adaptive schema: the database's own properties are fetched first and
only matching ones are filled (by name, case-insensitive, compatible
type), so any database works — the sole requirement is the title
property every Notion database already has. Re-syncs UPDATE the page
created earlier (the page id is stored back into the record) instead
of duplicating it.

Pinned Notion-Version 2022-06-28: the classic one-call database API,
still fully supported through Notion's per-request version pinning
after the 2025-09 database/data-source split. Migrating to the
data-source API would mean GET database -> data_sources[0] -> GET data
source for the schema and `data_source_id` page parents.

HITL over Notion (pull_decisions): Notion webhooks require a public
HTTPS endpoint ("Endpoints in localhost are not reachable" — Notion's
own docs) — unreachable for a local personal tool, so a live PUSH from
Notion into JobScout isn't possible. pull_decisions() is the honest
equivalent: the human changes the "Decision" select cell in Notion
(already populated with approved/rejected/skipped/undecided from
sync_records), and JobScout reads that back and applies it locally on
the next check. This is the same class of action as clicking Approve in
the Streamlit UI or answering the CLI prompt — a genuine human decision,
recorded, never triggering any submission — so it does not relax
CLAUDE.md constraint 1's hard stop, it just adds a surface for making
that decision asynchronously.
"""

from __future__ import annotations

import os

import httpx

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
USER_AGENT = "JobScout/1.0 (personal job-search agent; educational project)"


def available() -> bool:
    return bool(os.getenv("NOTION_API_KEY") and os.getenv("NOTION_DATABASE_ID"))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
        "User-Agent": USER_AGENT,
    }


def fetch_schema() -> dict | None:
    """The database's properties as {lowercased name: (name, type)}, or
    None when the database can't be read (bad key, not shared with the
    integration, wrong id)."""
    try:
        resp = httpx.get(
            f"{API_BASE}/databases/{os.environ['NOTION_DATABASE_ID']}",
            headers=_headers(), timeout=15.0)
        resp.raise_for_status()
        props = resp.json().get("properties", {})
    except Exception:
        return None
    return {name.lower(): (name, spec.get("type", ""))
            for name, spec in props.items()}


def _text(value) -> dict:
    return {"rich_text": [{"type": "text",
                           "text": {"content": str(value)[:2000]}}]}


def _select(value) -> dict:
    # Notion select option names cannot contain commas.
    return {"select": {"name": str(value).replace(",", " ")[:100]}}


def _number(value) -> dict:
    return {"number": float(value)}


def _url(value) -> dict:
    return {"url": str(value)}


def _date(value) -> dict:
    return {"date": {"start": str(value)}}


# What a record can offer the database: for each field, the property
# names it may land in (first present wins), the property types it can
# fill, and the builder per type. Anything the database lacks is simply
# skipped — adaptive, never an error.
_FIELDS = [
    ("company", ("company",), {"rich_text": _text, "select": _select}),
    ("score", ("score", "match score"), {"number": _number}),
    ("decision", ("decision",), {"select": _select}),
    ("archetype", ("archetype", "category"), {"select": _select}),
    ("legitimacy", ("legitimacy",), {"select": _select}),
    ("source", ("source", "board"), {"select": _select}),
    ("url", ("url", "link", "posting"), {"url": _url}),
    ("location", ("location",), {"rich_text": _text, "select": _select}),
    ("summary", ("summary", "notes", "analysis"), {"rich_text": _text}),
    ("date", ("date", "scored", "updated"), {"date": _date}),
]


def _field_values(entry: dict) -> dict:
    job = entry["job"]
    return {
        "company": job.get("company"),
        "score": entry.get("score"),
        "decision": entry.get("decision") or "undecided",
        "archetype": job.get("archetype"),
        "legitimacy": (job.get("legitimacy") or {}).get("tier"),
        "source": job.get("source"),
        "url": job.get("url"),
        "location": job.get("location"),
        "summary": entry.get("summary"),
        "date": entry.get("updated") or entry.get("first_seen"),
    }


def build_properties(entry: dict, schema: dict) -> dict:
    """Deterministic record -> Notion properties mapping, filling only
    what the user's database actually has."""
    job = entry["job"]
    props: dict = {}
    # Every Notion database has exactly one title property, of any name.
    for name, ptype in schema.values():
        if ptype == "title":
            title = f"{job.get('title', '')} @ {job.get('company', '')}"
            props[name] = {"title": [{"type": "text",
                                      "text": {"content": title[:2000]}}]}
            break
    values = _field_values(entry)
    for field, candidates, builders in _FIELDS:
        value = values.get(field)
        if value in (None, ""):
            continue
        for candidate in candidates:
            name, ptype = schema.get(candidate, (None, None))
            if name and ptype in builders:
                props[name] = builders[ptype](value)
                break
    return props


def sync_entry(entry: dict, schema: dict) -> tuple[str | None, bool]:
    """Create or update the Notion page for one record. Returns
    (page_id, created) on success, (None, False) on failure — a failed
    page must never block the rest of the sync."""
    props = build_properties(entry, schema)
    page_id = entry.get("notion_page_id")
    try:
        if page_id:
            resp = httpx.patch(f"{API_BASE}/pages/{page_id}",
                               headers=_headers(),
                               json={"properties": props}, timeout=15.0)
            resp.raise_for_status()
            return page_id, False
        resp = httpx.post(
            f"{API_BASE}/pages", headers=_headers(),
            json={"parent": {"database_id": os.environ["NOTION_DATABASE_ID"]},
                  "properties": props},
            timeout=15.0)
        resp.raise_for_status()
        return resp.json().get("id"), True
    except Exception:
        return None, False


def sync_records(records) -> tuple[int, int, int] | None:
    """Sync every record; returns (created, updated, failed), or None
    when the database itself is unreachable (nothing was attempted).
    Page ids are stored back into the records store so future syncs
    update in place instead of duplicating."""
    if not available():
        return None
    schema = fetch_schema()
    if schema is None:
        return None
    created = updated = failed = 0
    for entry in records.all():
        page_id, was_created = sync_entry(entry, schema)
        if page_id is None:
            failed += 1
        elif was_created:
            created += 1
            records.set_notion_page_id(entry["job"]["id"], page_id)
        else:
            updated += 1
    return created, updated, failed


_VALID_DECISIONS = {"approved", "rejected", "skipped", "undecided"}


def pull_decisions(records, memory=None) -> tuple[int, int] | None:
    """Read back decisions the human made directly in Notion's Decision
    column and apply them locally — see module docstring for why this is
    poll/pull, not a live push. Only entries already synced (they carry a
    notion_page_id) are checked; nothing to reconcile for a job never
    pushed. Returns (applied, checked), or None if the database/schema
    itself can't be read at all.

    `memory` is optional so a caller without a Memory instance can still
    reconcile decisions in Records — but passing it keeps memory's
    seen/decision state (used by the deterministic seen-filter) in sync
    with a decision made remotely, exactly as every other decision path
    already does."""
    if not available():
        return None
    schema = fetch_schema()
    if schema is None:
        return None
    name, ptype = schema.get("decision", (None, None))
    if not name or ptype != "select":
        return 0, 0  # database has no compatible Decision column to read

    applied = checked = 0
    for entry in records.all():
        page_id = entry.get("notion_page_id")
        if not page_id:
            continue
        checked += 1
        try:
            resp = httpx.get(f"{API_BASE}/pages/{page_id}",
                             headers=_headers(), timeout=15.0)
            resp.raise_for_status()
            prop = resp.json().get("properties", {}).get(name) or {}
            notion_decision = ((prop.get("select") or {}).get("name")
                              or "").lower()
        except Exception:
            continue  # one unreadable page must not stop the rest
        if notion_decision not in _VALID_DECISIONS:
            continue  # empty cell, or the user typed something else
        job = entry["job"]
        if notion_decision != (entry.get("decision") or "undecided"):
            records.upsert(job, decision=notion_decision)
            if memory is not None:
                memory.mark_seen(job["id"], job["title"], notion_decision)
            applied += 1
    return applied, checked


def push_digest(stats: dict) -> str | None:
    """Create a standalone Notion page summarizing ONE run's outcome — a
    human-readable rollup, not a job row — so an unattended, scheduled
    run leaves a trail even on a day it finds nothing new. No LLM call:
    built entirely from counters the caller already tracks.

    stats: {"date": str, "found": int, "kept": int, "scored": int,
    "matches": int}. Returns the new page id, or None on failure/
    unavailable/no title property (every Notion database has one, so
    the last case only happens if the database itself is unreachable)."""
    if not available():
        return None
    schema = fetch_schema()
    if schema is None:
        return None
    title_name = next((n for n, t in schema.values() if t == "title"), None)
    if not title_name:
        return None

    lines = [
        f"Found: {stats.get('found', 0)} posting(s) across all boards",
        f"Kept after filters: {stats.get('kept', 0)} (new, not seen before)",
        f"Scored: {stats.get('scored', 0)}",
        f"Matches (>= draft threshold): {stats.get('matches', 0)}",
    ]
    props = {title_name: {"title": [{"type": "text", "text": {
        "content": f"📊 JobScout digest — {stats.get('date', '')}"}}]}}
    children = [{"object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [
                    {"type": "text", "text": {"content": line}}]}}
               for line in lines]
    try:
        resp = httpx.post(
            f"{API_BASE}/pages", headers=_headers(),
            json={"parent": {"database_id": os.environ["NOTION_DATABASE_ID"]},
                  "properties": props, "children": children},
            timeout=15.0)
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception:
        return None
