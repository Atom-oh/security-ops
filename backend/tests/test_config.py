"""Tests for pipeline.config domain types."""
from __future__ import annotations

from pipeline.config import Finding, Language, ScanConfig, Severity, Verdict


def test_severity_ordering():
    assert Severity.CRITICAL.weight > Severity.HIGH.weight > Severity.MEDIUM.weight
    assert Severity.MEDIUM.weight > Severity.LOW.weight > Severity.INFO.weight
    ordered = sorted(
        [Severity.LOW, Severity.CRITICAL, Severity.MEDIUM],
        key=lambda s: s.weight,
        reverse=True,
    )
    assert ordered[0] is Severity.CRITICAL
    # str-enum: value is JSON-friendly
    assert Severity.CRITICAL.value == "critical"


def test_verdict_and_language_values():
    assert Verdict.CONFIRMED.value == "confirmed"
    assert {v.value for v in Verdict} == {"confirmed", "likely", "dismissed", "escalate"}
    assert Language.PYTHON.value == "python"
    assert Language.from_extension(".c") is Language.C
    assert Language.from_extension(".UNKNOWN") is None


def test_scanconfig_defaults():
    cfg = ScanConfig(project_path="/app/sample-target")
    assert cfg.max_files == 8
    assert cfg.pass_at_k == 1
    assert cfg.region == "ap-northeast-2"
    assert cfg.scan_scope == "defensive"
    assert cfg.fsi_mode is True
    assert "K-ISMS" in cfg.compliance_tags
    # role models present
    assert cfg.hunter_model and cfg.challenger_model and cfg.validator_model and cfg.ranker_model


def test_finding_id_is_deterministic():
    f1 = Finding(
        title="strcpy buffer overflow",
        file_path="transfer.c",
        line_range=(4, 8),
        severity=Severity.CRITICAL,
    )
    f2 = Finding(
        title="strcpy buffer overflow",
        file_path="transfer.c",
        line_range=(4, 8),
        severity=Severity.HIGH,  # severity not part of identity
    )
    assert f1.id == f2.id
    assert f1.id.startswith("fsi-")
    assert len(f1.id) == len("fsi-") + 16
    # different location → different id
    f3 = Finding(title="strcpy buffer overflow", file_path="other.c", line_range=(4, 8), severity=Severity.CRITICAL)
    assert f3.id != f1.id


def test_finding_to_dict_roundtrip():
    f = Finding(
        title="OS command injection",
        file_path="transfer.c",
        line_range=(6, 6),
        severity=Severity.CRITICAL,
        cwe_id="CWE-78",
        confidence=0.98,
        chain_potential=True,
        verdict=Verdict.CONFIRMED,
        validated=True,
    )
    d = f.to_dict()
    assert d["severity"] == "critical"
    assert d["verdict"] == "confirmed"
    assert d["cwe_id"] == "CWE-78"
    assert d["confidence"] == 0.98
    assert d["chain_potential"] is True
    assert d["id"] == f.id
