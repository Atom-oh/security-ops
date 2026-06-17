"""Phase 6 — aggregation, ASFF report, and CI/CD gate.

Emits AWS Security Finding Format (ASFF) records for Security Hub and a CI/CD gate verdict.
Gate policy: any Critical/High finding, or any finding with chaining potential, blocks the
pipeline (fail-closed for a financial-sector posture).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pipeline.config import Finding, Severity

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


def cicd_gate_check(findings: List[Finding], threshold: Optional[Dict] = None) -> Dict:
    """Return ``{status, blocked, info, reasons}``. Fail-closed on Critical/High/chaining."""
    blocking_sevs = _BLOCKING_SEVERITIES
    blocked = []
    for f in findings:
        if f.severity in blocking_sevs or f.chain_potential:
            blocked.append(f)
    info_count = len(findings) - len(blocked)
    reasons = [
        f"{f.severity.value.upper()} {f.title} ({f.file_path})"
        + (" [chaining]" if f.chain_potential else "")
        for f in blocked
    ]
    return {
        "status": "BLOCKED" if blocked else "PASSED",
        "blocked": len(blocked),
        "info": info_count,
        "reasons": reasons,
    }
