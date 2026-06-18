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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fsi.app")

CORS_HEADERS = {
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_scan_id() -> str:
    return f"{_now_iso()}#{uuid.uuid4().hex[:8]}"


def _cors(origin: str) -> Dict:
    return {"Access-Control-Allow-Origin": origin or "*", **CORS_HEADERS}


def _default_spawn(fn: Callable[[], None]) -> None:
    """Run an async job in a background thread.

    This is valid on AgentCore Runtime, whose container persists for the session lifetime
    (unlike AWS Lambda, which freezes after the response — there a daemon thread would die).
    ``Deps.spawn`` is injectable so a deployment that needs a durable trigger can swap in an
    SQS/EventBridge/async-invoke dispatcher without touching ``route``.
    """
    threading.Thread(target=fn, daemon=True).start()


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


def _run_scan(payload: Dict, user_id: str, deps: Deps, progress=None) -> Dict:
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
        return {"cors": _cors(origin), "action": action, "items": items}

    if action == "get_scan":
        item = deps.history.get_scan(user_id, payload["scanId"])
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

        def _progress(phase: str) -> None:
            _safe_update(deps, user_id, scan_id, currentPhase=phase)

        def _job() -> None:
            try:
                result = _run_scan(payload, user_id, deps, progress=_progress)
                _persist(deps, user_id, scan_id, payload, status="done", result=result, update=True)
            except Exception as exc:  # noqa: BLE001 — record failure, never crash the worker
                _safe_update(deps, user_id, scan_id, status="error", error=str(exc))

        deps.spawn(_job)
        return {"cors": _cors(origin), "action": action, "scanId": scan_id, "status": "IN_PROGRESS"}

    return {"action": action, "status": "error", "error": f"unknown action: {action}", "cors": _cors(origin)}


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

        deps = Deps(
            converse=BedrockConverse(region=region),
            history=_default_history(region),
            account_id=_account_id(),
            region=region,
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
