"""Deterministic tests for the orchestrator's pre-LLM filter pipeline."""

from datetime import datetime, timedelta, timezone

from src.memory import Memory
from src.orchestrator import deterministic_filter


def _job(job_id: str, posted_days_ago: int | None = None, **overrides) -> dict:
    posted_at = None
    if posted_days_ago is not None:
        posted_at = (datetime.now(timezone.utc)
                    - timedelta(days=posted_days_ago)).isoformat()
    job = {"id": job_id, "title": "ML Engineer", "company": "Acme",
           "url": f"https://x.example/{job_id}", "location": "Remote",
           "remote": "remote", "source": "remoteok",
           "employment_type": "full-time", "description": "",
           "posted_at": posted_at}
    job.update(overrides)
    return job


def test_max_posting_age_drops_stale_jobs(tmp_path):
    memory = Memory(tmp_path / "mem.json")
    profile = {"preferences": {"max_posting_age_days": 7}}
    jobs = [_job("fresh", posted_days_ago=2), _job("stale", posted_days_ago=30)]

    kept = deterministic_filter(jobs, profile, memory)

    assert [j["id"] for j in kept] == ["fresh"]


def test_max_posting_age_drops_undated_jobs_when_set(tmp_path):
    memory = Memory(tmp_path / "mem.json")
    profile = {"preferences": {"max_posting_age_days": 7}}
    jobs = [_job("undated", posted_days_ago=None)]

    assert deterministic_filter(jobs, profile, memory) == []


def test_max_posting_age_unset_keeps_everything(tmp_path):
    memory = Memory(tmp_path / "mem.json")
    profile = {"preferences": {}}  # no max_posting_age_days -> filter off
    jobs = [_job("undated", posted_days_ago=None), _job("old", posted_days_ago=400)]

    kept = deterministic_filter(jobs, profile, memory)

    assert {j["id"] for j in kept} == {"undated", "old"}
