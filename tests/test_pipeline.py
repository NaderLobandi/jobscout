"""Tests for the outcome-driven search loop (src/pipeline.collect_new_jobs).

The loop's contract: the TARGET number of new filter-surviving jobs is
the goal — rounds deepen until it's met, boards run dry, or the round
cap is hit. These run against fake fetchers, no MCP server needed.
"""

from src.pipeline import MAX_SEARCH_ROUNDS, collect_new_jobs


def _jobs(*ids):
    return [{"id": i, "title": i} for i in ids]


def test_stops_as_soon_as_target_met():
    rounds_fetched = []

    def fetch(page):
        rounds_fetched.append(page)
        return _jobs(f"a{page}", f"b{page}")

    kept = collect_new_jobs(fetch, keep_filter=lambda js: js, target=2)
    assert len(kept) == 2
    assert rounds_fetched == [1]  # target met in round 1 — no round 2


def test_deepens_until_target_met():
    def fetch(page):
        return _jobs(f"a{page}")  # one new job per round

    kept = collect_new_jobs(fetch, keep_filter=lambda js: js, target=3)
    assert [j["id"] for j in kept] == ["a1", "a2", "a3"]


def test_stops_when_a_round_returns_nothing():
    # Boards exhausted: an empty round means deeper rounds are pointless.
    calls = []

    def fetch(page):
        calls.append(page)
        return _jobs("a1") if page == 1 else []

    kept = collect_new_jobs(fetch, keep_filter=lambda js: js, target=99)
    assert len(kept) == 1
    assert calls == [1, 2]  # stopped right after the dry round


def test_round_cap_is_respected():
    def fetch(page):
        return _jobs(f"only{page}")

    kept = collect_new_jobs(fetch, keep_filter=lambda js: [], target=5)
    assert kept == []
    # keep_filter rejected everything, but the loop still must not spin
    # past MAX_SEARCH_ROUNDS.


def test_cross_round_duplicates_dropped_before_filtering():
    # A rotated keyword can resurface the same posting; it must not be
    # double-kept or double-counted against the filter.
    filtered_batches = []

    def fetch(page):
        return _jobs("same", f"new{page}")

    def keep(js):
        filtered_batches.append([j["id"] for j in js])
        return js

    kept = collect_new_jobs(fetch, keep_filter=keep, target=99, max_rounds=2)
    assert [j["id"] for j in kept] == ["same", "new1", "new2"]
    assert filtered_batches == [["same", "new1"], ["new2"]]


def test_on_round_narration_reports_progress():
    seen = []

    def fetch(page):
        return _jobs(f"a{page}")

    collect_new_jobs(fetch, keep_filter=lambda js: js, target=2,
                     on_round=lambda *args: seen.append(args))
    assert seen == [(1, 1, 1, 1), (2, 1, 1, 2)]


def test_default_round_cap_is_three():
    assert MAX_SEARCH_ROUNDS == 3
