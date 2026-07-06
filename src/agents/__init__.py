"""JobScout sub-agents + skill loading.

COURSE CONCEPT (Agent Skills / progressive disclosure): each skill's
metadata (frontmatter description) is cheap and always known; the full
body is loaded into an agent's system prompt only when that agent actually
runs. One skill, one job.
"""

from __future__ import annotations

import os
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

# Default per the Claude API guidance; override with JOBSCOUT_MODEL (e.g.
# claude-haiku-4-5 for near-zero-cost development and demo runs).
MODEL = os.getenv("JOBSCOUT_MODEL", "claude-opus-4-8")


def thinking_kwargs() -> dict:
    """Adaptive thinking is a reasoning-tier feature. Haiku models don't
    support it (and reject the related `effort` param outright), so we
    omit it there rather than 400 on every call when running cost-conscious
    on claude-haiku-4-5."""
    if "haiku" in MODEL:
        return {}
    return {"thinking": {"type": "adaptive"}}


def load_skill(name: str) -> str:
    """Return the SKILL.md body (frontmatter stripped) for injection into
    an agent's system prompt at invocation time — progressive disclosure."""
    path = SKILLS_DIR / name / "SKILL.md"
    text = path.read_text()
    if text.startswith("---"):
        # strip YAML frontmatter: body starts after the second '---'
        _, _, body = text.split("---", 2)
        return body.strip()
    return text.strip()
