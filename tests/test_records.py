"""Records store: the UI's persistent history of scored jobs."""

from src.records import Records

JOB = {"id": "r1", "title": "ML Engineer", "company": "Acme",
       "url": "https://x.example/1", "location": "Remote", "remote": "remote",
       "source": "remoteok", "employment_type": "full-time", "description": ""}


def test_upsert_accumulates_fields(tmp_path):
    r = Records(tmp_path / "rec.json")
    r.upsert(JOB, scoring={"score": 81.5, "dimensions": {}, "summary": "good"})
    r.upsert(JOB, drafts={"cover_letter": "Dear team", "resume_tweaks": "• x"})
    r.upsert(JOB, decision="approved")

    entry = r.get("r1")
    assert entry["score"] == 81.5          # scoring survived later upserts
    assert entry["cover_letter"] == "Dear team"
    assert entry["decision"] == "approved"
    assert len(r.all()) == 1               # one record per job id


def test_records_persist_across_sessions(tmp_path):
    path = tmp_path / "rec.json"
    Records(path).upsert(JOB, scoring={"score": 50, "dimensions": {},
                                       "summary": "meh"})
    assert Records(path).get("r1")["score"] == 50


def test_corrupt_records_start_fresh(tmp_path):
    path = tmp_path / "rec.json"
    path.write_text("{not json")
    assert Records(path).all() == []  # must not raise


def test_unmask_works_without_prior_mask():
    """UI flow: a fresh PIIMasker must unmask drafts even when mask() was
    never called in the same process (Streamlit reruns per interaction)."""
    from src.guardrails import PIIMasker
    masker = PIIMasker(name="Jordan Rivera", email="j@example.com")
    letter = "Sincerely,\n{{CANDIDATE_NAME}} ({{CANDIDATE_EMAIL}})"
    out = masker.unmask(letter)
    assert "Jordan Rivera" in out and "j@example.com" in out
    assert "{{CANDIDATE_NAME}}" not in out
