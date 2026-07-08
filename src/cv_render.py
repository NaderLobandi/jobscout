"""Local, deterministic ATS CV renderer. No LLM calls, no network.

COURSE CONCEPT (deterministic vs. LLM): tailor_cv() (an LLM call) decides
WHAT the CV says; this module — plain Python — decides how it's laid
out. Keeping layout deterministic means the PDF is reproducible and
testable, and there's no way for a job posting's text to influence
formatting.

SECURITY: sections arrive from tailor_cv() still PII-masked
({{CANDIDATE_NAME}} etc.). Real values are reinjected ONLY here, at
final local render — same pattern as the cover letter — and the
unmasked result never goes back through the model.

ATS design choices, deliberate:
- Core PDF fonts (Helvetica) only, no embedded/subset font. Subsetted
  fonts are exactly what breaks reliable text extraction in some
  LaTeX-generated resumes (ligatures that don't round-trip through
  copy/paste or an ATS parser) — core fonts have no such failure mode.
- Single column, no tables or text boxes — ATS parsers read PDF text in
  stream order; anything that isn't a plain top-to-bottom flow risks
  scrambling section order.
- ASCII-only static text (separators, bullets) — sidesteps any core-font
  encoding gaps entirely, rather than depending on which extended
  characters happen to be supported.
"""

from __future__ import annotations

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .guardrails import PIIMasker

_MARGIN = 18
_PAGE_WIDTH_MM = 210  # A4


def render_cv_pdf(sections: dict, candidate: dict, masker: PIIMasker) -> bytes:
    """sections: tailor_cv()'s output (masked). candidate: profile.yaml's
    candidate dict (real name/email/phone — used only for the header,
    never sent to any LLM). masker: unmasks any {{PLACEHOLDER}} left in
    LLM-generated text (summary/bullets) back to real values, locally."""
    pdf = FPDF(format="A4")
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN)
    pdf.add_page()

    def unmask(text: str) -> str:
        return masker.unmask(text or "")

    _header(pdf, candidate)

    if sections.get("summary"):
        _heading(pdf, "Summary")
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(0, 5.5, unmask(sections["summary"]),
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    if sections.get("skills"):
        _heading(pdf, "Skills")
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(0, 5.5, unmask(" | ".join(sections["skills"])),
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    if sections.get("experience"):
        _heading(pdf, "Experience")
        for entry in sections["experience"]:
            pdf.set_font("Helvetica", "B", 11)
            title_line = f"{entry.get('title', '')} - {entry.get('company', '')}"
            pdf.cell(0, 6, unmask(title_line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            meta = " | ".join(p for p in
                             [entry.get("dates", ""), entry.get("location", "")] if p)
            if meta:
                pdf.set_font("Helvetica", "I", 9.5)
                pdf.cell(0, 5, unmask(meta), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("Helvetica", "", 10.5)
            for bullet in entry.get("bullets", []):
                pdf.multi_cell(0, 5.5, f"-  {unmask(bullet)}",
                              new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)

    if sections.get("education"):
        _heading(pdf, "Education")
        for entry in sections["education"]:
            pdf.set_font("Helvetica", "B", 10.5)
            deg_line = f"{entry.get('degree', '')} - {entry.get('institution', '')}"
            pdf.cell(0, 6, unmask(deg_line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if entry.get("dates"):
                pdf.set_font("Helvetica", "I", 9.5)
                pdf.cell(0, 5, unmask(entry["dates"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())


def _header(pdf: FPDF, candidate: dict) -> None:
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 9, candidate.get("name", ""), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    contact = " | ".join(p for p in
                         [candidate.get("email", ""), candidate.get("phone", "")] if p)
    if contact:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, contact, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


def _heading(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 12.5)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 7, title.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(150, 150, 150)
    y = pdf.get_y()
    pdf.line(_MARGIN, y, _PAGE_WIDTH_MM - _MARGIN, y)
    pdf.ln(2)
