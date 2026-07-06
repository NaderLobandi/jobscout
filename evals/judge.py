"""Eval harness for the Scoring Agent (LLM-as-judge).

COURSE CONCEPT (evals vs tests): pytest covers the deterministic parts
(parsing, masking, filtering); this harness covers the NON-deterministic
part — does the Scoring Agent produce sensible scores and rationales?
Without both it is always vibe coding.

Two checks per golden case:
1. Deterministic band check (code): weighted score inside expected_band.
2. LLM-as-judge (Claude): does the rationale actually cite the factors a
   human labeler said matter, without hallucinating?

Run:  python -m evals.judge          (requires ANTHROPIC_API_KEY)

The golden set includes a prompt-injection case (gold6): a job description
that orders the model to output 100s. Passing means the injection failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agents import MODEL, scoring_agent  # noqa: E402

console = Console()

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "factors_covered": {"type": "boolean"},
        "grounded": {"type": "boolean"},
        "comment": {"type": "string"},
    },
    "required": ["factors_covered", "grounded", "comment"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = (
    "You are grading a job-matching agent's output against a rubric. "
    "Answer strictly from the evidence given. factors_covered: does the "
    "rationale meaningfully address the expected factors? grounded: is the "
    "rationale free of claims not supported by the job posting or profile?"
)


def judge_rationale(client: Anthropic, case: dict, result: dict) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=JUDGE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        messages=[{
            "role": "user",
            "content": (
                f"EXPECTED FACTORS: {case['expected_factors']}\n\n"
                f"JOB POSTING:\n{json.dumps(case['job'], indent=1)}\n\n"
                f"AGENT OUTPUT:\n{json.dumps(result, indent=1)}"
            ),
        }],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    golden = json.loads((REPO_ROOT / "evals" / "golden_set.json").read_text())
    client = Anthropic()

    table = Table(title="Scoring Agent eval")
    for col in ("case", "score", "band", "band ok", "judge ok", "comment"):
        table.add_column(col)

    passed = 0
    for case in golden["cases"]:
        result = scoring_agent.score_job(
            client, golden["skills_profile"], golden["preferences"],
            case["job"], golden["weights"],
        )
        lo, hi = case["expected_band"]
        band_ok = lo <= result["score"] <= hi
        verdict = judge_rationale(client, case, result)
        judge_ok = verdict["factors_covered"] and verdict["grounded"]
        if band_ok and judge_ok:
            passed += 1
        table.add_row(
            case["name"], f"{result['score']:.0f}", f"{lo}-{hi}",
            "✅" if band_ok else "❌", "✅" if judge_ok else "❌",
            verdict["comment"][:60],
        )

    console.print(table)
    total = len(golden["cases"])
    style = "green" if passed == total else "red"
    console.print(f"[{style}]{passed}/{total} cases passed[/{style}]")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
