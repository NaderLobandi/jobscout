"""JobScout guardrails: PII masking, audit logging, and the HITL gate.

COURSE CONCEPT (security features). Three independent defenses:

1. PII masking (context hygiene) — the user's name/email/phone/address are
   replaced with placeholders BEFORE any LLM call and reinjected only at
   final local render. Real PII never transits the model or its logs.
2. Audit log — every tool/LLM call is appended to logs/audit.jsonl so a
   human can reconstruct exactly what the agent did and with what inputs.
3. HITL checkpoint gate — the hard stop before any application. This
   mitigates the CONFUSED DEPUTY problem: JobScout wields the user's
   authority to search and draft, but deliberately does NOT hold the
   authority to submit. Submission requires the human, every time.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG = REPO_ROOT / "logs" / "audit.jsonl"

console = Console()

# ---------------------------------------------------------------------------
# PII masking
# ---------------------------------------------------------------------------

# Regexes catch PII the user didn't declare (emails/phones inside the resume
# body). Declared values (name, address) are masked by exact match.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(
    r"(?<![\w/])(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
)
_URL_RE = re.compile(r"https?://\S+|linkedin\.com/\S+|github\.com/\S+", re.I)


class PIIMasker:
    """Two-way mask: mask() before every LLM call, unmask() only at final
    local render. The mapping lives in this process's memory only."""

    def __init__(self, name: str = "", email: str = "", phone: str = "",
                 address: str = ""):
        self._declared = [
            ("{{CANDIDATE_NAME}}", name),
            ("{{CANDIDATE_EMAIL}}", email),
            ("{{CANDIDATE_PHONE}}", phone),
            ("{{CANDIDATE_ADDRESS}}", address),
        ]
        # placeholder -> real value. Prepopulated from declared values so
        # unmask() works even in flows (e.g. the Streamlit UI) where this
        # instance renders a draft without having masked text first.
        self.mapping: dict[str, str] = {
            ph: val for ph, val in self._declared if val
        }

    def mask(self, text: str) -> str:
        if not text:
            return text
        # 1) declared values, longest first so substrings don't clobber
        for placeholder, value in sorted(self._declared, key=lambda p: -len(p[1])):
            if value:
                self.mapping[placeholder] = value
                text = re.sub(re.escape(value), placeholder, text, flags=re.I)
        # 2) any residual emails/phones the user didn't declare
        for match in _EMAIL_RE.findall(text):
            if match not in self.mapping.values():
                self.mapping["{{CANDIDATE_EMAIL}}"] = self.mapping.get(
                    "{{CANDIDATE_EMAIL}}", match)
        text = _EMAIL_RE.sub("{{CANDIDATE_EMAIL}}", text)
        text = _PHONE_RE.sub("{{CANDIDATE_PHONE}}", text)
        return text

    def unmask(self, text: str) -> str:
        """Reinject real values — called only at final render, locally,
        never on text that will be sent back to the model."""
        for placeholder, value in self.mapping.items():
            text = text.replace(placeholder, value)
        return text


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def audit(tool: str, inputs: dict, actor: str = "orchestrator") -> None:
    """Append one audit entry. Inputs are truncated so the log stays
    reviewable (and never balloons with full job descriptions)."""
    AUDIT_LOG.parent.mkdir(exist_ok=True)
    safe_inputs = {
        k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v)
        for k, v in inputs.items()
    }
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "tool": tool,
        "inputs": safe_inputs,
    }
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# Deterministic filters (not prompt-injectable)
# ---------------------------------------------------------------------------

def violates_dealbreakers(job_text: str, dealbreakers: list[str]) -> str | None:
    """Return the matched dealbreaker, or None. Plain substring matching in
    Python — a malicious job description cannot talk its way past this the
    way it might prompt-inject an LLM judge."""
    t = job_text.lower()
    for db in dealbreakers:
        if db.strip() and db.strip().lower() in t:
            return db
    return None


def employment_type_allowed(job_type: str, allowed: list[str]) -> bool:
    """'unknown' passes (we'd rather score it than silently drop it);
    a known type must be in the allowed list."""
    if not allowed or job_type == "unknown":
        return True
    return job_type in allowed


# ---------------------------------------------------------------------------
# HITL gate
# ---------------------------------------------------------------------------

def hitl_gate(package: dict) -> str:
    """Present one application package and HARD STOP for a human decision.

    Returns 'approved' | 'rejected' | 'skipped' | 'quit'. 'approved' means
    the human will apply manually via the job URL — JobScout itself has no
    code path that submits an application anywhere. 'quit' tells the
    orchestrator to stop presenting further packages this run (each
    remaining package is still an explicit human decision to stop
    reviewing, not an automated bypass).
    """
    job = package["job"]
    console.print(Panel(
        f"[bold]{job['title']}[/bold] @ {job['company']}\n"
        f"{job['location']}  ·  {job['remote']}  ·  {job['source']}\n"
        f"[cyan]{job['url']}[/cyan]\n\n"
        f"[bold]Score: {package['score']:.0f}/100[/bold]\n"
        + "\n".join(f"  {dim:18} {d['score']:>3}/100 — {d['reason']}"
                    for dim, d in package["dimensions"].items())
        + f"\n\n[italic]{package['summary']}[/italic]",
        title="🎯 Match — human review required",
        border_style="green",
    ))
    if package.get("cover_letter"):
        console.print(Panel(package["cover_letter"],
                            title="✉️  Draft cover letter", border_style="blue"))
    if package.get("resume_tweaks"):
        console.print(Panel(package["resume_tweaks"],
                            title="📄 Suggested resume tweaks", border_style="blue"))
    if package.get("review_notes"):
        issues = "\n".join(
            f"  • {i['category'].replace('_', ' ')}: {i['detail']}"
            for i in package.get("review_issues", []))
        body = package["review_notes"] + (f"\n\n{issues}" if issues else "")
        console.print(Panel(body, title="🔍 Reviewer notes (second-pass critique)",
                            border_style="magenta"))
    kw = package.get("keyword_coverage")
    if kw and (kw["covered"] or kw["missing"]):
        total = len(kw["covered"]) + len(kw["missing"])
        body = (f"[green]✅ Covered ({len(kw['covered'])}/{total}):[/green] "
               f"{', '.join(kw['covered']) or '—'}\n"
               f"[yellow]⚠️  Missing:[/yellow] {', '.join(kw['missing']) or '—'}")
        console.print(Panel(body, title="🔑 Keyword coverage vs. the posting",
                            border_style="cyan"))

    console.print(
        "[yellow]JobScout never submits applications. "
        "If you approve, apply manually at the URL above.[/yellow]"
    )
    decision = Prompt.ask(
        "[bold]Approve this package?[/bold] "
        "(quit = stop reviewing remaining matches this run)",
        choices=["approve", "reject", "skip", "quit"],
        default="skip",
    )
    audit("hitl_gate", {"job_id": job["id"], "title": job["title"],
                        "decision": decision}, actor="human")
    return {"approve": "approved", "reject": "rejected",
            "quit": "quit"}.get(decision, "skipped")
