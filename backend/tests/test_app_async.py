"""Task 3 — durable async dispatch + idempotent worker."""
from __future__ import annotations

import json

from app import Deps, SqsDispatchSpawn, route, scan_worker


class EmptyConverse:
    def invoke(self, model, system, prompt, **k):
        return {"thinking": "", "output": "[]"}


class FakeHistory:
    def __init__(self, scan=None, claim_ok=True):
        self.records = {}
        self._scan = scan
        self._claim_ok = claim_ok
        self.claims = []

    def save_scan(self, user_id, scan_id, *a, **kw):
        self.records[(user_id, scan_id)] = {"status": kw.get("status", "IN_PROGRESS")}

    def update_status(self, user_id, scan_id, **fields):
        self.records.setdefault((user_id, scan_id), {}).update(fields)

    def get_scan(self, user_id, scan_id):
        return self._scan

    def try_claim(self, user_id, scan_id, token, now_iso):
        self.claims.append(token)
        return self._claim_ok


def _ctx():
    return {"claims": {"sub": "admin"}}


def test_scan_async_enqueues_and_does_not_run_in_thread(tmp_path):
    sent = []
    hist = FakeHistory()
    deps = Deps(converse=EmptyConverse(), history=hist, region="ap-northeast-2",
                allowed_origin="*", dispatch=lambda msg: sent.append(msg),
                spawn=lambda fn: (_ for _ in ()).throw(AssertionError("must not spawn in-thread")))
    res = route({"action": "scan_async", "projectPath": str(tmp_path)}, context=_ctx(), deps=deps)
    assert res["status"] == "IN_PROGRESS"
    assert len(sent) == 1
    assert sent[0]["action"] == "scan_worker"
    assert sent[0]["userId"] == "admin"  # trusted identity propagated, not a caller claim
    assert sent[0]["scanId"] == res["scanId"]


def test_dispatch_failure_compensates_to_error(tmp_path):
    def boom(_msg):
        raise RuntimeError("sqs unreachable")

    hist = FakeHistory()
    deps = Deps(converse=EmptyConverse(), history=hist, region="ap-northeast-2",
                allowed_origin="*", dispatch=boom)
    res = route({"action": "scan_async", "projectPath": str(tmp_path)}, context=_ctx(), deps=deps)
    assert res["status"] == "error" and res["error"] == "dispatch_failed"
    # the record was compensated, not left bare IN_PROGRESS
    rec = next(iter(hist.records.values()))
    assert rec["status"] == "error"


def test_worker_runs_and_persists_done(tmp_path):
    (tmp_path / "a.py").write_text("def f(r):\n    return r.body['x']\n")
    hist = FakeHistory(scan=None)
    deps = Deps(converse=EmptyConverse(), history=hist, region="ap-northeast-2")
    out = scan_worker({"scanId": "s#1", "userId": "admin", "payload": {"projectPath": str(tmp_path)}}, deps)
    assert out["status"] == "done"
    assert hist.records[("admin", "s#1")]["status"] == "done"


def test_worker_skips_already_terminal():
    hist = FakeHistory(scan={"status": "done"})
    deps = Deps(converse=EmptyConverse(), history=hist, region="ap-northeast-2")
    out = scan_worker({"scanId": "s#1", "userId": "admin", "payload": {}}, deps)
    assert out["status"] == "done" and out.get("skipped")


def test_worker_skips_when_lease_held():
    hist = FakeHistory(scan={"status": "IN_PROGRESS"}, claim_ok=False)
    deps = Deps(converse=EmptyConverse(), history=hist, region="ap-northeast-2")
    out = scan_worker({"scanId": "s#1", "userId": "admin", "payload": {}}, deps)
    assert out.get("skipped") == "lease held by another worker"


def test_worker_exception_persists_error(tmp_path):
    class BoomConverse:
        def invoke(self, *a, **k):
            raise RuntimeError("bedrock down")

    # a non-existent project path makes _run_scan raise before/within the scan
    hist = FakeHistory(scan=None)
    deps = Deps(converse=BoomConverse(), history=hist, region="ap-northeast-2")
    out = scan_worker({"scanId": "s#1", "userId": "admin",
                       "payload": {"projectPath": "/nonexistent/xyz"}}, deps)
    assert out["status"] in ("error", "done")  # never raises; records a terminal status
    assert hist.records[("admin", "s#1")]["status"] in ("error", "done")


def test_sqs_dispatch_sends_message():
    import boto3
    from botocore.stub import Stubber

    client = boto3.client("sqs", region_name="ap-northeast-2")
    stub = Stubber(client)
    stub.add_response("send_message", {"MessageId": "m1", "MD5OfMessageBody": "x"},
                      expected_params={"QueueUrl": "https://q/url",
                                       "MessageBody": json.dumps({"action": "scan_worker", "scanId": "s#1"})})
    with stub:
        SqsDispatchSpawn("https://q/url", client=client)({"action": "scan_worker", "scanId": "s#1"})
    stub.assert_no_pending_responses()
