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


def test_suppress_is_location_scoped():
    """A dismissed FP in one file must NOT suppress a real same-class finding elsewhere.

    Regression for the global FP ratchet: signatures keyed only by (cwe, title) let a
    single dismissed 'SQL injection' silently suppress every real SQLi in other files.
    """
    store = InMemoryFPStore()
    fp = Finding(
        title="SQL injection", file_path="reports.py", line_range=(10, 10),
        severity=Severity.LOW, cwe_id="CWE-89",
    )
    record_false_positives(store, [fp], user_id="u@x")
    candidates = [
        Finding(  # same file, same class → known FP, suppressed
            title="SQL injection", file_path="reports.py", line_range=(10, 10),
            severity=Severity.HIGH, cwe_id="CWE-89",
        ),
        Finding(  # DIFFERENT file, same class → real finding, must survive
            title="SQL injection", file_path="payments.py", line_range=(7, 7),
            severity=Severity.CRITICAL, cwe_id="CWE-89",
        ),
    ]
    kept = suppress_known_fps(store, candidates, user_id="u@x")
    paths = {f.file_path for f in kept}
    assert "payments.py" in paths, "real vuln in a different file must not be suppressed"
    assert "reports.py" not in paths, "known FP in the same file should still be suppressed"


def test_suppress_isolated_on_error():
    class Broken:
        def recall(self, user_id):
            raise RuntimeError("memory down")

    candidates = [_f("x")]
    # error must not drop findings
    assert suppress_known_fps(Broken(), candidates, user_id="u@x") == candidates
