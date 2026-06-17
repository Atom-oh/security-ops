"""Tests for Phase 4.5 cross-family ensemble voting."""
from __future__ import annotations

from pipeline.config import Finding, ScanConfig, Severity, Verdict
from pipeline.ensemble import cross_family_validate


def _f(title, verdict=Verdict.CONFIRMED):
    return Finding(title=title, file_path="a.py", line_range=(1, 1), severity=Severity.HIGH,
                   verdict=verdict, confidence=0.7)


class OpenAIFake:
    def __init__(self, verdict):
        self.verdict = verdict

    def invoke(self, model, system, prompt, **k):
        return {"thinking": "", "output": '[{"id":"x","verdict":"%s","confidence":0.9}]' % self.verdict}


_cfg = ScanConfig(project_path="/x")
_target = {"language": "python", "code": "code"}


def test_both_confirm_is_confirmed():
    out = cross_family_validate([_f("v", Verdict.CONFIRMED)], _target, _cfg, OpenAIFake("confirmed"))
    assert len(out) == 1
    assert out[0].verdict is Verdict.CONFIRMED
    assert out[0].cross_family == "both"
    assert out[0].confidence >= 0.95


def test_disagreement_escalates():
    out = cross_family_validate([_f("v", Verdict.CONFIRMED)], _target, _cfg, OpenAIFake("dismissed"))
    assert len(out) == 1
    assert out[0].verdict is Verdict.ESCALATE
    assert out[0].cross_family == "disagree"


def test_both_dismiss_drops():
    out = cross_family_validate([_f("v", Verdict.DISMISSED)], _target, _cfg, OpenAIFake("dismissed"))
    assert out == []


def test_provider_error_keeps_claude_verdict():
    class Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("mantle down")

    findings = [_f("v", Verdict.CONFIRMED)]
    out = cross_family_validate(findings, _target, _cfg, Boom())
    assert out == findings  # unchanged on error


def test_no_provider_noop():
    findings = [_f("v")]
    assert cross_family_validate(findings, _target, _cfg, None) == findings


def test_orchestrator_runs_ensemble_when_enabled(tmp_path):
    from pipeline.orchestrator import FSIMythosPipeline

    (tmp_path / "auth.py").write_text("def login(req):\n    return req.body['pw']\n")
    cfg = ScanConfig(project_path=str(tmp_path), max_files=1, pass_at_k=1)
    cfg.ensemble_enabled = True

    class ClaudeFake:  # hunter finds 1, challenger/validator confirm
        def invoke(self, model, system, prompt, **k):
            if "보안 연구원" in system:
                return {"thinking": "", "output": '[{"title":"authz bug","cwe_id":"CWE-285","severity":"high","line_range":[2,2]}]'}
            if "최종" in system:
                import re
                m = re.search(r'"id":\s*"(fsi-[0-9a-f]{16})"', prompt)
                fid = m.group(1) if m else "x"
                return {"thinking": "", "output": '[{"id":"%s","verdict":"confirmed","confidence":0.9,"validated":true}]' % fid}
            return {"thinking": "", "output": "[]"}

    res = FSIMythosPipeline(cfg, converse=ClaudeFake(), openai_provider=OpenAIFake("confirmed")).run()
    findings = res["report"]["findings"]
    assert any(f.get("cross_family") == "both" for f in findings), "ensemble vote should be recorded"
