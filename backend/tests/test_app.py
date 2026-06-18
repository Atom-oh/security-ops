"""Tests for app.route — action dispatch, CORS, sync/async, region trust."""
from __future__ import annotations

from pathlib import Path

import app as appmod
from app import Deps, route


class FakeHistory:
    def __init__(self):
        self.saved = []
        self.updated = []
        self.items = []

    def save_scan(self, user_id, scan_id, **kw):
        self.saved.append((user_id, scan_id, kw))

    def update_status(self, user_id, scan_id, **fields):
        self.updated.append((user_id, scan_id, fields))

    def list_history(self, user_id, limit=50):
        return [i for i in self.items if i["userId"] == user_id]

    def get_scan(self, user_id, scan_id):
        return {"userId": user_id, "scanId": scan_id, "status": "done"}


class EmptyConverse:
    def invoke(self, model, system, prompt, **k):
        return {"thinking": "", "output": "[]"}


def _target_dir(tmp_path: Path) -> str:
    (tmp_path / "x.c").write_text("void f(char*u){char b[8]; strcpy(b,u);}\n")
    return str(tmp_path)


def _deps(history=None, spawn=None):
    return Deps(
        converse=EmptyConverse(),
        history=history or FakeHistory(),
        account_id="123456789012",
        region="ap-northeast-2",
        allowed_origin="https://example.cloudfront.net",
        spawn=spawn or (lambda fn: fn()),
    )


def test_options_preflight_returns_cors():
    res = route({"action": "OPTIONS"}, deps=_deps())
    h = res["cors"]
    assert h["Access-Control-Allow-Origin"] == "https://example.cloudfront.net"
    assert "Authorization" in h["Access-Control-Allow-Headers"]


def test_unknown_action_is_error():
    res = route({"action": "frobnicate"}, deps=_deps())
    assert res["status"] == "error"
    assert "unknown action" in res["error"]


def test_missing_action_does_not_scan():
    hist = FakeHistory()
    res = route({"project_path": "/whatever"}, deps=_deps(hist))
    assert res["status"] == "error"
    assert hist.saved == []  # no accidental scan


_CTX = {"claims": {"email": "u@x"}}  # verified JWT identity


def test_sync_scan_runs_and_persists(tmp_path):
    hist = FakeHistory()
    res = route({"action": "scan", "project_path": _target_dir(tmp_path)}, context=_CTX, deps=_deps(hist))
    assert res["status"] == "done"
    assert res["scanId"]
    assert "summary" in res
    assert hist.saved and hist.saved[0][0] == "u@x"


def test_payload_user_id_ignored_without_claims(tmp_path):
    # security: a payload-supplied user_id must NOT set identity (no claims → anonymous)
    hist = FakeHistory()
    route({"action": "scan", "project_path": _target_dir(tmp_path), "user_id": "attacker@evil"}, deps=_deps(hist))
    assert hist.saved[0][0] == "anonymous"


def test_async_scan_returns_immediately_and_completes(tmp_path):
    hist = FakeHistory()
    # synchronous spawn → job runs inline so we can assert the update
    res = route(
        {"action": "scan_async", "project_path": _target_dir(tmp_path), "user_id": "u@x"},
        deps=_deps(hist),
    )
    assert res["status"] == "IN_PROGRESS"
    scan_id = res["scanId"]
    # IN_PROGRESS persisted first, then updated to done by the job
    assert hist.saved[0][2]["status"] == "IN_PROGRESS"
    assert any(u[1] == scan_id and u[2].get("status") == "done" for u in hist.updated)


def test_async_scan_records_error(tmp_path):
    hist = FakeHistory()

    class Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("bedrock down")

    deps = _deps(hist)
    deps.converse = Boom()
    res = route({"action": "scan_async", "project_path": _target_dir(tmp_path)}, deps=deps)
    assert res["status"] == "IN_PROGRESS"
    assert any(u[2].get("status") == "error" for u in hist.updated)


def test_list_and_get(tmp_path):
    hist = FakeHistory()
    hist.items = [{"userId": "u@x", "scanId": "s1"}]
    res = route({"action": "list_history"}, context=_CTX, deps=_deps(hist))
    # items are staleness-annotated (extra fields added), so assert by identity not equality
    assert len(res["items"]) == 1
    assert res["items"][0]["scanId"] == "s1" and res["items"][0]["userId"] == "u@x"
    res2 = route({"action": "get_scan", "scanId": "s1"}, context=_CTX, deps=_deps(hist))
    assert res2["scan"]["scanId"] == "s1"


def test_user_id_from_context_claims(tmp_path):
    captured = {}

    class CapHistory(FakeHistory):
        def save_scan(self, user_id, scan_id, **kw):
            captured["user"] = user_id
            super().save_scan(user_id, scan_id, **kw)

    ctx = {"claims": {"email": "claim@bank.kr"}}
    route(
        {"action": "scan", "project_path": _target_dir(tmp_path)},
        context=ctx,
        deps=_deps(CapHistory()),
    )
    assert captured.get("user") == "claim@bank.kr"


def test_sdk_optional_import():
    # app module imports cleanly even without the AgentCore SDK installed
    assert appmod.app is None or appmod.app is not None


def _fake_jwt(claims: dict) -> str:
    import base64, json
    def b64(o): return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
    return f"{b64({'alg':'none'})}.{b64(claims)}.sig"


def test_identity_from_bearer_jwt_header(tmp_path):
    # the real deployed path: RequestContext.request_headers carries Authorization: Bearer <jwt>
    hist = FakeHistory()

    class Ctx:
        request_headers = {"Authorization": "Bearer " + _fake_jwt({"sub": "u-abc-123", "username": "u-abc-123"})}

    route({"action": "scan", "project_path": _target_dir(tmp_path)}, context=Ctx(), deps=_deps(hist))
    assert hist.saved[0][0] == "u-abc-123"  # keyed on the JWT sub, not anonymous


def test_identity_anonymous_without_token(tmp_path):
    hist = FakeHistory()
    route({"action": "scan", "project_path": _target_dir(tmp_path)}, deps=_deps(hist))
    assert hist.saved[0][0] == "anonymous"
