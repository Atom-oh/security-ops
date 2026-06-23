"""Tests for the advisory staleness guard (Task 2)."""
from __future__ import annotations

from tools.staleness import annotate_stale

NOW = "2026-06-18T12:00:00.000000Z"


def _rec(status, updated=None, created="2026-06-18T11:00:00.000000Z", phase="Phase 3 · 헌트"):
    r = {"status": status, "createdAt": created, "currentPhase": phase}
    if updated:
        r["updatedAt"] = updated
    return r


def test_stale_in_progress_becomes_timed_out_view():
    # last heartbeat 1h ago, threshold 30m → advisory timed_out, canonical status untouched.
    r = annotate_stale(_rec("IN_PROGRESS", updated="2026-06-18T11:00:00.000000Z"), NOW, 1800)
    assert r["stale"] is True
    assert r["statusView"] == "timed_out"
    assert r["status"] == "IN_PROGRESS"  # canonical status NOT mutated
    assert "Phase 3" in r["staleReason"]


def test_fresh_in_progress_not_stale():
    r = annotate_stale(_rec("IN_PROGRESS", updated="2026-06-18T11:59:30.000000Z"), NOW, 1800)
    assert r["stale"] is False
    assert r["statusView"] == "IN_PROGRESS"


def test_terminal_records_untouched():
    for st in ("done", "error"):
        r = annotate_stale(_rec(st, updated="2026-06-17T00:00:00.000000Z"), NOW, 1800)
        assert r["stale"] is False
        assert r["statusView"] == st


def test_missing_timestamps_fail_closed_to_stale():
    r = {"status": "IN_PROGRESS"}  # no updatedAt/createdAt
    out = annotate_stale(r, NOW, 1800)
    assert out["stale"] is True
    assert out["statusView"] == "timed_out"


def test_updated_at_takes_precedence_over_created_at():
    # createdAt is old (would be stale) but a recent updatedAt heartbeat keeps it alive.
    r = annotate_stale(
        _rec("IN_PROGRESS", updated="2026-06-18T11:59:00.000000Z",
             created="2026-06-18T01:00:00.000000Z"),
        NOW, 1800,
    )
    assert r["stale"] is False


def test_does_not_mutate_input():
    src = _rec("IN_PROGRESS", updated="2026-06-18T11:00:00.000000Z")
    annotate_stale(src, NOW, 1800)
    assert "statusView" not in src and "stale" not in src
