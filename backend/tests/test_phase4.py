"""Tests for Phase 4 — skeptical validator."""
from __future__ import annotations

from pipeline.config import Finding, ScanConfig, Severity, Verdict
from pipeline.phase4_validator import validate


def _findings():
    return [
        Finding(title="real", file_path="a.c", line_range=(1, 1), severity=Severity.CRITICAL),
        Finding(title="weak", file_path="a.c", line_range=(2, 2), severity=Severity.MEDIUM),
        Finding(title="fp", file_path="a.c", line_range=(3, 3), severity=Severity.LOW),
    ]


class IdConverse:
    def __init__(self, verdict_map):
        self.verdict_map = verdict_map

    def invoke(self, model, system, prompt, **k):
        import json

        items = [
            {"id": fid, "verdict": v, "confidence": c, "validated": True}
            for fid, (v, c) in self.verdict_map.items()
        ]
        return {"thinking": "", "output": json.dumps(items)}


def test_verdict_mapping_and_drop_dismissed():
    cfg = ScanConfig(project_path="/x")
    findings = _findings()
    vm = {
        findings[0].id: ("confirmed", 0.97),
        findings[1].id: ("likely", 0.7),
        findings[2].id: ("dismissed", 0.1),
    }
    out = validate(findings, {"language": "c", "code": "x"}, cfg, converse=IdConverse(vm))
    titles = {f.title for f in out}
    assert "real" in titles and "weak" in titles
    assert "fp" not in titles  # dismissed dropped
    real = next(f for f in out if f.title == "real")
    assert real.verdict is Verdict.CONFIRMED
    assert real.confidence == 0.97
    assert real.validated is True


def test_unmatched_findings_default_kept_as_likely():
    cfg = ScanConfig(project_path="/x")
    findings = _findings()
    out = validate(findings, {"language": "c", "code": "x"}, cfg, converse=IdConverse({}))
    # no verdicts returned → conservative keep with LIKELY
    assert len(out) == 3
    assert all(f.verdict is Verdict.LIKELY for f in out)
