"""Tests for tools.history against a mocked DynamoDB (moto)."""
from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from tools.history import ScanHistory

TABLE = "SCAN_HISTORY"
REGION = "ap-northeast-2"


@pytest.fixture
def history():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "userId", "KeyType": "HASH"},
                {"AttributeName": "scanId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "userId", "AttributeType": "S"},
                {"AttributeName": "scanId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ScanHistory(TABLE, resource=ddb)


def test_save_get_roundtrip(history):
    history.save_scan(
        "u@x", "2026-06-17T00:00:00Z#abcd1234", "2026-06-17T00:00:00Z",
        "/app/sample-target", 8, 1,
        summary={"critical": 3, "confidence": 0.97},
        report={"findings": [{"title": "x"}]},
        gate={"status": "BLOCKED"},
    )
    got = history.get_scan("u@x", "2026-06-17T00:00:00Z#abcd1234")
    assert got["summary"]["critical"] == 3
    assert got["report"]["findings"][0]["title"] == "x"
    assert got["gate"]["status"] == "BLOCKED"
    assert got["maxFiles"] == 8


def test_list_is_newest_first_and_isolated(history):
    history.save_scan("u@x", "2026-06-01T00:00:00Z#aaaa1111", "2026-06-01T00:00:00Z", "/p", 8, 1)
    history.save_scan("u@x", "2026-06-17T00:00:00Z#bbbb2222", "2026-06-17T00:00:00Z", "/p", 8, 1)
    history.save_scan("other@x", "2026-06-10T00:00:00Z#cccc3333", "2026-06-10T00:00:00Z", "/p", 8, 1)
    items = history.list_history("u@x")
    assert len(items) == 2  # other user's scan excluded
    assert items[0]["scanId"].startswith("2026-06-17")  # newest first


def test_update_status(history):
    history.save_scan("u@x", "s1", "2026-06-17T00:00:00Z", "/p", 8, 1, status="IN_PROGRESS")
    history.update_status("u@x", "s1", status="done", summary={"critical": 1})
    got = history.get_scan("u@x", "s1")
    assert got["status"] == "done"
    assert got["summary"]["critical"] == 1


def test_update_status_autostamps_updated_at(history):
    # Liveness: every update stamps updatedAt so staleness can be detected (Task 1).
    history.save_scan("u@x", "s2", "2026-06-17T00:00:00Z", "/p", 8, 1, status="IN_PROGRESS")
    history.update_status("u@x", "s2", currentPhase="Phase 3 · 에이전틱 헌트")
    got = history.get_scan("u@x", "s2")
    assert got.get("updatedAt"), "update_status must stamp updatedAt"
    assert got["currentPhase"].startswith("Phase 3")


def test_update_status_keeps_caller_updated_at(history):
    history.save_scan("u@x", "s3", "2026-06-17T00:00:00Z", "/p", 8, 1, status="IN_PROGRESS")
    history.update_status("u@x", "s3", updatedAt="2099-01-01T00:00:00Z")
    assert history.get_scan("u@x", "s3")["updatedAt"] == "2099-01-01T00:00:00Z"


def test_get_missing_returns_none(history):
    assert history.get_scan("u@x", "nope") is None
