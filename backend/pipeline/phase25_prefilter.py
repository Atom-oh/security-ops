"""Phase 2.5 — deterministic secret pre-filter (no LLM).

High-precision detection of hardcoded credentials (CWE-798) so the pipeline catches obvious
secrets cheaply before burning Opus tokens. FP control (per the v2 panel): only flag
(a) known secret SHAPES, or (b) string LITERALS assigned to secret-named keys — never bare
UUIDs/hashes/session-ids, and never obvious placeholders.
"""
from __future__ import annotations

import math
import re
from typing import List

from pipeline.config import Finding, Severity

# Known high-confidence secret shapes.
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")

# secret-y assignment: name = "literal"
_SECRET_ASSIGN = re.compile(
    r"""(?ix)
    \b(?P<name>[a-z0-9_]*(?:secret|passwd|password|api[_-]?key|apikey|token|credential|private[_-]?key)[a-z0-9_]*)
    \s*[:=]\s*
    ['"](?P<val>(?:\\.|[^'"]){8,})['"]
    """
)

_PLACEHOLDERS = (
    "example", "changeme", "change-me", "your-", "your_", "yourapi", "placeholder",
    "dummy", "test", "sample", "xxxx", "<", "redacted", "todo", "none", "null",
)


def _is_placeholder(val: str) -> bool:
    v = val.lower()
    if any(p in v for p in _PLACEHOLDERS):
        return True
    if len(set(val)) <= 2:  # "aaaaaaa", "00000000"
        return True
    return False


# Config/reference values (not literal credentials) that cause the bulk of prefilter FPs:
# a URL (token_url="https://..."), an ARN, an env interpolation, a Secrets-Manager path
# ("prod/db/password"), or an HTTP header name ("X-Api-Key"). Excluded PRECISELY — never by
# a blunt `"/" in val`, which would drop real base64 secret keys (they contain `/`).
_SCHEME_ARN = re.compile(r"(?ix)^(?:[a-z][a-z0-9+.\-]*://|arn:aws:)")  # URL scheme / ARN
# Env interpolation ONLY: ``${VAR}`` or bare ``$ALLCAPS`` — NOT every ``$``-prefixed value.
# (A blunt ``$`` exclusion would blind us to bcrypt/argon2 hashes like ``$2b$..`` and to
# passwords such as ``$up3rS3cr3t``.) Case-sensitive on purpose.
_ENV_REF = re.compile(r"^\$(?:\{[A-Za-z_]\w*\}|[A-Z][A-Z0-9_]*)$")
_PATH_REF = re.compile(r"^[\w.\-]+(?:/[\w.\-]+)+$")              # a/b/c style ref
_HEADER_REF = re.compile(r"^[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+$")  # X-Api-Key


def _shannon(s: str) -> float:
    """Shannon entropy in bits/char (0 for empty)."""
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    n = len(s)
    return -sum((k / n) * math.log2(k / n) for k in counts.values())


def _is_credential_like(val: str) -> bool:
    """Decide whether a value assigned to a *secret-named* key is a literal credential.

    The name already signals intent (api_key/password/token/...), so we flag broadly and
    only carve out clear non-secrets:
      * placeholders;
      * scheme URLs / ARNs / ``${ENV}`` interpolations;
      * low-entropy path or header references (``prod/db/password``, ``X-Api-Key``) — but a
        high-entropy value that merely contains ``/`` or ``-`` (a base64 secret key) is KEPT;
      * anything shorter than 8 chars.
    This keeps real secrets (incl. base64 with ``/`` and short complex passwords) while
    dropping the URL/header/ref false positives."""
    if _is_placeholder(val):
        return False
    if _SCHEME_ARN.match(val) or _ENV_REF.match(val):
        return False
    if _shannon(val) < 3.6 and (_PATH_REF.match(val) or _HEADER_REF.match(val)):
        return False
    return len(val) >= 8


def _finding(path: str, lineno: int, title: str, severity: Severity, evidence: str) -> Finding:
    return Finding(
        title=title,
        file_path=path,
        line_range=(lineno, lineno),
        severity=severity,
        cwe_id="CWE-798",
        description=f"하드코딩된 자격증명 의심: {evidence}",
        patch_suggestion="시크릿을 코드에서 제거하고 Secrets Manager/환경변수로 외부화하세요.",
        confidence=0.9,
        validated=True,
    )


def scan_secrets(file_path: str, language=None, content: str = "") -> List[Finding]:
    out: List[Finding] = []
    for idx, line in enumerate((content or "").splitlines(), start=1):
        if "EXAMPLE" in line:  # AWS-documented example keys etc.
            continue
        if _AWS_KEY.search(line):
            out.append(_finding(file_path, idx, "하드코딩된 AWS 액세스 키", Severity.CRITICAL, "AKIA…"))
            continue
        if _PRIVATE_KEY.search(line):
            out.append(_finding(file_path, idx, "하드코딩된 개인 키", Severity.CRITICAL, "PRIVATE KEY"))
            continue
        m = _SECRET_ASSIGN.search(line)
        if m and _is_credential_like(m.group("val")):
            out.append(
                _finding(file_path, idx, f"하드코딩된 시크릿 ({m.group('name')})", Severity.HIGH,
                         f"{m.group('name')}=…")
            )
    return out
