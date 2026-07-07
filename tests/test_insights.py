"""aggregate_dimension_gaps: pure aggregation over Records data, no LLM
call — deterministic and directly testable."""

from src.insights import aggregate_dimension_gaps

ENTRY_STRONG_LOCATION = {
    "job": {"id": "j1", "title": "Remote ML Engineer"},
    "dimensions": {
        "skills_match": {"score": 90, "reason": "great fit"},
        "location_match": {"score": 95, "reason": "fully remote"},
    },
}
ENTRY_WEAK_LOCATION = {
    "job": {"id": "j2", "title": "Onsite Research Engineer"},
    "dimensions": {
        "skills_match": {"score": 80, "reason": "solid overlap"},
        "location_match": {"score": 20, "reason": "onsite-only, no remote"},
    },
}
ENTRY_NO_DIMENSIONS = {"job": {"id": "j3", "title": "Not yet scored"}}


def test_empty_input():
    assert aggregate_dimension_gaps([]) == []


def test_ignores_entries_without_dimensions():
    rows = aggregate_dimension_gaps([ENTRY_NO_DIMENSIONS])
    assert rows == []


def test_sorts_worst_average_first():
    rows = aggregate_dimension_gaps([ENTRY_STRONG_LOCATION, ENTRY_WEAK_LOCATION])
    dims = [r["dimension"] for r in rows]
    # location_match avg = (95+20)/2 = 57.5; skills_match avg = (90+80)/2 = 85
    assert dims[0] == "location_match"
    assert dims[-1] == "skills_match"
    assert rows[0]["avg_score"] == 57.5


def test_weakest_count_tracks_the_single_lowest_dimension_per_job():
    rows = aggregate_dimension_gaps([ENTRY_STRONG_LOCATION, ENTRY_WEAK_LOCATION])
    by_dim = {r["dimension"]: r for r in rows}
    # job1's weakest is skills_match (90 vs 95); job2's weakest is location_match (20 vs 80)
    assert by_dim["location_match"]["weakest_count"] == 1
    assert by_dim["skills_match"]["weakest_count"] == 1


def test_sample_reasons_are_lowest_scoring_first():
    entries = [ENTRY_STRONG_LOCATION, ENTRY_WEAK_LOCATION]
    rows = aggregate_dimension_gaps(entries)
    location_row = next(r for r in rows if r["dimension"] == "location_match")
    assert location_row["sample_reasons"][0]["score"] == 20
    assert "onsite-only" in location_row["sample_reasons"][0]["reason"]


def test_real_data_shape_regression():
    """Matches the exact shape scoring_agent.score_job() + Records.upsert()
    produce — guards against silently drifting from the real schema."""
    entry = {
        "job": {"id": "real1", "title": "Research Engineer, Discovery"},
        "score": 82.5,
        "dimensions": {
            "skills_match": {"score": 72, "reason": "..."},
            "role_title_match": {"score": 95, "reason": "..."},
            "industry_match": {"score": 100, "reason": "..."},
            "location_match": {"score": 40, "reason": "no remote option"},
            "seniority_match": {"score": 80, "reason": "..."},
        },
    }
    rows = aggregate_dimension_gaps([entry])
    assert len(rows) == 5
    assert rows[0]["dimension"] == "location_match"
    assert rows[0]["avg_score"] == 40.0
