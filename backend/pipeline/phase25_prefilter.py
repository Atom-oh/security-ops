"""Phase 2.5 — deterministic secret pre-filter (no LLM).

High-precision detection of hardcoded credentials (CWE-798) so the pipeline catches obvious
secrets cheaply before burning Opus tokens. FP control (per the v2 panel): only flag
(a) known secret SHAPES, or (b) string LITERALS assigned to secret-named keys — never bare
UUIDs/hashes/session-ids, and never obvious placeholders.
"""
from __future__ import annotations

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
    ['"](?P<val>[^'"]{8,})['"]
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
        if m and not _is_placeholder(m.group("val")):
            out.append(
                _finding(file_path, idx, f"하드코딩된 시크릿 ({m.group('name')})", Severity.HIGH,
                         f"{m.group('name')}=…")
            )
    return out
