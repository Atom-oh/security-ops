"""AgentCore Runtime entrypoint for FSI-Mythos.

The browser calls the Runtime ``/invocations`` endpoint directly with a Cognito access
token, so this handler must (1) answer CORS preflight, (2) avoid the synchronous timeout on
long 8-phase scans via an async dispatch path, and (3) isolate persistence failures.

The HTTP/SDK glue is thin: ``route(payload, context, deps)`` is pure and unit-tested; the
``BedrockAgentCoreApp`` entrypoint just builds ``Deps`` from the environment and delegates.
"""
from __future__ import annotations

import base64
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
from tools.staleness import DEFAULT_STALE_AFTER_SEC, annotate_stale

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
        identity = claims.get("sub") or claims.get("username") or claims.get("client_id")
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


def _materialize_upload(payload: Dict) -> Optional[str]:
    """If the payload carries uploaded files, write them to a temp dir and return it.

    Hardened against path traversal ("zip slip"): each resolved destination must stay inside
    the temp root, else the entry is skipped.
    """
    upload = payload.get("upload")
    if not upload or not upload.get("files"):
        return None
    root = tempfile.mkdtemp(prefix="fsi-upload-")
    root_abs = os.path.abspath(root)
    for f in upload["files"]:
        rel = f.get("path", "").lstrip("/")
        if not rel:
            continue
        dest = os.path.abspath(os.path.join(root, rel))
        if dest != root_abs and not dest.startswith(root_abs + os.sep):
            continue  # path traversal attempt — skip
        os.makedirs(os.path.dirname(dest) or root, exist_ok=True)
        data = f.get("content_b64")
        with open(dest, "wb") as fh:
            fh.write(base64.b64decode(data) if data else (f.get("content", "").encode()))
    return root


def _build_config(payload: Dict, region: str) -> ScanConfig:
    cfg = ScanConfig(project_path=payload.get("project_path", "/app/sample-target"))
    cfg.region = region  # trust container region, ignore any payload region
    for key in ("max_files", "pass_at_k"):
        if key in payload:
            setattr(cfg, key, int(payload[key]))
    for key in ("hunter_model", "challenger_model", "validator_model", "ranker_model",
                "openai_model", "openai_api_kind"):
        if payload.get(key):
            setattr(cfg, key, payload[key])
    if "sandbox_enabled" in payload:
        cfg.sandbox_enabled = bool(payload["sandbox_enabled"])
    if "ensemble_enabled" in payload:
        cfg.ensemble_enabled = bool(payload["ensemble_enabled"])
    return cfg


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


def _run_scan(payload: Dict, user_id: str, deps: Deps, progress=None, heartbeat=None) -> Dict:
    import shutil

    upload_dir = _materialize_upload(payload)
    cfg = _build_config(payload, deps.region)
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

    if action == "scan":
        scan_id = _new_scan_id()
        try:
            result = _run_scan(payload, user_id, deps)
        except Exception as exc:  # noqa: BLE001 — surface the error instead of a 500
            log.exception("sync scan failed")
            _persist(deps, user_id, scan_id, payload, status="error", result=None)
            return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "error", "error": str(exc)}
        _persist(deps, user_id, scan_id, payload, status="done", result=result)
        return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "done", **result}

    if action == "scan_async":
        scan_id = _new_scan_id()
        # write IN_PROGRESS up front so the poller sees it immediately
        _persist(deps, user_id, scan_id, payload, status="IN_PROGRESS", result=None)

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
                deps.dispatch({"action": "scan_worker", "scanId": scan_id,
                               "userId": user_id, "payload": payload})
            except Exception as exc:  # noqa: BLE001
                log.exception("scan dispatch failed")
                _safe_update(deps, user_id, scan_id, status="error", error=f"dispatch_failed: {exc}")
                return {"cors": _cors(origin), "action": action, "scanId": scan_id,
                        "status": "error", "error": "dispatch_failed"}
        else:
            # Local/dev fallback: in-thread daemon (NOT durable on AgentCore — see _default_spawn).
            def _job() -> None:
                try:
                    result = _run_scan(payload, user_id, deps, progress=_progress, heartbeat=_heartbeat)
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
        result = _run_scan(payload, user_id, deps, progress=_progress, heartbeat=_heartbeat)
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
        pass


def _safe_update(deps: Deps, user_id, scan_id, **fields) -> None:
    if deps.history is None:
        return
    try:
        deps.history.update_status(user_id, scan_id, **fields)
    except Exception:
        pass


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
            account_id=_account_id(),
            region=region,
            dispatch=dispatch,
        )
        return route(payload, context, deps)

    def _default_history(region):
        from tools.history import ScanHistory

        return ScanHistory(os.environ.get("HISTORY_TABLE", "SCAN_HISTORY"), region=region)

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
