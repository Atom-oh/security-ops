"""Tests for Phase 2.5 deterministic secret pre-filter."""
from __future__ import annotations

from pipeline.config import Language, Severity
from pipeline.phase25_prefilter import scan_secrets


def _scan(content):
    return scan_secrets("config.py", Language.PYTHON, content=content)


def test_detects_aws_key():
    f = _scan('aws_key = "AKIA1234567890ABCDEF"')
    assert f and f[0].cwe_id == "CWE-798"
    assert f[0].severity in (Severity.CRITICAL, Severity.HIGH)


def test_detects_hardcoded_password_literal():
    f = _scan('password = "xK9$mP2vL8qR4wT7zN3bF6"')
    assert any("CWE-798" == x.cwe_id for x in f)


def test_detects_private_key_header():
    f = _scan("-----BEGIN RSA PRIVATE KEY-----")
    assert f and f[0].cwe_id == "CWE-798"


def test_ignores_uuid_not_secret_named():
    assert _scan('userId = "550e8400-e29b-41d4-a716-446655440000"') == []


def test_ignores_placeholder():
    assert _scan('api_key = "your-api-key-here"') == []


def test_ignores_short_value():
    assert _scan('password = "x"') == []


def test_ignores_example_aws_key():
    # AWS's documented EXAMPLE key must not be flagged
    assert _scan('k = "AKIAIOSFODNN7EXAMPLE"') == []
