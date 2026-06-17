"""Tests for Phase 6 — ASFF report + CI/CD gate."""
from __future__ import annotations

from pipeline.config import Finding, Severity, Verdict
from pipeline.phase6_report import cicd_gate_check, generate_report, to_asff


def _f(sev, chain=False, cwe="CWE-120"):
    return Finding(
        title=f"{sev.value} issue",
        file_path="transfer.c",
        line_range=(4, 8),
        severity=sev,
        cwe_id=cwe,
        confidence=0.9,
        chain_potential=chain,
        verdict=Verdict.CONFIRMED,
        validated=True,
        patch_suggestion="fix it",
    )


def test_to_asff_shape():
    asff = to_asff(_f(Severity.CRITICAL), account_id="123456789012", region="ap-northeast-2")
    assert asff["SchemaVersion"] == "2018-10-08"
    assert asff["Severity"]["Label"] == "CRITICAL"
    assert asff["ProductArn"].startswith("arn:aws:securityhub:ap-northeast-2:123456789012:")
    assert asff["Resources"][0]["Id"] == "transfer.c"
    assert asff["Remediation"]["Recommendation"]["Text"] == "fix it"
    assert asff["FindingProviderFields"]["Confidence"] == 90
    assert "CWE-120" in asff["FindingProviderFields"]["Types"]


def test_generate_report_counts():
    findings = [_f(Severity.CRITICAL, chain=True), _f(Severity.HIGH), _f(Severity.LOW)]
    rep = generate_report(findings)
    assert rep["total_findings"] == 3
    assert rep["critical"] == 1
    assert rep["high"] == 1
    assert rep["low"] == 1
    assert rep["chaining"] == 1
    assert len(rep["findings"]) == 3


def test_gate_blocks_on_critical():
    res = cicd_gate_check([_f(Severity.CRITICAL)])
    assert res["status"] == "BLOCKED"
    assert res["blocked"] == 1


def test_gate_blocks_on_chaining_medium():
    res = cicd_gate_check([_f(Severity.MEDIUM, chain=True)])
    assert res["status"] == "BLOCKED"  # chaining always blocks


def test_gate_passes_on_low_only():
    res = cicd_gate_check([_f(Severity.LOW), _f(Severity.INFO)])
    assert res["status"] == "PASSED"
    assert res["blocked"] == 0


def test_gate_empty_passes():
    assert cicd_gate_check([])["status"] == "PASSED"
