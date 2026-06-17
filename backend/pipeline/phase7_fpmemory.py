"""Phase 7 — false-positive memory.

Dismissed findings are recorded as FP *patterns* so later scans can pre-suppress the same
noise. In production this is backed by AgentCore Memory (per-user namespace); here we also
ship an in-memory store used by tests and local runs. Both satisfy the ``FPStore`` shape:
``record(user_id, pattern)`` and ``recall(user_id) -> list[pattern]``.
"""
from __future__ import annotations

from typing import Dict, List

from pipeline.config import Finding


def _signature(f: Finding) -> Dict:
    """A *location-scoped* FP fingerprint: keyed by (file, cwe, title).

    Scoping to the file is deliberate. A class-only key ((cwe, title)) lets one dismissed
    'SQL injection' silently suppress every real SQLi in *other* files — a global
    false-negative ratchet. Keying by file confines suppression to the exact place the FP
    was dismissed, so same-class vulns elsewhere still reach Challenger/Validator.
    """
    return {
        "file_path": f.file_path,
        "cwe_id": f.cwe_id,
        "title": f.title.strip().lower(),
    }


def _key(sig: Dict) -> tuple:
    return (sig.get("file_path"), sig.get("cwe_id"), sig.get("title"))


class InMemoryFPStore:
    """Dict-backed FP store keyed by user id (fake for tests / local dev)."""

    def __init__(self) -> None:
        self._by_user: Dict[str, List[Dict]] = {}

    def record(self, user_id: str, pattern: Dict) -> None:
        self._by_user.setdefault(user_id, []).append(pattern)

    def recall(self, user_id: str) -> List[Dict]:
        return list(self._by_user.get(user_id, []))


class AgentCoreFPStore:
    """FP store backed by AgentCore Memory. Lazily binds the client so unit tests that use
    the in-memory store never import the SDK.

    The per-user namespace is used consistently for both write and read (``fp/<user_id>``)
    so recall actually finds what record wrote, and recall paginates via ``nextToken`` so a
    growing FP history isn't silently truncated. Verify the exact Memory API shape against
    your AgentCore SDK version at deploy time.
    """

    def __init__(self, memory_id: str, region=None, client=None) -> None:
        self.memory_id = memory_id
        self._region = region
        self._client = client

    @staticmethod
    def _namespace(user_id: str) -> str:
        return f"fp/{user_id}"

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-agentcore", region_name=self._region)
        return self._client

    def record(self, user_id: str, pattern: Dict) -> None:
        import json

        self.client.create_event(
            memoryId=self.memory_id,
            actorId=user_id,
            sessionId=self._namespace(user_id),
            payload=[{"text": json.dumps({"fp": pattern}, ensure_ascii=False)}],
        )

    def recall(self, user_id: str) -> List[Dict]:
        import json

        out: List[Dict] = []
        next_token = None
        while True:
            kwargs = dict(
                memoryId=self.memory_id,
                namespace=self._namespace(user_id),
                searchCriteria={"searchQuery": "fp"},
            )
            if next_token:
                kwargs["nextToken"] = next_token
            resp = self.client.retrieve_memory_records(**kwargs)
            for rec in resp.get("memoryRecords", []):
                try:
                    out.append(json.loads(rec["content"]["text"])["fp"])
                except (KeyError, ValueError, TypeError):
                    continue
            next_token = resp.get("nextToken")
            if not next_token:
                break
        return out


def record_false_positives(store, dismissed: List[Finding], user_id: str) -> None:
    for f in dismissed:
        try:
            store.record(user_id, _signature(f))
        except Exception:
            continue  # memory write failures must never break the scan


def suppress_known_fps(store, findings: List[Finding], user_id: str) -> List[Finding]:
    """Drop findings matching a remembered FP pattern. Isolated: any store error returns the
    findings unchanged.

    Migration note: patterns recorded before location-scoping (no ``file_path``) key as
    ``(None, cwe, title)`` and therefore stop matching real findings. This is intentional —
    those legacy FPs resurface once, get re-dismissed per file, and are re-recorded with a
    ``file_path``. We deliberately do NOT honor legacy patterns globally: that would
    reinstate the cross-file false-negative ratchet this scoping removes. Resurfacing an FP
    is the safe direction (more review, never a missed vuln)."""
    try:
        known = {_key(p) for p in store.recall(user_id)}
    except Exception:
        return findings
    if not known:
        return findings
    return [f for f in findings if _key(_signature(f)) not in known]
