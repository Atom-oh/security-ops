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


def test_ignores_url_assigned_to_token_name():
    # HIGH #4: token_url="https://..." is config, not a secret → no FP block.
    assert _scan('token_url = "https://api.acme-corp.io/v1/oauth/authorize"') == []


def test_ignores_header_name():
    # An HTTP header name assigned to api_key_header must not flag.
    assert _scan('api_key_header = "X-Api-Key"') == []


def test_ignores_secret_store_reference():
    # A Secrets Manager / vault path reference is not a literal credential.
    assert _scan('db_password = "prod/db/password"') == []


def test_still_flags_high_entropy_secret():
    # A genuine random credential is still caught.
    f = _scan('api_key = "aZ4!kQ19vXp7Lm2RtY8w"')
    assert f and f[0].cwe_id == "CWE-798"


def test_flags_base64_secret_containing_slash():
    # Regression: a base64 AWS-style secret key contains '/' but must NOT be excluded as a path.
    f = _scan('aws_secret = "wJalrXUtnFEMIK7MDENGbPxRfiCYz9qLm2/RtY8wQ4z"')
    assert f and f[0].cwe_id == "CWE-798"


def test_flags_short_complex_password():
    # Regression: a short (<20 char, <3.5-entropy) but real password is still caught.
    f = _scan('password = "Summer2024!"')
    assert f and f[0].cwe_id == "CWE-798"


def test_flags_dollar_prefixed_password_not_treated_as_env():
    # Only ${VAR}/$ALLCAPS are env refs; a literal password starting with $ must be flagged.
    assert _scan('password = "$up3rS3cr3tValue"')
    # bcrypt-style hash assigned to a secret name is not mistaken for an env interpolation
    assert _scan('secret = "$2b$10$N9qo8uLOickgxBe1aZ4kQOabc"')


def test_ignores_env_interpolation():
    assert _scan('api_key = "${API_KEY}"') == []
    assert _scan('api_key = "$API_KEY"') == []
