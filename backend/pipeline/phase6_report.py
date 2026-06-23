"""Phase 6 — aggregation, ASFF report, and CI/CD gate.

Emits AWS Security Finding Format (ASFF) records for Security Hub and a CI/CD gate verdict.
Gate policy: any Critical/High finding, or any finding with chaining potential, blocks the
pipeline (fail-closed for a financial-sector posture).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pipeline.config import Finding, Severity, Verdict

_ASFF_SEVERITY = {
    Severity.CRITICAL: {"Label": "CRITICAL", "Normalized": 90},
    Severity.HIGH: {"Label": "HIGH", "Normalized": 70},
    Severity.MEDIUM: {"Label": "MEDIUM", "Normalized": 40},
    Severity.LOW: {"Label": "LOW", "Normalized": 10},
    Severity.INFO: {"Label": "INFORMATIONAL", "Normalized": 0},
}

# Severities that block a deploy regardless of chaining.
_BLOCKING_SEVERITIES = {Severity.CRITICAL, Severity.HIGH}


def to_asff(finding: Finding, account_id: str, region: str, created_at: Optional[str] = None) -> Dict:
    """Render one finding as an ASFF record.

    ``created_at`` (ISO8601) defaults to now — Security Hub tracks finding lifecycle by these
    timestamps, so they must be dynamic, not hardcoded.
    """
    ts = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {
        "SchemaVersion": "2018-10-08",
        "Id": finding.id,
        "ProductArn": (
            f"arn:aws:securityhub:{region}:{account_id}:product/{account_id}/fsi-mythos"
        ),
        "GeneratorId": "fsi-mythos-pipeline",
        "AwsAccountId": account_id,
        "Types": ["Software and Configuration Checks/Vulnerabilities/CVE"],
        "CreatedAt": ts,
        "UpdatedAt": ts,
        "Severity": _ASFF_SEVERITY.get(finding.severity, _ASFF_SEVERITY[Severity.INFO]),
        "Title": finding.title,
        "Description": finding.description or finding.title,
        "Resources": [
            {
                "Type": "Other",
                "Id": finding.file_path,
                "Details": {"Other": {"LineRange": str(list(finding.line_range))}},
            }
        ],
        "Remediation": {"Recommendation": {"Text": finding.patch_suggestion or "N/A"}},
        "FindingProviderFields": {
            "Confidence": int(round(finding.confidence * 100)),
            "Types": [finding.cwe_id] if finding.cwe_id else [],
        },
    }


def generate_report(findings: List[Finding]) -> Dict:
    """Summarize findings (counts by severity + chaining) plus the serialized list."""

    def count(sev: Severity) -> int:
        return sum(1 for f in findings if f.severity is sev)

    return {
        "total_findings": len(findings),
        "critical": count(Severity.CRITICAL),
        "high": count(Severity.HIGH),
        "medium": count(Severity.MEDIUM),
        "low": count(Severity.LOW),
        "info": count(Severity.INFO),
        "chaining": sum(1 for f in findings if f.chain_potential),
        "findings": [f.to_dict() for f in findings],
    }


def cicd_gate_check(
    findings: List[Finding],
    coverage: Optional[Dict] = None,
    threshold: Optional[Dict] = None,
) -> Dict:
    """Return ``{status, blocked, info, incomplete, reasons}``. Fail-closed.

    ``status`` is one of ``BLOCKED`` / ``INCOMPLETE`` / ``PASSED``:

    * **BLOCKED** — a Critical/High finding, or a *validated* chaining finding, exists.
      ``chain_potential`` only blocks when the finding survived validation
      (verdict CONFIRMED/LIKELY): a raw single-file Hunter guess no longer hard-blocks CI
      (HIGH-4b). High-confidence deterministic findings (e.g. secret prefilter, no LLM
      verdict) still block via severity.
    * **INCOMPLETE** — no blocking finding, but ``coverage`` shows files were *dropped over
      budget* (never even considered) or *nothing* was deep-scanned while code exists. A scan
      that couldn't look at part of the codebase must not certify "clean" (HIGH #1). Files
      merely deprioritized below the ``max_files`` deep-scan cap do NOT force INCOMPLETE —
      they are risk-ranked and still secret-scanned (Phase 2.5); the count is reported in
      ``coverage`` for transparency and surfaced as an advisory reason.
    * **PASSED** — no blocking findings and nothing dropped over budget.
    """
    blocked = []
    for f in findings:
        sev_block = f.severity in _BLOCKING_SEVERITIES
        # chaining blocks only once the finding is past raw Hunter output: CONFIRMED/LIKELY,
        # or ESCALATE (needs human review → fail-closed). A raw unvalidated/DISMISSED guess
        # does not hard-block (HIGH-4b).
        chain_block = f.chain_potential and f.verdict in (
            Verdict.CONFIRMED, Verdict.LIKELY, Verdict.ESCALATE,
        )
        if sev_block or chain_block:
            blocked.append(f)
    info_count = len(findings) - len(blocked)
    reasons = [
        f"{f.severity.value.upper()} {f.title} ({f.file_path})"
        + (" [chaining]" if f.chain_potential else "")
        for f in blocked
    ]

    incomplete = False
    if coverage:
        unscanned = coverage.get("unscanned_files", 0) or 0
        dropped = coverage.get("dropped_over_budget", 0) or 0
        total = coverage.get("total_code_files", 0) or 0
        scanned = coverage.get("scanned_files", 0) or 0
        if dropped > 0:  # files we couldn't even consider → fail-closed
            reasons.append(f"{dropped} file(s) dropped over budget — never scanned")
            incomplete = True
        if total > 0 and scanned == 0:  # nothing deep-scanned at all → fail-closed
            reasons.append("no files were deep-scanned — cannot certify clean")
            incomplete = True
        if unscanned > 0:  # risk-deprioritized below max_files — advisory only, not blocking
            reasons.append(
                f"advisory: {unscanned}/{total} lower-risk file(s) not deep-scanned "
                f"(max_files cap; still secret-scanned)"
            )

    if blocked:
        status = "BLOCKED"
    elif incomplete:
        status = "INCOMPLETE"
    else:
        status = "PASSED"
    return {
        "status": status,
        "blocked": len(blocked),
        "info": info_count,
        "incomplete": incomplete,
        "reasons": reasons,
    }
