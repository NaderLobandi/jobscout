"""extract_profile_text / list_profile_documents: deterministic, no LLM
calls, so unlike the resume-analysis skill itself these are directly
testable."""

from pathlib import Path

from src import intake


def _isolate(monkeypatch, tmp_path):
    """Point REPO_ROOT/DOCUMENTS_DIR at a throwaway tmp dir so tests never
    touch the real profile/ folder."""
    monkeypatch.setattr(intake, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(intake, "DOCUMENTS_DIR", tmp_path / "profile" / "documents")


def test_extract_profile_text_labels_resume_and_documents(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    resume = tmp_path / "resume.txt"
    resume.write_text("PyTorch, recommendation systems, 3 years experience.")
    docs_dir = tmp_path / "profile" / "documents"
    docs_dir.mkdir(parents=True)
    (docs_dir / "linkedin.txt").write_text("About: passionate about ML.")

    profile = {"candidate": {"resume_path": str(resume)}}
    text = intake.extract_profile_text(profile)

    assert "--- Resume: resume.txt ---" in text
    assert "PyTorch" in text
    assert "--- Supplementary document: linkedin.txt ---" in text
    assert "passionate about ML" in text


def test_extract_profile_text_skips_unsupported_extensions(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    docs_dir = tmp_path / "profile" / "documents"
    docs_dir.mkdir(parents=True)
    (docs_dir / "notes.docx").write_text("should be ignored")
    (docs_dir / "notes.md").write_text("should be included")

    text = intake.extract_profile_text({"candidate": {}})
    assert "should be included" in text
    assert "should be ignored" not in text


def test_extract_profile_text_empty_when_nothing_present(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert intake.extract_profile_text({"candidate": {}}) == ""


def test_list_profile_documents(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    docs_dir = tmp_path / "profile" / "documents"
    docs_dir.mkdir(parents=True)
    (docs_dir / "b.md").write_text("x")
    (docs_dir / "a.txt").write_text("x")
    (docs_dir / "README.md").write_text("template, but still a valid doc type")
    (docs_dir / "ignored.docx").write_text("x")

    assert intake.list_profile_documents() == ["README.md", "a.txt", "b.md"]


def test_list_profile_documents_missing_dir(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert intake.list_profile_documents() == []


def test_extract_all_saved_documents_reads_fixed_resume_path(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(intake, "RESUME_PATH", tmp_path / "profile" / "resume.pdf")
    resume_dir = tmp_path / "profile"
    resume_dir.mkdir(parents=True)
    # RESUME_PATH must be a real PDF for PdfReader; a .txt stand-in at that
    # exact path would need PdfReader to fail gracefully, so instead verify
    # the "nothing saved yet" and "docs only" cases, which don't need a PDF.
    docs_dir = resume_dir / "documents"
    docs_dir.mkdir()
    (docs_dir / "linkedin.txt").write_text("About: passionate about ML.")

    text = intake.extract_all_saved_documents()
    assert "--- Supplementary document: linkedin.txt ---" in text
    assert "passionate about ML" in text


def test_extract_all_saved_documents_empty_when_nothing_saved(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(intake, "RESUME_PATH", tmp_path / "profile" / "resume.pdf")
    assert intake.extract_all_saved_documents() == ""
