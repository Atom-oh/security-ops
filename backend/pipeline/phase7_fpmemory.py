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
    """A location-independent FP fingerprint (so the same class of FP is recognized
    across files)."""
    return {"cwe_id": f.cwe_id, "title": f.title.strip().lower()}


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
    findings unchanged."""
    try:
        known = {(p.get("cwe_id"), p.get("title")) for p in store.recall(user_id)}
    except Exception:
        return findings
    if not known:
        return findings
    return [
        f for f in findings
        if (_signature(f)["cwe_id"], _signature(f)["title"]) not in known
    ]
