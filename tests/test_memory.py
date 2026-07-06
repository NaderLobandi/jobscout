"""Spec: specs/scenarios.feature — "Rerun skips seen jobs"."""

from src.memory import Memory


def test_rerun_skips_seen_jobs(tmp_path):
    path = tmp_path / "mem.json"
    m1 = Memory(path)
    assert not m1.is_seen("job1")
    m1.mark_seen("job1", "ML Engineer", "approved")

    # New session, same file -> still remembered
    m2 = Memory(path)
    assert m2.is_seen("job1")
    assert m2.approved_count == 1


def test_corrupt_memory_starts_fresh(tmp_path):
    path = tmp_path / "mem.json"
    path.write_text("{not json")
    m = Memory(path)  # must not raise
    assert m.seen_count == 0
