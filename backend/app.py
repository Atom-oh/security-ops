"""AgentCore Runtime entrypoint for FSI-Mythos.

The browser calls the Runtime ``/invocations`` endpoint directly with a Cognito access
token, so this handler must (1) answer CORS preflight, (2) avoid the synchronous timeout on
long 8-phase scans via an async dispatch path, and (3) isolate persistence failures.

The HTTP/SDK glue is thin: ``route(payload, context, deps)`` is pure and unit-tested; the
``BedrockAgentCoreApp`` entrypoint just builds ``Deps`` from the environment and delegates.
"""
from __future__ import annotations

import base64
import re
import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from agents.bedrock import BedrockConverse
from pipeline.config import ScanConfig
from pipeline.orchestrator import FSIMythosPipeline
from pipeline.prompts_store import (
    PromptStoreUnavailable,
    PromptValidationError,
    prompt_hash,
)
from tools.staleness import DEFAULT_STALE_AFTER_SEC, annotate_stale

# Cognito group that may edit/activate prompts (ADR-001 RBAC). Server-side authoritative.
PROMPT_ADMIN_GROUP = os.environ.get("PROMPT_ADMIN_GROUP", "admin")
_PROMPT_ACTIONS = ("prompt_list", "prompt_get", "prompt_create", "prompt_preview", "prompt_activate")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fsi.app")

CORS_HEADERS = {
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _stale_after_sec() -> int:
    try:
        return int(os.environ.get("STALE_AFTER_SEC", DEFAULT_STALE_AFTER_SEC))
    except ValueError:
        return DEFAULT_STALE_AFTER_SEC


def _new_scan_id() -> str:
    return f"{_now_iso()}#{uuid.uuid4().hex[:8]}"


def _cors(origin: str) -> Dict:
    return {"Access-Control-Allow-Origin": origin or "*", **CORS_HEADERS}


def _default_spawn(fn: Callable[[], None]) -> None:
    """Run an async job in a background daemon thread — LOCAL/DEV ONLY.

    WARNING: this is NOT durable on AgentCore Runtime. The runtime is request/response: once
    the entrypoint returns, the microVM is frozen/reaped and this thread is killed mid-scan,
    stranding the record IN_PROGRESS. Production must set ``Deps.dispatch`` to enqueue the scan
    to SQS for a long-running Fargate worker (see ``SqsDispatchSpawn`` / ``scan_worker``).
    """
    threading.Thread(target=fn, daemon=True).start()


class SqsDispatchSpawn:
    """Durable async dispatch: enqueue the scan to SQS for a Fargate worker to run to
    completion (off the request-scoped AgentCore runtime). ``__call__`` takes the worker
    MESSAGE (not a thunk) so the job survives the entrypoint returning."""

    def __init__(self, queue_url: str, client=None, region: Optional[str] = None):
        self.queue_url = queue_url
        self._client = client
        self._region = region

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("sqs", region_name=self._region)
        return self._client

    def __call__(self, message: Dict) -> None:
        self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps(message))


@dataclass
class Deps:
    """Injected collaborators. Everything is overridable for tests."""

    converse: object = None
    history: object = None
    fp_store: object = None
    sandbox: object = None
    openai_provider: object = None
    prompt_store: object = None  # ADR-001 versioned prompt store (None → code defaults)
    benchmark_runner: object = None  # optional injected dry-run; when set, activation requires a pass
    # When the deployment uses the prompt store, the (storeless) worker must REFUSE a scan whose
    # inline pinned bundle is absent — otherwise a fully-stripped message would run on defaults.
    require_pinned_prompts: bool = False
    account_id: str = "000000000000"
    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-west-2"))
    allowed_origin: str = field(default_factory=lambda: os.environ.get("FRONTEND_ORIGIN", "*"))
    spawn: Callable[[Callable[[], None]], None] = _default_spawn
    # Durable dispatcher: takes a worker message dict and enqueues it (SQS in prod). When None,
    # scan_async falls back to the in-thread spawn (local/dev only — not durable).
    dispatch: Optional[Callable[[Dict], None]] = None


