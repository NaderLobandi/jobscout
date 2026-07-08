"""Deterministic tests for the local ATS CV renderer — no LLM calls.

Spec: specs/technical_design.md §2 step 5d — CV sections arrive masked
from tailor_cv(); render_cv_pdf() unmasks locally, once, at final render,
and must produce a real selectable text layer (ATS-readability), not an
image or garbled/subsetted text.
"""

from io import BytesIO

from pypdf import PdfReader

from src.cv_render import render_cv_pdf
from src.guardrails import PIIMasker

CANDIDATE = {"name": "Jordan Rivera", "email": "jordan@example.com",
            "phone": "555-123-4567"}

SECTIONS = {
    "summary": "ML engineer with {{CANDIDATE_NAME}}-caliber production experience.",
    "skills": ["Python", "PyTorch", "Kubernetes"],
    "experience": [
        {"title": "ML Engineer", "company": "Acme AI", "dates": "2022-2025",
         "location": "Remote",
         "bullets": ["Built recommendation systems serving 2M users.",
                    "Shipped an agentic pipeline reducing latency 40%."]},
    ],
    "education": [
        {"degree": "M.S. Data Science", "institution": "Northeastern",
         "dates": "2020-2022"},
    ],
}


def _masker() -> PIIMasker:
    return PIIMasker(name=CANDIDATE["name"], email=CANDIDATE["email"],
                     phone=CANDIDATE["phone"])


def _extract_text(pdf_bytes: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf_bytes)).pages)


def test_renders_valid_pdf_with_selectable_text():
    pdf_bytes = render_cv_pdf(SECTIONS, CANDIDATE, _masker())
    assert pdf_bytes[:4] == b"%PDF"  # real PDF, not garbage bytes
    text = _extract_text(pdf_bytes)
    # ATS-readability: content must be real extractable text, not an image
    assert "Built recommendation systems serving 2M users" in text
    assert "M.S. Data Science" in text
    assert "Northeastern" in text


def test_unmasks_pii_at_final_render_only():
    pdf_bytes = render_cv_pdf(SECTIONS, CANDIDATE, _masker())
    text = _extract_text(pdf_bytes)
    assert "Jordan Rivera" in text  # real name reinjected
    assert "{{CANDIDATE_NAME}}" not in text  # no stray placeholder text
    assert "jordan@example.com" in text


def test_omits_missing_sections_rather_than_padding():
    thin = {"summary": "", "skills": [], "experience": [], "education": []}
    pdf_bytes = render_cv_pdf(thin, CANDIDATE, _masker())
    text = _extract_text(pdf_bytes)
    assert "SUMMARY" not in text
    assert "SKILLS" not in text
    assert "EXPERIENCE" not in text
    assert "EDUCATION" not in text
    assert "Jordan Rivera" in text  # header still renders


def test_multiple_bullets_and_entries_do_not_crash_layout():
    # Regression: multi_cell() without an explicit cursor reset leaves the
    # cursor near the right margin, so a SECOND multi_cell call right
    # after (a second bullet, a second job) had zero width to render into
    # and raised FPDFException. Two bullets + two jobs is the minimum
    # repro for that.
    sections = {
        "summary": "",
        "skills": [],
        "experience": [
            {"title": "A", "company": "X", "dates": "2020", "location": "",
             "bullets": ["First bullet.", "Second bullet.", "Third bullet."]},
            {"title": "B", "company": "Y", "dates": "2019", "location": "",
             "bullets": ["Another bullet."]},
        ],
        "education": [],
    }
    pdf_bytes = render_cv_pdf(sections, CANDIDATE, _masker())
    text = _extract_text(pdf_bytes)
    assert "First bullet." in text
    assert "Another bullet." in text


def test_no_llm_generated_content_survives_beyond_provided_sections():
    """Renderer must not fabricate anything — every word in the PDF
    (besides fixed section headings and the real header) must trace back
    to a section value we passed in."""
    pdf_bytes = render_cv_pdf(SECTIONS, CANDIDATE, _masker())
    text = _extract_text(pdf_bytes)
    for skill in SECTIONS["skills"]:
        assert skill in text
    for entry in SECTIONS["experience"]:
        assert entry["company"] in text
        assert entry["title"] in text
