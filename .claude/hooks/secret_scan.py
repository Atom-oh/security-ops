#!/usr/bin/env python3
"""PreToolUse secret scanner — reads the hook JSON on stdin, exits 2 to BLOCK a write that
contains a likely hardcoded credential in a non-test file. Allowlists test/fixture/sample-target
paths, *.md docs, and obvious placeholders / AWS EXAMPLE keys."""
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # can't parse → don't block

ti = data.get("tool_input", {}) or {}
path = ti.get("file_path", "") or ""

ALLOW_PATHS = ("/tests/", "test_", "/sample-target/", ".env.example", "secret-samples", "false-positives")
if path.endswith(".md") or any(a in path for a in ALLOW_PATHS):
    sys.exit(0)

parts = [ti.get("content", ""), ti.get("new_string", "")]
for e in ti.get("edits", []) or []:
    parts.append(e.get("new_string", ""))
text = "\n".join(p for p in parts if p)
if not text:
    sys.exit(0)

PLACEHOLDER = re.compile(r"(?i)example|changeme|your[-_]|placeholder|dummy|xxxx|<[^>]+>|\$\{?[A-Z_]+\}?")
PATTERNS = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("hardcoded secret", re.compile(
        r"""(?ix)\b[a-z0-9_]*(?:secret|passwd|password|api[_-]?key|apikey|token|credential)[a-z0-9_]*"""
        r"""\s*[:=]\s*['"]([^'"]{12,})['"]""")),
]
for label, rx in PATTERNS:
    m = rx.search(text)
    if not m:
        continue
    val = m.group(1) if m.groups() else m.group(0)
    if PLACEHOLDER.search(val):
        continue
    sys.stderr.write(
        f"secret-scan blocked this write: possible {label} in {path or '<file>'}.\n"
        f"Externalize it (Secrets Manager / env var) and reference it instead. "
        f"If this is a test fixture, place it under tests/ or sample-target/.\n")
    sys.exit(2)
sys.exit(0)
