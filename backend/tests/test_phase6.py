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


def _raw(sev, chain=False):
    """A raw Hunter finding: no verdict yet (not validated)."""
    return Finding(
        title=f"{sev.value} raw", file_path="x.py", line_range=(1, 1),
        severity=sev, chain_potential=chain,
    )


def test_chaining_does_not_block_unvalidated_low():
    # HIGH-4b: a raw single-file Hunter chaining guess on a LOW finding must NOT hard-block CI.
    res = cicd_gate_check([_raw(Severity.LOW, chain=True)])
    assert res["status"] == "PASSED"
    assert res["blocked"] == 0


def test_chaining_blocks_when_validated():
    # A validated (CONFIRMED) chaining finding still blocks.
    res = cicd_gate_check([_f(Severity.MEDIUM, chain=True)])  # _f has verdict=CONFIRMED
    assert res["status"] == "BLOCKED"


def test_gate_cap_unscanned_is_advisory_not_incomplete():
    # HIGH #1 (refined): files merely deprioritized below max_files are risk-ranked + still
    # secret-scanned → advisory PASS, not INCOMPLETE (else every real repo is forever INCOMPLETE).
    cov = {"total_code_files": 5, "scanned_files": 3, "unscanned_files": 2, "dropped_over_budget": 0}
    res = cicd_gate_check([_f(Severity.LOW)], coverage=cov)
    assert res["status"] == "PASSED"
    assert any("advisory" in r for r in res["reasons"])


def test_gate_incomplete_on_budget_drop():
    # Files dropped over budget were never scanned at all → fail-closed INCOMPLETE.
    cov = {"total_code_files": 10, "scanned_files": 8, "unscanned_files": 0, "dropped_over_budget": 2}
    assert cicd_gate_check([], coverage=cov)["status"] == "INCOMPLETE"


def test_gate_incomplete_when_nothing_scanned():
    cov = {"total_code_files": 4, "scanned_files": 0, "unscanned_files": 4, "dropped_over_budget": 0}
    assert cicd_gate_check([], coverage=cov)["status"] == "INCOMPLETE"


def test_gate_chaining_blocks_on_escalate():
    # ESCALATE chains need human review → fail-closed block.
    esc = Finding(title="esc", file_path="x.py", line_range=(1, 1), severity=Severity.MEDIUM,
                  chain_potential=True, verdict=Verdict.ESCALATE)
    assert cicd_gate_check([esc])["status"] == "BLOCKED"


def test_gate_blocked_precedes_incomplete():
    # A real blocking finding outranks incomplete coverage.
    cov = {"total_code_files": 5, "scanned_files": 1, "unscanned_files": 0, "dropped_over_budget": 4}
    assert cicd_gate_check([_f(Severity.CRITICAL)], coverage=cov)["status"] == "BLOCKED"


def test_gate_passes_when_coverage_complete():
    cov = {"total_code_files": 2, "scanned_files": 2, "unscanned_files": 0, "dropped_over_budget": 0}
    assert cicd_gate_check([_f(Severity.LOW)], coverage=cov)["status"] == "PASSED"
