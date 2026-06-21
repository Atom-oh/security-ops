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


# --- key helpers (single-table; PK reuses ``userId``, SK reuses ``scanId``) -----------

def _pk(agent_key: str) -> str:
    return f"PROMPT#{agent_key}"


def _vsk(version: int) -> str:
    return f"V#{version:06d}"  # zero-padded width 6 → lexical sort == numeric sort


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _rand() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def _default_bodies():
    """Code-side default system bodies — the seed/fallback when the store has no active
    version. Sourced from the hardcoded constants so they can never drift out of existence."""
    from agents.prompts import (
        CHALLENGER_SYSTEM,
        HUNTER_SYSTEM,
        RANKER_SYSTEM,
        VALIDATOR_SYSTEM,
    )
    return {
        "ranker": RANKER_SYSTEM,
        "hunter": HUNTER_SYSTEM,
        "challenger": CHALLENGER_SYSTEM,
        "validator": VALIDATOR_SYSTEM,
    }


class _StoreBase:
    """Shared logic (resolve/audit shaping) over a minimal item-CRUD surface that each
    backend implements: ``_put_new(pk, sk, item)`` (conditional create), ``_get(pk, sk)``,
    ``_query_prefix(pk, prefix)``, ``_cas_active(pk, version, expected_prev)``."""

    def create_version(self, agent_key: str, body: str, author: str, note: str = "") -> dict:
        validate_prompt_body(agent_key, body, note)
        if not author:
            raise PromptValidationError("author is required")
        pk = _pk(agent_key)
        for _ in range(8):  # bounded retry on a concurrent next-version collision
            existing = self._query_prefix(pk, "V#")
            nxt = max((int(i["version"]) for i in existing), default=0) + 1
            item = {
                "userId": pk,
                "scanId": _vsk(nxt),
                "version": nxt,
                "body": body,
                "hash": prompt_hash(body),
                "author": author,
                "note": note,
                "createdAt": _now_iso(),
            }
            if self._put_new(pk, _vsk(nxt), item):
                self._audit(agent_key, "create", author, nxt)
                return {k: item[k] for k in ("version", "body", "hash", "author", "note", "createdAt")}
        raise PromptStoreUnavailable("could not allocate a new version after retries")

    def get_version(self, agent_key: str, version: int) -> Optional[dict]:
        item = self._get(_pk(agent_key), _vsk(int(version)))
        if not item:
            return None
        return {
            "version": int(item["version"]),
            "body": item["body"],
            "hash": item.get("hash") or prompt_hash(item["body"]),
            "author": item.get("author"),
            "note": item.get("note", ""),
            "createdAt": item.get("createdAt"),
            "validatedHash": item.get("validatedHash"),
            "validatedAt": item.get("validatedAt"),
        }

    def list_versions(self, agent_key: str) -> list:
        rows = self._query_prefix(_pk(agent_key), "V#")
        rows.sort(key=lambda i: int(i["version"]))
        return [
            {
                "version": int(i["version"]),
                "body": i["body"],
                "hash": i.get("hash") or prompt_hash(i["body"]),
                "author": i.get("author"),
                "note": i.get("note", ""),
                "createdAt": i.get("createdAt"),
                "validatedHash": i.get("validatedHash"),
            }
            for i in rows
        ]

    def list_audit(self, agent_key: str) -> list:
        rows = self._query_prefix(_pk(agent_key), "AUDIT#")
        rows.sort(key=lambda i: i["scanId"])
        return [{"event": i["event"], "actor": i.get("actor"), "version": i.get("version"),
                 "at": i.get("createdAt")} for i in rows]

    def activate(self, agent_key: str, version: int, updated_by: str,
                 expected_prev: Optional[int] = None) -> bool:
        if agent_key not in AGENT_KEYS:
            raise PromptValidationError(f"unknown agentKey: {agent_key!r}")
        if self.get_version(agent_key, version) is None:
            raise PromptValidationError(f"cannot activate non-existent version {version}")
        won = self._cas_active(_pk(agent_key), int(version), expected_prev, updated_by)
        if won:
            self._audit(agent_key, "activate", updated_by, int(version))
        return won

    def get_active(self, agent_key: str) -> Optional[int]:
        item = self._get(_pk(agent_key), "ACTIVE")
        if not item or item.get("activeVersion") is None:
            return None
        return int(item["activeVersion"])

    def stamp_validated(self, agent_key: str, version: int, validated_hash: str) -> None:
        """Record server-side that ``version`` passed preview/validation (Task 10). Idempotent:
        the stamp can only equal the immutable version's own hash."""
        v = self.get_version(agent_key, version)
        if v is None:
            raise PromptValidationError(f"cannot validate non-existent version {version}")
        if validated_hash != v["hash"]:
            raise PromptValidationError("validated hash does not match the version body")
        self._patch(_pk(agent_key), _vsk(int(version)),
                    {"validatedHash": validated_hash, "validatedAt": _now_iso()})

    def resolve_active_set(self) -> dict:
        """Resolve the active body+version+hash per agent for inline pinning at scan creation.

        Empty (no active version) → code default (legit first-run). Store **error**
        (unreachable/throttled/missing table) → ``PromptStoreUnavailable`` so the caller fails
        closed rather than silently scanning with defaults during an outage."""
        from botocore.exceptions import BotoCoreError, ClientError

        defaults = _default_bodies()
        out = {}
        for agent in AGENT_KEYS:
            try:
                active = self.get_active(agent)
                ver = self.get_version(agent, active) if active is not None else None
            except (ClientError, BotoCoreError) as exc:
                raise PromptStoreUnavailable(f"prompt store unreachable: {exc}") from exc
            if active is None:
                # legitimately empty (no active version) → trusted code default
                body = defaults[agent]
                out[agent] = {"version": "default", "body": body, "hash": prompt_hash(body)}
                continue
            if ver is None:
                # ACTIVE points at a version that doesn't exist → corruption, NOT a reason to
                # silently downgrade. Fail closed (immutable versions should never disappear).
                raise PromptStoreUnavailable(
                    f"active pointer for {agent!r} references missing version {active}"
                )
            # defense-in-depth: the stored body must still hash to its stored hash
            if prompt_hash(ver["body"]) != ver["hash"]:
                raise PromptStoreUnavailable(f"stored prompt hash mismatch for {agent!r} v{active}")
            out[agent] = {"version": ver["version"], "body": ver["body"], "hash": ver["hash"]}
        return out

    def _audit(self, agent_key: str, event: str, actor: str, version) -> None:
        sk = f"AUDIT#{_now_iso()}#{_rand()}"
        self._put_new(_pk(agent_key), sk, {
            "userId": _pk(agent_key), "scanId": sk, "event": event,
            "actor": actor, "version": version, "createdAt": _now_iso(),
        })


