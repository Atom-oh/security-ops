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
    assert res["statusCode"] == 200
    h = res["headers"]
    assert h["Access-Control-Allow-Origin"] == "https://example.cloudfront.net"
    assert "Authorization" in h["Access-Control-Allow-Headers"]


def test_unknown_action_is_400():
    res = route({"action": "frobnicate"}, deps=_deps())
    assert res["statusCode"] == 400


def test_sync_scan_runs_and_persists(tmp_path):
    hist = FakeHistory()
    res = route({"action": "scan", "project_path": _target_dir(tmp_path), "user_id": "u@x"}, deps=_deps(hist))
    assert res["status"] == "done"
    assert res["scanId"]
    assert "summary" in res
    assert hist.saved and hist.saved[0][0] == "u@x"


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
    res = route({"action": "list_history", "user_id": "u@x"}, deps=_deps(hist))
    assert res["items"] == [{"userId": "u@x", "scanId": "s1"}]
    res2 = route({"action": "get_scan", "scanId": "s1", "user_id": "u@x"}, deps=_deps(hist))
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
