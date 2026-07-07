"""Intake wizard: interviews the user and writes profile/profile.yaml.

Run directly (python -m src.intake) or let the orchestrator invoke it when
no profile exists. Also owns profile loading + resume text extraction.

SECURITY note: the resume and contact details collected here stay local.
Everything that later goes to the LLM passes through guardrails.mask_pii().
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pypdf import PdfReader
from rich.console import Console
from rich.prompt import Confirm, Prompt

# pypdf logs benign "Ignoring wrong pointing object" warnings for PDFs with
# non-standard xref tables (common from Word/Docs exporters); it still
# extracts text fine. Silenced so demo/CLI output stays clean.
logging.getLogger("pypdf").setLevel(logging.ERROR)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "profile" / "profile.yaml"
EXAMPLE_PATH = REPO_ROOT / "profile" / "profile.example.yaml"
DOCUMENTS_DIR = REPO_ROOT / "profile" / "documents"
RESUME_PATH = REPO_ROOT / "profile" / "resume.pdf"
SUPPORTED_DOC_SUFFIXES = (".pdf", ".txt", ".md")

console = Console()


def load_profile() -> dict | None:
    """Real profile if present, else None (orchestrator then runs the wizard).
    The committed example is only used as a template, never silently as a
    real profile."""
    if PROFILE_PATH.exists():
        return yaml.safe_load(PROFILE_PATH.read_text())
    return None


def _extract_text(path: Path) -> str:
    """Plain text from a PDF, .txt, or .md file. Empty string on any
    failure — a bad supplementary document should degrade, not crash."""
    if not path.exists():
        return ""
    if path.suffix.lower() == ".pdf":
        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        except Exception:
            return ""
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def list_profile_documents() -> list[str]:
    """Filenames currently saved under profile/documents/, for UI display."""
    if not DOCUMENTS_DIR.exists():
        return []
    return sorted(
        p.name for p in DOCUMENTS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_DOC_SUFFIXES
    )


def extract_profile_text(profile: dict) -> str:
    """Combined plain text from the resume PDF plus any supplementary
    documents in profile/documents/ (LinkedIn export, past cover letters,
    reference letters), each labeled by filename so the resume-analysis
    skill can weight a resume bullet differently from an inferred claim
    in a LinkedIn blurb. Empty string if nothing is present — scoring
    still works from the profile summary alone."""
    sections: list[str] = []

    resume_path_str = (profile.get("candidate") or {}).get("resume_path", "")
    if resume_path_str:
        resume_path = (REPO_ROOT / resume_path_str).resolve() \
            if not Path(resume_path_str).is_absolute() else Path(resume_path_str)
        resume_text = _extract_text(resume_path)
        if resume_text:
            sections.append(f"--- Resume: {resume_path.name} ---\n{resume_text}")

    for doc_path in (DOCUMENTS_DIR.iterdir() if DOCUMENTS_DIR.exists() else []):
        if not doc_path.is_file() or doc_path.suffix.lower() not in SUPPORTED_DOC_SUFFIXES:
            continue
        text = _extract_text(doc_path)
        if text:
            sections.append(f"--- Supplementary document: {doc_path.name} ---\n{text}")

    return "\n\n".join(sections)


def extract_all_saved_documents() -> str:
    """Same extraction as extract_profile_text(), but keyed off whatever is
    already saved on disk rather than a profile dict — lets the UI preview
    what the LLM will actually see before or without a saved profile.yaml."""
    return extract_profile_text({"candidate": {"resume_path": str(RESUME_PATH)}})


def _ask_list(prompt: str, default: str = "") -> list[str]:
    raw = Prompt.ask(prompt, default=default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def run_wizard() -> dict:
    """CLI interview -> profile dict, persisted to profile/profile.yaml."""
    console.print("[bold cyan]JobScout intake — let's build your profile.[/bold cyan]")
    console.print("[dim]Answers stay local; PII is masked before any LLM call.[/dim]\n")

    name = Prompt.ask("Your full name (for cover letters; masked from the LLM)")
    email = Prompt.ask("Email", default="")
    phone = Prompt.ask("Phone", default="")
    resume_path = Prompt.ask("Path to resume PDF", default="./profile/resume.pdf")
    summary = Prompt.ask("One-line summary of yourself (optional)", default="")
    communication_style = Prompt.ask(
        "Cover letter tone (optional — blank for a natural default)",
        choices=["", "direct", "collaborative", "enthusiastic"], default="")

    employment_types = _ask_list(
        "Employment types (comma-sep: internship, full-time, part-time, contract)",
        "full-time")
    target_roles = _ask_list("Target roles (comma-separated)",
                             "Machine Learning Engineer")
    seniority = _ask_list("Seniority levels (junior, mid, senior, staff)", "mid, senior")
    industries = _ask_list("Preferred industries", "AI/ML")
    locations = _ask_list("Locations", "Remote US")
    remote_pref = Prompt.ask("Remote preference",
                             choices=["onsite", "hybrid", "remote_only",
                                      "remote_or_hybrid", "any"],
                             default="remote_or_hybrid")
    salary_floor = int(Prompt.ask("Salary floor USD (0 = ignore)", default="0"))
    visa = Confirm.ask("Do you require visa sponsorship?", default=False)
    must_haves = _ask_list("Must-haves (comma-separated, optional)", "")
    dealbreakers = _ask_list("Dealbreakers (comma-separated, optional)", "")

    console.print(
        "\n[yellow]⚠️  LinkedIn has no official jobs API. JobScout can reach "
        "it only via LinkedIn's public no-login guest endpoint, and automated "
        "access to it violates LinkedIn's User Agreement. JobScout never "
        "sends your login or cookies there and keeps requests few and slow, "
        "but the ToS risk cannot be reduced to zero.[/yellow]")
    linkedin_ack = Confirm.ask(
        "Enable the LinkedIn source anyway, at your own risk?", default=False)

    profile = {
        "candidate": {
            "name": name, "email": email, "phone": phone,
            "resume_path": resume_path, "summary": summary,
            "communication_style": communication_style,
        },
        "preferences": {
            "employment_types": employment_types,
            "target_roles": target_roles,
            "seniority": seniority,
            "industries": industries,
            "locations": locations,
            "remote_preference": remote_pref,
            "salary_floor_usd": salary_floor,
            "visa_sponsorship_required": visa,
            "must_haves": must_haves,
            "dealbreakers": dealbreakers,
        },
        # sensible default weights; user can edit profile.yaml afterwards
        "weights": {
            "skills_match": 0.4, "role_title_match": 0.2, "industry_match": 0.15,
            "location_match": 0.15, "seniority_match": 0.1,
        },
        "draft_threshold": 70,
        "sources": {
            "enabled": ["remoteok", "themuse", "remotive", "arbeitnow",
                        "greenhouse", "lever", "ashby"]
                       + (["linkedin"] if linkedin_ack else []),
            "greenhouse_companies": _ask_list(
                "Greenhouse companies to watch (tokens, e.g. anthropic, stripe)",
                "anthropic"),
            "lever_companies": _ask_list(
                "Lever companies to watch (tokens, optional)", ""),
            "ashby_companies": _ask_list(
                "Ashby companies to watch (org names, optional)", ""),
            "linkedin_tos_acknowledged": linkedin_ack,
        },
    }
    PROFILE_PATH.parent.mkdir(exist_ok=True)
    PROFILE_PATH.write_text(yaml.safe_dump(profile, sort_keys=False))
    console.print(f"\n[green]Profile saved to {PROFILE_PATH} (gitignored).[/green]")
    return profile


if __name__ == "__main__":
    run_wizard()
