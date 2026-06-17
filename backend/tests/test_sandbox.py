"""Tests for tools.sandbox — Code Interpreter PoC verification."""
from __future__ import annotations

from pipeline.config import Finding, Severity
from tools.sandbox import verify_findings


def _f(title="overflow"):
    return Finding(title=title, file_path="a.c", line_range=(4, 4), severity=Severity.CRITICAL, confidence=0.7)


class FakeSandbox:
    def __init__(self, reproduced):
        self.reproduced = reproduced
        self.calls = 0

    def verify_poc_in_sandbox(self, finding, code):
        self.calls += 1
        return {"reproduced": self.reproduced, "output": "core dumped" if self.reproduced else ""}


def test_disabled_is_noop():
    fb = FakeSandbox(True)
    findings = [_f()]
    out = verify_findings(fb, findings, code="x", enabled=False)
    assert out == findings
    assert fb.calls == 0


def test_enabled_reproduced_boosts_confidence():
    fb = FakeSandbox(True)
    out = verify_findings(fb, [_f()], code="x", enabled=True)
    assert fb.calls == 1
    assert out[0].validated is True
    assert out[0].confidence >= 0.9  # reproduction is strong evidence


def test_enabled_not_reproduced_keeps_finding():
    fb = FakeSandbox(False)
    out = verify_findings(fb, [_f()], code="x", enabled=True)
    assert len(out) == 1  # not dropped, just not boosted
    assert out[0].confidence == 0.7


def test_error_isolated():
    class Broken:
        def verify_poc_in_sandbox(self, finding, code):
            raise RuntimeError("sandbox down")

    findings = [_f()]
    out = verify_findings(Broken(), findings, code="x", enabled=True)
    assert out == findings  # error must not drop findings