class PromptStore(_StoreBase):
    """DynamoDB-backed prompt store. Reuses the scan-history table; injected ``resource``
    for tests (mirrors ``tools.history.ScanHistory``)."""

    def __init__(self, table_name: str, region: Optional[str] = None, resource=None):
        self.table_name = table_name
        self._resource = resource
        self._region = region

    @property
    def table(self):
        if self._resource is None:
            import boto3
            self._resource = boto3.resource("dynamodb", region_name=self._region)
        return self._resource.Table(self.table_name)

    def _put_new(self, pk: str, sk: str, item: dict) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(scanId)")
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def _get(self, pk: str, sk: str) -> Optional[dict]:
        return self.table.get_item(Key={"userId": pk, "scanId": sk}).get("Item")

    def _query_prefix(self, pk: str, prefix: str) -> list:
        # Paginate: a single Query truncates at 1 MB (~50 × 20 KB bodies). Without this,
        # create_version's max-version calc and list_versions/list_audit would silently drop
        # the newest items past the first page.
        from boto3.dynamodb.conditions import Key

        cond = Key("userId").eq(pk) & Key("scanId").begins_with(prefix)
        items, start = [], None
        while True:
            kw = {"KeyConditionExpression": cond}
            if start:
                kw["ExclusiveStartKey"] = start
            resp = self.table.query(**kw)
            items.extend(resp.get("Items", []))
            start = resp.get("LastEvaluatedKey")
            if not start:
                return items

    def _patch(self, pk: str, sk: str, fields: dict) -> None:
        sets, names, values = [], {}, {}
        for i, (k, v) in enumerate(fields.items()):
            sets.append(f"#k{i} = :v{i}")
            names[f"#k{i}"] = k
            values[f":v{i}"] = v
        self.table.update_item(
            Key={"userId": pk, "scanId": sk},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def _cas_active(self, pk: str, version: int, expected_prev: Optional[int], updated_by: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            if expected_prev is None:
                cond = "attribute_not_exists(activeVersion)"
                values = {":v": version, ":u": updated_by, ":t": _now_iso()}
            else:
                cond = "activeVersion = :p"
                values = {":v": version, ":u": updated_by, ":t": _now_iso(), ":p": int(expected_prev)}
            self.table.update_item(
                Key={"userId": pk, "scanId": "ACTIVE"},
                UpdateExpression="SET activeVersion = :v, updatedBy = :u, updatedAt = :t",
                ConditionExpression=cond,
                ExpressionAttributeValues=values,
            )
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise


class InMemoryPromptStore(_StoreBase):
    """In-memory fake mirroring ``PromptStore`` semantics for unit tests."""

    def __init__(self):
        self._items = {}  # (pk, sk) -> item dict

    def _put_new(self, pk: str, sk: str, item: dict) -> bool:
        if (pk, sk) in self._items:
            return False
        self._items[(pk, sk)] = dict(item)
        return True

    def _get(self, pk: str, sk: str) -> Optional[dict]:
        it = self._items.get((pk, sk))
        return dict(it) if it else None

    def _query_prefix(self, pk: str, prefix: str) -> list:
        return [dict(v) for (p, s), v in self._items.items() if p == pk and s.startswith(prefix)]

    def _patch(self, pk: str, sk: str, fields: dict) -> None:
        if (pk, sk) in self._items:
            self._items[(pk, sk)].update(fields)

    def _cas_active(self, pk: str, version: int, expected_prev: Optional[int], updated_by: str) -> bool:
        cur = self._items.get((pk, "ACTIVE"))
        cur_v = cur.get("activeVersion") if cur else None
        if expected_prev is None:
            if cur_v is not None:
                return False
        elif cur_v != int(expected_prev):
            return False
        self._items[(pk, "ACTIVE")] = {
            "userId": pk, "scanId": "ACTIVE", "activeVersion": int(version),
            "updatedBy": updated_by, "updatedAt": _now_iso(),
        }
        return True
