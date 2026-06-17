"""Tests for Phase 3.5 — adversarial challenger (thinking off, isolation)."""
from __future__ import annotations

from pipeline.config import Finding, ScanConfig, Severity
from pipeline.phase35_challenger import challenge


def _findings():
    return [
        Finding(title="real", file_path="a.c", line_range=(1, 1), severity=Severity.CRITICAL),
        Finding(title="bogus", file_path="a.c", line_range=(2, 2), severity=Severity.HIGH),
    ]


class MapConverse:
    """Returns a verdict keyed by which finding title appears in the prompt."""

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.thinking_flags = []

    def invoke(self, model, system, prompt, **k):
        self.thinking_flags.append(k.get("thinking"))
        for title, verdict in self.verdicts.items():
            if title in prompt:
                return {"thinking": "", "output": '{"verdict":"%s","confidence":0.9}' % verdict}
        return {"thinking": "", "output": '{"verdict":"likely"}'}


def test_dismissed_findings_dropped():
    cfg = ScanConfig(project_path="/x")
    fc = MapConverse({"real": "confirmed", "bogus": "dismissed"})
    kept = challenge(_findings(), {"language": "c", "code": "x"}, cfg, converse=fc)
    titles = {f.title for f in kept}
    assert "real" in titles and "bogus" not in titles


def test_thinking_disabled():
    cfg = ScanConfig(project_path="/x")
    fc = MapConverse({"real": "confirmed", "bogus": "confirmed"})
    challenge(_findings(), {"language": "c", "code": "x"}, cfg, converse=fc)
    assert all(flag is False for flag in fc.thinking_flags)


def test_exception_isolation_preserves_findings():
    cfg = ScanConfig(project_path="/x")

    class Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("challenger down")

    original = _findings()
    kept = challenge(original, {"language": "c", "code": "x"}, cfg, converse=Boom())
    assert kept == original  # preserved on failure
