# INTENTIONALLY VULNERABLE — FSI-Mythos scanner testbed (defensive corpus).
# CWE-22: path traversal — user-controlled filename joined onto a base dir.
import os

STATEMENT_DIR = "/var/fsi/statements"


def read_statement(filename: str) -> bytes:
    # No normalization/containment check → ../../etc/passwd escapes the base.
    path = os.path.join(STATEMENT_DIR, filename)  # CWE-22
    with open(path, "rb") as fh:
        return fh.read()
