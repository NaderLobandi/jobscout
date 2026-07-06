"""Intake wizard: interviews the user and writes profile/profile.yaml.

Run directly (python -m src.intake) or let the orchestrator invoke it when
no profile exists. Also owns profile loading + resume text extraction.

SECURITY note: the resume and contact details collected here stay local.
Everything that later goes to the LLM passes through guardrails.mask_pii().
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pypdf import PdfReader
from rich.console import Console
from rich.prompt import Confirm, Prompt

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "profile" / "profile.yaml"
EXAMPLE_PATH = REPO_ROOT / "profile" / "profile.example.yaml"

console = Console()


def load_profile() -> dict | None:
    """Real profile if present, else None (orchestrator then runs the wizard).
    The committed example is only used as a template, never silently as a
    real profile."""
    if PROFILE_PATH.exists():
        return yaml.safe_load(PROFILE_PATH.read_text())
    return None


def extract_resume_text(profile: dict) -> str:
    """Plain text from the resume PDF (or .txt). Empty string if missing —
    scoring still works from the profile summary alone."""
    path_str = (profile.get("candidate") or {}).get("resume_path", "")
    if not path_str:
        return ""
    path = (REPO_ROOT / path_str).resolve() if not Path(path_str).is_absolute() \
        else Path(path_str)
    if not path.exists():
        return ""
    if path.suffix.lower() == ".pdf":
        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        except Exception:
            return ""
    return path.read_text(errors="ignore")


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

    profile = {
        "candidate": {
            "name": name, "email": email, "phone": phone,
            "resume_path": resume_path, "summary": summary,
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
            "enabled": ["remoteok", "themuse", "remotive", "arbeitnow", "greenhouse"],
            "greenhouse_companies": _ask_list(
                "Greenhouse companies to watch (tokens, e.g. anthropic, stripe)",
                "anthropic"),
        },
    }
    PROFILE_PATH.parent.mkdir(exist_ok=True)
    PROFILE_PATH.write_text(yaml.safe_dump(profile, sort_keys=False))
    console.print(f"\n[green]Profile saved to {PROFILE_PATH} (gitignored).[/green]")
    return profile


if __name__ == "__main__":
    run_wizard()
