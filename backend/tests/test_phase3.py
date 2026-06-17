"""Tests for Phase 3 — agentic hunter (pass@k dedup + confidence)."""
from __future__ import annotations

from pipeline.config import Language, ScanConfig
from pipeline.phase3_hunter import hunt

_FINDING = (
    '[{"title":"strcpy overflow","cwe_id":"CWE-120","severity":"critical",'
    '"line_range":[4,4],"description":"buf","exploitation_scenario":"x",'
    '"patch_suggestion":"use strncpy","chain_potential":true}]'
)


class SeqConverse:
    """Returns a queued output per invoke call."""

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def invoke(self, *a, **k):
        return {"thinking": "", "output": self.outputs.pop(0)}


def _target():
    return {"file": "transfer.c", "language": Language.C, "code": "strcpy(a,b);", "sink_summary": "strcpy@4"}


def test_dedup_across_k_runs_and_confidence():
    cfg = ScanConfig(project_path="/x", pass_at_k=3)
    fc = SeqConverse([_FINDING, _FINDING, _FINDING])
    findings = hunt(_target(), cfg, converse=fc)
    assert len(findings) == 1  # same finding deduped
    f = findings[0]
    assert f.cwe_id == "CWE-120"
    assert f.confidence == 1.0  # found in 3/3 runs
    assert f.chain_potential is True


def test_partial_frequency_confidence():
    cfg = ScanConfig(project_path="/x", pass_at_k=2)
    fc = SeqConverse([_FINDING, "[]"])  # found once of two runs
    findings = hunt(_target(), cfg, converse=fc)
    assert len(findings) == 1
    assert findings[0].confidence == 0.5


def test_no_findings():
    cfg = ScanConfig(project_path="/x", pass_at_k=1)
    fc = SeqConverse(["[]"])
    assert hunt(_target(), cfg, converse=fc) == []