def _decode_jwt_claims(token: str) -> Dict:
    """Decode (NOT verify) a JWT payload. The AgentCore JWT authorizer has already verified
    the signature/audience before the request reaches us, so we only need the claims."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # pad base64url
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def _headers_from_context(context) -> Dict[str, str]:
    """AgentCore passes a RequestContext with ``request_headers``; also tolerate a dict or an
    object exposing ``.claims`` (older shape / tests)."""
    if context is None:
        return {}
    hdrs = getattr(context, "request_headers", None)
    if hdrs is None and isinstance(context, dict):
        hdrs = context.get("request_headers")
    return hdrs or {}


def _user_id(payload: Dict, context) -> str:
    """Stable per-user identity from the verified bearer JWT — never from the request payload.

    The SPA sends the Cognito ACCESS token as ``Authorization: Bearer <jwt>``; AgentCore's JWT
    authorizer verifies it, then we read the claims off the request header. Prefer ``sub`` (the
    stable per-user UUID, always present in an access token). Falls back to a context ``claims``
    dict (tests) and, only when ``FSI_ALLOW_PAYLOAD_USER=1``, the payload (local dev).
    """
    # 1) bearer JWT from the request headers (the real deployed path)
    headers = _headers_from_context(context)
    auth = ""
    for k, v in headers.items():
        if k.lower() == "authorization":
            auth = v or ""
            break
    if auth.lower().startswith("bearer "):
        claims = _decode_jwt_claims(auth[7:])
        # Require a per-user identity. Drop the ``client_id`` fallback: a machine/client-credentials
        # token has no ``sub`` and would collapse every such caller into one DynamoDB partition
        # (cross-tenant exposure). ``sub`` is always present on a Cognito user access token.
        identity = claims.get("sub") or claims.get("username")
        if identity:
            return identity

    # 2) explicit claims on the context (test/ID-token shape)
    claims = getattr(context, "claims", None) or (
        context.get("claims") if isinstance(context, dict) else None
    ) or {}
    identity = claims.get("sub") or claims.get("username") or claims.get("email")
    if identity:
        return identity

    # 3) local-dev escape hatch only
    if os.environ.get("FSI_ALLOW_PAYLOAD_USER") == "1":
        return payload.get("user_id") or "anonymous"
    return "anonymous"


# Server-side upload caps (the frontend also bounds these, but a direct caller must not be able
# to exhaust disk/memory before the pipeline's budget guard runs). Decoded bytes, not wire bytes.
MAX_UPLOAD_FILES = 200
MAX_UPLOAD_TOTAL_BYTES = 8 * 1024 * 1024  # 8 MiB total
MAX_UPLOAD_FILE_BYTES = 1 * 1024 * 1024   # 1 MiB per file


def _materialize_upload(payload: Dict) -> Optional[str]:
    """If the payload carries uploaded files, write them to a temp dir and return it.

    Hardened against path traversal ("zip slip"): each resolved destination must stay inside
    the temp root, else the entry is skipped. Also bounds file count and decoded bytes
    server-side (a direct caller could otherwise exhaust disk before the budget guard runs).
    """
    upload = payload.get("upload")
    if not upload or not upload.get("files"):
        return None
    files = upload["files"]
    if len(files) > MAX_UPLOAD_FILES:
        raise ValueError(f"upload exceeds {MAX_UPLOAD_FILES} files")
    root = tempfile.mkdtemp(prefix="fsi-upload-")
    root_abs = os.path.abspath(root)
    total = 0
    for f in files:
        rel = f.get("path", "").lstrip("/")
        if not rel:
            continue
        dest = os.path.abspath(os.path.join(root, rel))
        if dest != root_abs and not dest.startswith(root_abs + os.sep):
            continue  # path traversal attempt — skip
        data = f.get("content_b64")
        raw = base64.b64decode(data) if data else (f.get("content", "").encode())
        if len(raw) > MAX_UPLOAD_FILE_BYTES:
            raise ValueError(f"upload file {rel!r} exceeds {MAX_UPLOAD_FILE_BYTES} bytes")
        total += len(raw)
        if total > MAX_UPLOAD_TOTAL_BYTES:
            raise ValueError(f"upload exceeds {MAX_UPLOAD_TOTAL_BYTES} total bytes")
        os.makedirs(os.path.dirname(dest) or root, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(raw)
    return root


# Server-side validation of client-controlled scan inputs (the frontend bounds these too, but a
# direct caller must not bypass region/cost/path controls).
MAX_FILES_CAP = 60
MAX_PASS_AT_K = 5
# Model ids are pinned to region-agnostic profiles only — reject ``us.*``/``eu.*`` region prefixes
# that would route a Korean-FSI scan's source outside the container region.
_ALLOWED_CLAUDE_MODEL = re.compile(r"^(global\.)?anthropic\.claude-[\w.\-]+$")
_ALLOWED_OPENAI_MODEL = re.compile(r"^openai\.[\w.\-:]+$")
_ALLOWED_API_KIND = ("chat", "responses")


def _clamp(value, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def _safe_project_path(payload: Dict) -> str:
    """Honor a client ``project_path`` only when it resolves under an allowed root (the OS temp
    dir — where uploads/tests live — or the bundled sample-target). Any other path falls back to
    the sample-target, so a caller can never point the scanner at arbitrary container files (LFI)."""
    default = os.environ.get("SAMPLE_TARGET_DIR", "/app/sample-target")
    raw = payload.get("project_path")
    if not raw:
        return default
    p = os.path.abspath(str(raw))
    roots = [os.path.abspath(tempfile.gettempdir()), os.path.abspath(default)]
    if any(p == r or p.startswith(r + os.sep) for r in roots):
        return p
    log.warning("rejecting out-of-allowlist project_path; using sample-target")
    return default


def _build_config(payload: Dict, region: str, pinned: Optional[Dict] = None) -> ScanConfig:
    cfg = ScanConfig(project_path=_safe_project_path(payload))
    cfg.region = region  # trust container region, ignore any payload region
    if "max_files" in payload:
        cfg.max_files = _clamp(payload["max_files"], 1, MAX_FILES_CAP)
    if "pass_at_k" in payload:
        cfg.pass_at_k = _clamp(payload["pass_at_k"], 1, MAX_PASS_AT_K)
    # Model ids: accept only allowlisted region-agnostic profiles; anything else keeps the default.
    for key in ("hunter_model", "challenger_model", "validator_model", "ranker_model"):
        v = payload.get(key)
        if v and _ALLOWED_CLAUDE_MODEL.match(v):
            setattr(cfg, key, v)
    if payload.get("openai_model") and _ALLOWED_OPENAI_MODEL.match(payload["openai_model"]):
        cfg.openai_model = payload["openai_model"]
    if payload.get("openai_api_kind") in _ALLOWED_API_KIND:
        cfg.openai_api_kind = payload["openai_api_kind"]
    if "sandbox_enabled" in payload:
        cfg.sandbox_enabled = bool(payload["sandbox_enabled"])
    if "ensemble_enabled" in payload:
        # The cross-family ensemble re-judges via Bedrock mantle, whose default endpoint
        # (`openai_region`, us-east-2) is OUTSIDE the in-region boundary (ap-northeast-2).
        # Per the v2 design VETO (data sovereignty / 전자금융감독규정), cross-region egress of FSI
        # source is DEFAULT OFF and gated by deploy-time policy (env var, not a UI flag): ops must
        # explicitly set ENSEMBLE_ALLOWED=1 to permit it. This also keeps policy consistent with the
        # Claude path, which already rejects out-of-region (`us.*`/`eu.*`) model routing.
        ensemble_allowed = os.environ.get("ENSEMBLE_ALLOWED", "0") == "1"
        cfg.ensemble_enabled = bool(payload["ensemble_enabled"]) and ensemble_allowed
        if cfg.ensemble_enabled and cfg.openai_region != cfg.region:
            # Audit the boundary crossing — "log what left the boundary" (design spec).
            log.warning(
                "DATA-RESIDENCY: cross-family ensemble ENABLED — scan source egresses "
                "out-of-region to %s (container region %s) via ENSEMBLE_ALLOWED=1",
                cfg.openai_region, cfg.region,
            )
    if pinned:  # ADR-001: inline-pinned prompt set resolved at scan creation
        from agents.prompts import PromptSet

        cfg.prompts = PromptSet.from_resolved(
            {a: {"body": b} for a, b in pinned["bodies"].items()}
        )
        cfg.pinned_prompt_versions = dict(pinned["versions"])
        cfg.prompt_hashes = dict(pinned["hashes"])
    return cfg


def _resolve_pinned(deps: "Deps") -> Optional[Dict]:
    """Resolve + pin the active prompt set at scan creation (ADR-001). Returns the inline
    bundle ``{versions, hashes, bodies}`` or ``None`` when no store is wired (legacy). Raises
    ``PromptStoreUnavailable`` on an outage so the caller fails closed (never scans with
    silent defaults during a store outage)."""
    store = getattr(deps, "prompt_store", None)
    if store is None:
        return None
    resolved = store.resolve_active_set()  # may raise PromptStoreUnavailable
    return {
        "versions": {a: str(r["version"]) for a, r in resolved.items()},
        "hashes": {a: r["hash"] for a, r in resolved.items()},
        "bodies": {a: r["body"] for a, r in resolved.items()},
    }


def _verify_inline_prompts(mp: Dict) -> Dict:
    """Worker-side integrity check on the inline-pinned prompt bundle. Requires the COMPLETE set
    of agents (no partial bundle that would silently fall back to defaults) and that every body
    hashes to its pinned hash; otherwise abort (tamper / corruption in transit)."""
    from pipeline.prompts_store import AGENT_KEYS

    bodies = mp.get("bodies", {}) or {}
    hashes = mp.get("hashes", {}) or {}
    missing = [a for a in AGENT_KEYS if a not in bodies or a not in hashes]
    if missing:
        raise ValueError(f"incomplete pinned prompt bundle — missing {missing} (aborting scan)")
    for agent in AGENT_KEYS:
        if prompt_hash(bodies[agent]) != hashes.get(agent):
            raise ValueError(f"pinned prompt hash mismatch for {agent!r} — aborting scan (tamper/corruption)")
    return {"versions": mp.get("versions", {}) or {}, "hashes": hashes, "bodies": bodies}


def _make_openai_provider(cfg: ScanConfig, deps: "Deps"):
    """Build the cross-family OpenAI (Bedrock-mantle) provider when the ensemble is on.
    Injectable via deps for tests; otherwise constructed from config (SigV4/IAM, no key)."""
    if not cfg.ensemble_enabled:
        return None
    if getattr(deps, "openai_provider", None) is not None:
        return deps.openai_provider
    from agents.openai_mantle import OpenAIMantleProvider

    return OpenAIMantleProvider(
        model=cfg.openai_model, region=cfg.openai_region, api_kind=cfg.openai_api_kind
    )


def _run_scan(payload: Dict, user_id: str, deps: Deps, progress=None, heartbeat=None,
              pinned: Optional[Dict] = None) -> Dict:
    import shutil

    upload_dir = _materialize_upload(payload)
    cfg = _build_config(payload, deps.region, pinned=pinned)
    if upload_dir:
        cfg.project_path = upload_dir
    pipe = FSIMythosPipeline(
        cfg,
        converse=deps.converse,
        account_id=deps.account_id,
        fp_store=deps.fp_store,
        sandbox=deps.sandbox,
        user_id=user_id,
        progress=progress,
        heartbeat=heartbeat,
        openai_provider=_make_openai_provider(cfg, deps),
    )
    try:
        return pipe.run()
    finally:
        if upload_dir:
            shutil.rmtree(upload_dir, ignore_errors=True)  # avoid /tmp leak


def _groups_from_context(context) -> List[str]:
    """Extract ``cognito:groups`` from the authorizer-verified bearer (same path as
    ``_user_id``). The AgentCore JWT authorizer verifies signature/issuer/audience before the
    request reaches us; we only decode the claims. Backend is authoritative for RBAC."""
    headers = _headers_from_context(context)
    auth = ""
    for k, v in (headers or {}).items():
        if str(k).lower() == "authorization":
            auth = v or ""
            break
    groups = []
    if auth.lower().startswith("bearer "):
        groups = _decode_jwt_claims(auth[7:]).get("cognito:groups") or []
    if not groups:  # tolerate context.claims / dict shape (tests, older runtime)
        claims = getattr(context, "claims", None)
        if claims is None and isinstance(context, dict):
            claims = context.get("claims")
        groups = (claims or {}).get("cognito:groups") or []
    return groups if isinstance(groups, list) else [groups]


def _is_admin(context) -> bool:
    return PROMPT_ADMIN_GROUP in _groups_from_context(context)


def _render_preview(agent_key: str, body: str) -> str:
    """Render exactly what the model will see (no model call): the immutable safety preamble +
    edited body as system, plus a sample user prompt with scanned code wrapped in the
    nonce-fenced untrusted-data block — so the admin can confirm the injection scaffolding is
    intact before activating."""
    from agents.prompts import PromptSet, build_untrusted_block, _nonce

    system = PromptSet.assemble(body)
    nonce = _nonce()
    fence = build_untrusted_block("def example(req):\n    return req.body['x']\n", nonce)
    return f"=== SYSTEM ===\n{system}\n\n=== USER (scanned code is untrusted, nonce-fenced) ===\n{fence}"


def _prompt_route(action: str, payload: Dict, user_id: str, deps: Deps) -> Dict:
    """Admin-only prompt-store operations (ADR-001). Caller already passed ``_is_admin``.
    ``author``/``updatedBy`` come from the verified ``user_id`` (sub), never the payload."""
    store = getattr(deps, "prompt_store", None)
    if store is None:
        return {"status": "error", "error": "prompt store not configured"}
    agent = payload.get("agentKey")
    try:
        if action == "prompt_list":
            return {"status": "ok", "versions": store.list_versions(agent),
                    "active": store.get_active(agent), "audit": store.list_audit(agent)}
        if action == "prompt_get":
            return {"status": "ok", "version": store.get_version(agent, int(payload["version"]))}
        if action == "prompt_create":
            v = store.create_version(agent, payload.get("body", ""), author=user_id,
                                     note=payload.get("note", ""))
            return {"status": "ok", "version": v["version"], "hash": v["hash"]}
        if action == "prompt_preview":
            ver = store.get_version(agent, int(payload["version"]))
            if ver is None:
                return {"status": "error", "error": "version not found"}
            # re-validate (defense-in-depth) then stamp server-side validation state
            from pipeline.prompts_store import validate_prompt_body

            validate_prompt_body(agent, ver["body"], ver.get("note", ""))
            store.stamp_validated(agent, ver["version"], ver["hash"])
            return {"status": "ok", "validated": True, "rendered": _render_preview(agent, ver["body"])}
        if action == "prompt_activate":
            version = int(payload["version"])
            ver = store.get_version(agent, version)
            if ver is None:
                return {"status": "error", "error": "version not found"}
            if ver.get("validatedHash") != ver["hash"]:
                return {"status": "error", "error": "version must be previewed/validated before activation"}
            runner = getattr(deps, "benchmark_runner", None)
            if runner is not None and not runner(agent, ver["body"]):
                return {"status": "error", "error": "benchmark dry-run failed — activation blocked"}
            won = store.activate(agent, version, updated_by=user_id, expected_prev=store.get_active(agent))
            if not won:
                return {"status": "error", "error": "active pointer changed concurrently — retry"}
            return {"status": "ok", "active": version}
    except PromptValidationError as exc:
        return {"status": "error", "error": str(exc)}
    except (KeyError, ValueError, TypeError) as exc:
        return {"status": "error", "error": f"bad request: {exc}"}
    return {"status": "error", "error": f"unknown prompt action: {action}"}


def route(payload: Dict, context=None, deps: Optional[Deps] = None) -> Dict:
    deps = deps or Deps()
    payload = payload or {}
    # Require an explicit action — never default to "scan" (an empty/preflight body must not
    # accidentally launch a scan). All returns are raw JSON dicts (the AgentCore entrypoint
    # contract); CORS for the runtime data plane is handled at the service/CloudFront edge,
    # so `cors` here is advisory metadata, not an API-Gateway proxy response.
    action = payload.get("action")
    origin = deps.allowed_origin

    if action == "OPTIONS" or payload.get("httpMethod") == "OPTIONS":
        return {"action": "OPTIONS", "cors": _cors(origin)}

    if not action:
        return {"action": None, "status": "error", "error": "missing 'action'", "cors": _cors(origin)}

    user_id = _user_id(payload, context)
    log.info("route action=%s user=%s", action, user_id)

    if action == "list_history":
        items = deps.history.list_history(user_id, limit=int(payload.get("limit", 50)))
        now = _now_iso()
        items = [annotate_stale(it, now, _stale_after_sec()) for it in (items or [])]
        return {"cors": _cors(origin), "action": action, "items": items}

    if action == "get_scan":
        item = deps.history.get_scan(user_id, payload["scanId"])
        if item:
            item = annotate_stale(item, _now_iso(), _stale_after_sec())
        return {"cors": _cors(origin), "action": action, "scan": item}

    if action in _PROMPT_ACTIONS:
        if not _is_admin(context):
            log.warning("prompt admin denied action=%s user=%s", action, user_id)
            return {"cors": _cors(origin), "action": action, "status": "error",
                    "code": 403, "error": "admin role required"}
        return {"cors": _cors(origin), "action": action, **_prompt_route(action, payload, user_id, deps)}

    if action == "scan":
        scan_id = _new_scan_id()
        try:
            pinned = _resolve_pinned(deps)  # may fail-closed below
        except PromptStoreUnavailable as exc:
            log.exception("prompt store unavailable at scan creation")
            _persist(deps, user_id, scan_id, payload, status="error", result=None)
            return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "error",
                    "error": f"prompt store unavailable: {exc}"}
        try:
            result = _run_scan(payload, user_id, deps, pinned=pinned)
        except Exception as exc:  # noqa: BLE001 — surface the error instead of a 500
            log.exception("sync scan failed")
            _persist(deps, user_id, scan_id, payload, status="error", result=None)
            return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "error", "error": str(exc)}
        _persist(deps, user_id, scan_id, payload, status="done", result=result)
        if pinned:  # record what was pinned for reproducibility/audit
            _safe_update(deps, user_id, scan_id,
                         promptVersions=pinned["versions"], promptHashes=pinned["hashes"])
        return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "done", **result}

    if action == "scan_async":
        scan_id = _new_scan_id()
        try:
            pinned = _resolve_pinned(deps)
        except PromptStoreUnavailable as exc:
            log.exception("prompt store unavailable at async scan creation")
            return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "error",
                    "error": f"prompt store unavailable: {exc}"}
        # write IN_PROGRESS up front so the poller sees it immediately
        _persist(deps, user_id, scan_id, payload, status="IN_PROGRESS", result=None)
        if pinned:
            _safe_update(deps, user_id, scan_id,
                         promptVersions=pinned["versions"], promptHashes=pinned["hashes"])

        def _progress(phase: str, detail: str = "") -> None:
            _safe_update(deps, user_id, scan_id, currentPhase=phase, currentDetail=detail)

        def _heartbeat() -> None:
            # intra-phase liveness ping (bumps updatedAt via auto-stamp) so a long but healthy
            # Phase-3 scan is not flagged stale, and a frozen worker IS detectable.
            _safe_update(deps, user_id, scan_id)

        if deps.dispatch is not None:
            # Durable path: enqueue for the Fargate worker. The trusted user_id is carried in
            # the message (the worker must NOT re-derive identity). If enqueue fails, compensate
            # immediately so we never leave a bare IN_PROGRESS that can't be worked.
            try:
                worker_msg = {"action": "scan_worker", "scanId": scan_id,
                              "userId": user_id, "payload": payload}
                if pinned:  # carry the resolved bodies inline so the worker never reads PROMPT#
                    worker_msg["prompts"] = pinned
                    worker_msg["promptsPinned"] = True  # detect a stripped bundle at the worker
                deps.dispatch(worker_msg)
            except Exception as exc:  # noqa: BLE001
                log.exception("scan dispatch failed")
                _safe_update(deps, user_id, scan_id, status="error", error=f"dispatch_failed: {exc}")
                return {"cors": _cors(origin), "action": action, "scanId": scan_id,
                        "status": "error", "error": "dispatch_failed"}
        else:
            # Local/dev fallback: in-thread daemon (NOT durable on AgentCore — see _default_spawn).
            def _job() -> None:
                try:
                    result = _run_scan(payload, user_id, deps, progress=_progress,
                                       heartbeat=_heartbeat, pinned=pinned)
                    _persist(deps, user_id, scan_id, payload, status="done", result=result, update=True)
                except Exception as exc:  # noqa: BLE001 — record failure, never crash the worker
                    _safe_update(deps, user_id, scan_id, status="error", error=str(exc))

            deps.spawn(_job)
        return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "IN_PROGRESS"}

    return {"action": action, "status": "error", "error": f"unknown action: {action}", "cors": _cors(origin)}


def scan_worker(message: Dict, deps: Deps) -> Dict:
    """Consumer-only entrypoint for the durable SQS worker (Fargate). NOT a public ``route``
    action — identity comes solely from the trusted enqueued ``userId``, never a caller claim.

    Idempotent for SQS at-least-once delivery: skip if the record is already terminal, and
    claim a lease so a duplicate/redelivered message can't double-run. Runs ``_run_scan`` in
    this (long-running) process with a heartbeat, then persists done/error."""
    scan_id = message.get("scanId")
    user_id = message.get("userId")
    payload = message.get("payload", {})
    if not scan_id or not user_id:
        # Malformed/poison message — never default identity (would target the wrong partition).
        log.error("scan_worker rejecting malformed message: %s", {k: message.get(k) for k in ("scanId", "userId")})
        return {"status": "error", "error": "malformed worker message (missing scanId/userId)"}

    # Rebuild + integrity-check the inline-pinned prompts (ADR-001 T8b): the worker uses the
    # bodies pinned at scan creation, never the live active pointer, and aborts on a hash
    # mismatch (tamper/corruption) rather than silently substituting defaults.
    pinned = None
    if message.get("prompts"):
        try:
            pinned = _verify_inline_prompts(message["prompts"])
        except ValueError as exc:
            log.error("scan_worker aborting on prompt integrity failure: %s", exc)
            _safe_update(deps, user_id, scan_id, status="error", error=str(exc))
            return {"scanId": scan_id, "status": "error", "error": str(exc)}
    elif message.get("promptsPinned") or getattr(deps, "require_pinned_prompts", False):
        # Either the producer flagged a pinned bundle that is now absent (stripped/tampered), or
        # this deployment requires pinned prompts and the bundle is missing entirely. Fail closed
        # rather than silently running on code defaults.
        err = "pinned prompt bundle missing from worker message — aborting scan (tamper/corruption)"
        log.error("scan_worker %s: %s", scan_id, err)
        _safe_update(deps, user_id, scan_id, status="error", error=err)
        return {"scanId": scan_id, "status": "error", "error": err}

    existing = deps.history.get_scan(user_id, scan_id) if deps.history else None
    if existing and existing.get("status") in ("done", "error"):
        return {"scanId": scan_id, "status": existing["status"], "skipped": "already terminal"}

    # Lease claim: only one worker may proceed (conditional; best-effort if store lacks claim).
    token = uuid.uuid4().hex
    claim = getattr(deps.history, "try_claim", None)
    if claim is not None and not claim(user_id, scan_id, token, _now_iso()):
        return {"scanId": scan_id, "status": "IN_PROGRESS", "skipped": "lease held by another worker"}

    def _progress(phase: str, detail: str = "") -> None:
        _safe_update(deps, user_id, scan_id, currentPhase=phase, currentDetail=detail)

    def _heartbeat() -> None:
        _safe_update(deps, user_id, scan_id)

    try:
        result = _run_scan(payload, user_id, deps, progress=_progress, heartbeat=_heartbeat, pinned=pinned)
        _persist(deps, user_id, scan_id, payload, status="done", result=result, update=True)
        return {"scanId": scan_id, "status": "done"}
    except Exception as exc:  # noqa: BLE001
        # Terminal: record error and return normally so SQS deletes the message — we do NOT
        # re-raise to retry. Retrying the same message can't recover anyway (its lease is held
        # until expiry), and would burn LLM spend on poison pills. Crash recovery instead comes
        # from the *expiring* lease: a later delivery reclaims the lease once it goes stale.
        log.exception("scan_worker failed for %s", scan_id)
        _safe_update(deps, user_id, scan_id, status="error", error=str(exc))
        return {"scanId": scan_id, "status": "error", "error": str(exc)}


def _persist(deps: Deps, user_id, scan_id, payload, status, result, update=False) -> None:
    """Persist a scan record. Isolated: a DynamoDB failure never sinks the response."""
    if deps.history is None:
        return
    summary = (result or {}).get("summary")
    report = (result or {}).get("report")
    gate = (result or {}).get("gate")
    try:
        if update:
            deps.history.update_status(
                user_id, scan_id, status=status, summary=summary, report=report, gate=gate
            )
        else:
            deps.history.save_scan(
                user_id,
                scan_id,
                created_at=scan_id.split("#", 1)[0],
                project_path=payload.get("project_path", "(업로드)"),
                max_files=int(payload.get("max_files", 8)),
                pass_at_k=int(payload.get("pass_at_k", 1)),
                status=status,
                summary=summary,
                report=report,
                gate=gate,
            )
    except Exception:
        # Persistence is best-effort (must never crash a scan), but a swallowed failure here is
        # how scans "vanish" — log it so the cause is observable.
        log.exception("persist failed for scan %s", scan_id)


def _safe_update(deps: Deps, user_id, scan_id, **fields) -> None:
    if deps.history is None:
        return
    try:
        deps.history.update_status(user_id, scan_id, **fields)
    except Exception:
        log.exception("status update failed for scan %s", scan_id)


# --- AgentCore SDK wiring (kept importable without the SDK installed) -----------------
try:  # pragma: no cover - exercised only inside the container
    from bedrock_agentcore import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def handler(payload, context=None):
        region = os.environ.get("AWS_REGION", "us-west-2")
        import boto3

        # Durable async: if a worker queue is configured, enqueue scans to SQS for the Fargate
        # worker. Without it, scan_async falls back to the in-thread daemon (NOT durable on the
        # runtime) — so a deployment that relies on async MUST set SCAN_WORKER_QUEUE_URL.
        queue_url = os.environ.get("SCAN_WORKER_QUEUE_URL")
        dispatch = SqsDispatchSpawn(queue_url, region=region) if queue_url else None
        if not queue_url:
            log.warning("SCAN_WORKER_QUEUE_URL unset — async scans use the non-durable in-thread path")

        deps = Deps(
            converse=BedrockConverse(region=region),
            history=_default_history(region),
            prompt_store=_default_prompt_store(region),
            require_pinned_prompts=os.environ.get("PROMPT_STORE_REQUIRED") == "1",
            account_id=_account_id(),
            region=region,
            dispatch=dispatch,
        )
        return route(payload, context, deps)

    def _default_history(region):
        from tools.history import ScanHistory

        return ScanHistory(os.environ.get("HISTORY_TABLE", "SCAN_HISTORY"), region=region)

    def _default_prompt_store(region):
        from pipeline.prompts_store import PromptStore

        return PromptStore(os.environ.get("HISTORY_TABLE", "SCAN_HISTORY"), region=region)

    def _account_id():
        try:
            import boto3

            return boto3.client("sts").get_caller_identity()["Account"]
        except Exception:
            return "000000000000"

    if __name__ == "__main__":
        app.run()
except ImportError:  # SDK absent (unit-test / local) — route() is still usable
    app = None
