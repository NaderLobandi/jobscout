"""Session memory: which jobs have been seen/approved across runs.

COURSE CONCEPT (agent memory): one of the five agent components. A tiny
JSON state file is all JobScout needs — reruns skip jobs the user already
reviewed, so the agent never re-presents the same posting twice.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

MEMORY_PATH = Path(__file__).resolve().parent.parent / ".jobscout_memory.json"


class Memory:
    def __init__(self, path: Path = MEMORY_PATH):
        self.path = path
        self._state = {"seen": {}, "approved": {}}
        if path.exists():
            try:
                self._state = json.loads(path.read_text())
            except json.JSONDecodeError:
                pass  # corrupted memory -> start fresh rather than crash

    def is_seen(self, job_id: str) -> bool:
        return job_id in self._state["seen"]

    def mark_seen(self, job_id: str, title: str, decision: str = "presented") -> None:
        self._state["seen"][job_id] = {
            "title": title,
            "decision": decision,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if decision == "approved":
            self._state["approved"][job_id] = title
        self._save()

    @property
    def approved_count(self) -> int:
        return len(self._state["approved"])

    @property
    def seen_count(self) -> int:
        return len(self._state["seen"])

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state, indent=2))
