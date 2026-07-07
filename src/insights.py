"""Skill-gap insights: aggregate recurring weaknesses across every job
JobScout has ever scored, using the exact same Records store the History
page already reads.

COURSE CONCEPT (deterministic vs. LLM judgment): the aggregation itself
is plain Python over numbers already produced by the Scoring Agent — no
LLM call, no cost, safe to recompute any time. Only the optional
narrative suggestion (src/agents/insights_agent.py) spends a token.

Run standalone: python -m src.insights
"""

from __future__ import annotations

from src.records import Records

DIMENSIONS = ("skills_match", "role_title_match", "industry_match",
              "location_match", "seniority_match")


def aggregate_dimension_gaps(entries: list[dict]) -> list[dict]:
    """One row per dimension that has been scored at least once, sorted
    worst-average-first. Each row:
        dimension, avg_score, count,
        weakest_count (times this was the single lowest dimension for a job),
        sample_reasons (the 3 lowest-scoring instances, for qualitative color)
    """
    scored = [e for e in entries if e.get("dimensions")]
    scores: dict[str, list[float]] = {d: [] for d in DIMENSIONS}
    reasons: dict[str, list[tuple[float, str, str]]] = {d: [] for d in DIMENSIONS}
    weakest_count = {d: 0 for d in DIMENSIONS}

    for entry in scored:
        dims = entry["dimensions"]
        present = {d: dims[d]["score"] for d in DIMENSIONS if d in dims}
        if present:
            weakest = min(present, key=present.get)
            weakest_count[weakest] += 1
        for d in DIMENSIONS:
            if d in dims:
                scores[d].append(dims[d]["score"])
                reasons[d].append((dims[d]["score"], dims[d].get("reason", ""),
                                  entry["job"]["title"]))

    rows = []
    for d in DIMENSIONS:
        if not scores[d]:
            continue
        worst = sorted(reasons[d], key=lambda r: r[0])[:3]
        rows.append({
            "dimension": d,
            "avg_score": round(sum(scores[d]) / len(scores[d]), 1),
            "count": len(scores[d]),
            "weakest_count": weakest_count[d],
            "sample_reasons": [
                {"score": s, "reason": r, "job_title": t} for s, r, t in worst
            ],
        })
    rows.sort(key=lambda r: r["avg_score"])
    return rows


if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()
    gaps = aggregate_dimension_gaps(Records().all())
    if not gaps:
        console.print("[yellow]No scored jobs yet — run JobScout first.[/yellow]")
    else:
        table = Table(title="Recurring dimension gaps (worst first)")
        table.add_column("Dimension")
        table.add_column("Avg score", justify="right")
        table.add_column("Scored on", justify="right")
        table.add_column("Was the weakest link", justify="right")
        for row in gaps:
            table.add_row(row["dimension"].replace("_", " "),
                         f"{row['avg_score']:.1f}", str(row["count"]),
                         f"{row['weakest_count']}x")
        console.print(table)
        worst = gaps[0]
        console.print(f"\n[bold]Recurring pattern in your weakest "
                      f"dimension ({worst['dimension'].replace('_', ' ')}):[/bold]")
        for r in worst["sample_reasons"]:
            console.print(f"  • {r['score']}/100 on {r['job_title']!r}: {r['reason']}")
