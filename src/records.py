"""Persistent run records: every scored job, its breakdown, drafts, and
the human's decision — the UI's history store.

Complements (doesn't replace) the two existing stores:
- .jobscout_memory.json  -> dedupe only ("have I seen this job id?")
- logs/audit.jsonl       -> security audit trail of every tool/LLM call
- .jobscout_records.json -> THIS: rich, human-facing history of results

Gitignored; local personal data only (job info is public, but cover
letters contain the user's unmasked name after render).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

RECORDS_PATH = Path(__file__).resolve().parent.parent / ".jobscout_records.json"


class Records:
    def __init__(self, path: Path = RECORDS_PATH):
        self.path = path
        self._entries: list[dict] = []
        if path.exists():
            try:
                self._entries = json.loads(path.read_text())
            except json.JSONDecodeError:
                self._entries = []  # corrupted -> start fresh, don't crash

    def upsert(self, job: dict, scoring: dict | None = None,
               drafts: dict | None = None, decision: str | None = None) -> None:
        """One record per job id; scoring/drafts/decision fill in as the
        pipeline progresses. Re-upserting updates the existing record."""
        entry = self._find(job["id"])
        if entry is None:
            entry = {"job": job, "first_seen": _now()}
            self._entries.append(entry)
        entry["job"] = job
        entry["updated"] = _now()
        if scoring is not None:
            entry["score"] = scoring.get("score")
            entry["dimensions"] = scoring.get("dimensions")
            entry["summary"] = scoring.get("summary")
        if drafts is not None:
            entry["cover_letter"] = drafts.get("cover_letter")
            entry["resume_tweaks"] = drafts.get("resume_tweaks")
            entry["review_notes"] = drafts.get("review_notes")
            entry["review_issues"] = drafts.get("review_issues")
            entry["keyword_coverage"] = drafts.get("keyword_coverage")
        if decision is not None:
            entry["decision"] = decision
        self._save()

    def get(self, job_id: str) -> dict | None:
        return self._find(job_id)

    def all(self) -> list[dict]:
        """Newest first."""
        return sorted(self._entries, key=lambda e: e.get("updated", ""),
                      reverse=True)

    def _find(self, job_id: str) -> dict | None:
        for entry in self._entries:
            if entry["job"]["id"] == job_id:
                return entry
        return None

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._entries, indent=2, default=str))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
