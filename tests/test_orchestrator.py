"""Deterministic tests for the orchestrator's pre-LLM filter pipeline."""

from datetime import datetime, timedelta, timezone

from src.memory import Memory
from src.orchestrator import _explain_empty_filter, deterministic_filter


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

    kept, _ = deterministic_filter(jobs, profile, memory)

    assert [j["id"] for j in kept] == ["fresh"]


def test_max_posting_age_drops_undated_jobs_when_set(tmp_path):
    memory = Memory(tmp_path / "mem.json")
    profile = {"preferences": {"max_posting_age_days": 7}}
    jobs = [_job("undated", posted_days_ago=None)]

    kept, _ = deterministic_filter(jobs, profile, memory)
    assert kept == []


def test_max_posting_age_unset_keeps_everything(tmp_path):
    memory = Memory(tmp_path / "mem.json")
    profile = {"preferences": {}}  # no max_posting_age_days -> filter off
    jobs = [_job("undated", posted_days_ago=None), _job("old", posted_days_ago=400)]

    kept, _ = deterministic_filter(jobs, profile, memory)

    assert {j["id"] for j in kept} == {"undated", "old"}


def test_internship_only_drops_unlabeled_fulltime_jobs(tmp_path):
    # Regression for the real "Machine Learning Engineer @ Intel" case:
    # a full-time posting an upstream adapter couldn't positively label
    # (employment_type="unknown") must be dropped when internship is the
    # ONLY selected type — it must not fall through to the LLM scorer,
    # which has no way to override a wrong-but-plausible-looking match.
    memory = Memory(tmp_path / "mem.json")
    profile = {"preferences": {"employment_types": ["internship"]}}
    jobs = [
        _job("real_intern", posted_days_ago=1, title="ML Engineer Intern",
             employment_type="internship"),
        _job("unlabeled_fulltime", posted_days_ago=1,
             title="Machine Learning Engineer", employment_type="unknown"),
    ]

    kept, _ = deterministic_filter(jobs, profile, memory)

    assert [j["id"] for j in kept] == ["real_intern"]


def test_deterministic_filter_reports_drop_reasons(tmp_path):
    # The real "12 found, 0 kept" case: the caller needs to know WHY,
    # not just that nothing survived.
    memory = Memory(tmp_path / "mem.json")
    memory.mark_seen("old", "ML Engineer", "scored")
    profile = {"preferences": {"employment_types": ["internship"]}}
    jobs = [_job("old", posted_days_ago=1),
            _job("ft", posted_days_ago=1, employment_type="unknown")]

    kept, dropped = deterministic_filter(jobs, profile, memory)

    assert kept == []
    assert dropped["seen"] == 1
    assert dropped["type"] == 1


def test_explain_empty_filter_names_dominant_reason_and_lever():
    profile = {"preferences": {"employment_types": ["internship"]}}
    # "seen"-dominant → points at History / memory reset
    seen_msg = _explain_empty_filter(
        {"seen": 10, "type": 2, "dealbreaker": 0, "salary": 0, "stale": 0},
        profile)
    assert "already reviewed" in seen_msg
    assert "History" in seen_msg
    # "type"-dominant → names the actual configured types and the lever
    type_msg = _explain_empty_filter(
        {"seen": 0, "type": 5, "dealbreaker": 0, "salary": 0, "stale": 0},
        profile)
    assert "internship" in type_msg
    assert "employment types" in type_msg


def test_explain_empty_filter_handles_no_drops():
    # Defensive: an all-zero breakdown must still return a usable sentence.
    msg = _explain_empty_filter(
        {"seen": 0, "type": 0, "dealbreaker": 0, "salary": 0, "stale": 0},
        {"preferences": {}})
    assert "broaden" in msg.lower()
