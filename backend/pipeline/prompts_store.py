"""Versioned prompt store (ADR-001).

Externalizes the four editable agent **system** prompts (ranker, hunter, challenger,
validator) to DynamoDB as immutable, versioned items with an atomic active pointer,
reusing the existing scan-history table. Resolved + pinned (bodies inline) at
scan-creation time so a running scan is reproducible and the worker never reads the
store.

Security posture (see ADR-001):
- ``validate_prompt_body`` is **defense-in-depth**, not the injection control — the
  editable string is the trusted system channel, so the real controls are RBAC, the
  immutable code-side safety preamble (see ``agents.prompts``), immutability and audit.
- agentKey is allowlisted to the four known agents.
- Versions are immutable; activation is a compare-and-swap; prompt items never get a TTL.

This module is dependency-injected: pass a boto3 DynamoDB ``resource`` (or use
``InMemoryPromptStore`` in tests). Python 3.9-compatible.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

AGENT_KEYS = ("ranker", "hunter", "challenger", "validator")

MAX_BODY_BYTES = 20 * 1024
MAX_NOTE_CHARS = 500

# Defense-in-depth blocklist. NOT the primary injection control (the editable surface is
# the trusted system channel — RBAC + the immutable code preamble are the real controls).
_BANNED = [
    re.compile(r"ignore\s+(all\s+)?previous", re.I),
    re.compile(r"disregard\s+(?:\w+\s+){0,2}(previous|above|prior)", re.I),
    re.compile(r"\bsystem\s*:\s*you\s+are\s+now\b", re.I),
    re.compile(r"무시\s*(하|해|하고|하세요|하라|할)"),     # Korean "ignore"
    re.compile(r"이전\s*지침"),                            # Korean "previous instructions"
    # An edited prompt must not emit/close the untrusted-code nonce fence.
    re.compile(r"(?:<<<|>>>)\s*END_UNTRUSTED", re.I),
    re.compile(r"END_UNTRUSTED_[0-9a-f]+", re.I),
]

# Zero-width / formatting characters used to smuggle banned phrases past the blocklist.
_ZERO_WIDTH = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD], None
)


class PromptValidationError(ValueError):
    """Raised when a prompt body or note fails validation, or the agentKey is unknown."""


class PromptStoreUnavailable(RuntimeError):
    """Raised when the backing store is unreachable (vs. legitimately empty).

    Callers must fail closed — never silently fall back to defaults on an outage.
    """


def prompt_hash(body: str) -> str:
    """Canonical content hash: SHA-256 over the exact UTF-8 body. Defined once and reused
    by the inline-pin path so the worker can verify the body it received was not tampered."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    """NFKC-normalize and strip zero-width/control chars so obfuscated banned phrases are
    matched. Used only for *checking* — the stored body keeps the admin's original text."""
    stripped = text.translate(_ZERO_WIDTH)
    return unicodedata.normalize("NFKC", stripped)


def validate_prompt_body(agent_key: str, body: str, note: str = "") -> None:
    """Validate an editable system-prompt body (defense-in-depth). Raises
    ``PromptValidationError`` on an unknown agentKey, oversize body, banned pattern,
    unbalanced ``{``/``}`` (a stray placeholder), or an oversize note."""
    if agent_key not in AGENT_KEYS:
        raise PromptValidationError(f"unknown agentKey: {agent_key!r}")
    if not isinstance(body, str) or not body.strip():
        raise PromptValidationError("prompt body must be a non-empty string")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise PromptValidationError(f"prompt body exceeds {MAX_BODY_BYTES} bytes")
    if len(note) > MAX_NOTE_CHARS:
        raise PromptValidationError(f"note exceeds {MAX_NOTE_CHARS} chars")

    probe = _normalize(body)
    for rx in _BANNED:
        if rx.search(probe):
            raise PromptValidationError(f"prompt body matches a disallowed pattern: {rx.pattern}")

    # A stray unbalanced brace would break any later ``.format`` and is never legitimate in
    # an editable system body (the user-prompt builders own all real placeholders).
    if body.count("{") != body.count("}"):
        raise PromptValidationError("prompt body has unbalanced { } placeholders")
