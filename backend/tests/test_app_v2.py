"""v2.1: the scan response carries the coverage block."""
from __future__ import annotations

from pathlib import Path

from app import Deps, route


class EmptyConverse:
    def invoke(self, model, system, prompt, **k):
        return {"thinking": "", "output": "[]"}


class FakeHistory:
    def __init__(self):
        self.saved = []

    def save_scan(self, user_id, scan_id, **kw):
        self.saved.append(kw)

    def update_status(self, *a, **k):
        pass


def test_sync_scan_response_has_coverage(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "b.py").write_text("def g():\n    return 2\n")
    hist = FakeHistory()
    deps = Deps(converse=EmptyConverse(), history=hist, region="ap-northeast-2",
                allowed_origin="*", spawn=lambda fn: fn())
    res = route({"action": "scan", "project_path": str(tmp_path)},
                context={"claims": {"sub": "u1"}}, deps=deps)
    assert res["status"] == "done"
    assert "coverage" in res
    assert res["coverage"]["total_code_files"] == 2
    # persisted via summary.coverage
    assert hist.saved[0]["summary"]["coverage"]["total_code_files"] == 2


def test_model_selection_from_payload(tmp_path):
    # UI-selected per-role + ensemble models flow into ScanConfig
    from app import _build_config
    cfg = _build_config({
        "hunter_model": "global.anthropic.claude-opus-4-8",
        "validator_model": "global.anthropic.claude-opus-4-7",
        "openai_model": "openai.gpt-oss-120b",
        "openai_api_kind": "chat",
    }, region="ap-northeast-2")
    assert cfg.hunter_model == "global.anthropic.claude-opus-4-8"
    assert cfg.validator_model == "global.anthropic.claude-opus-4-7"
    assert cfg.openai_model == "openai.gpt-oss-120b"
    assert cfg.openai_api_kind == "chat"
