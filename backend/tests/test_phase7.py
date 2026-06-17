"""Tests for Phase 7 — false-positive memory."""
from __future__ import annotations

from pipeline.config import Finding, Severity
from pipeline.phase7_fpmemory import InMemoryFPStore, record_false_positives, suppress_known_fps


def _f(title, cwe="CWE-120"):
    return Finding(title=title, file_path="a.c", line_range=(1, 1), severity=Severity.LOW, cwe_id=cwe)


def test_record_and_recall():
    store = InMemoryFPStore()
    record_false_positives(store, [_f("printf format string")], user_id="u@x")
    patterns = store.recall("u@x")
    assert any(p["cwe_id"] == "CWE-120" for p in patterns)


def test_suppress_known_fps():
    store = InMemoryFPStore()
    record_false_positives(store, [_f("printf format string", cwe="CWE-134")], user_id="u@x")
    candidates = [
        _f("printf format string", cwe="CWE-134"),  # known FP → suppressed
        _f("real overflow", cwe="CWE-120"),  # kept
    ]
    kept = suppress_known_fps(store, candidates, user_id="u@x")
    titles = {f.title for f in kept}
    assert "real overflow" in titles
    assert "printf format string" not in titles


def test_suppress_isolated_on_error():
    class Broken:
        def recall(self, user_id):
            raise RuntimeError("memory down")

    candidates = [_f("x")]
    # error must not drop findings
    assert suppress_known_fps(Broken(), candidates, user_id="u@x") == candidates
