"""Tests for Phase 2 — file ranking."""
from __future__ import annotations

from pipeline.config import ScanConfig
from pipeline.phase2_ranker import rank_files


class FakeConverse:
    def __init__(self, output):
        self._output = output

    def invoke(self, *a, **k):
        return {"thinking": "", "output": self._output}


def test_rank_uses_llm_output_and_caps():
    cfg = ScanConfig(project_path="/x", max_files=2)
    counts = {"a.c": 5, "b.py": 1, "auth.py": 3}
    fc = FakeConverse(
        '[{"file":"auth.py","rank":1,"reason":"auth"},'
        '{"file":"a.c","rank":2,"reason":"buffer"},'
        '{"file":"b.py","rank":3,"reason":"low"}]'
    )
    ranked = rank_files(counts, cfg, converse=fc)
    assert len(ranked) == 2  # capped at max_files
    assert ranked[0]["file"] == "auth.py"


def test_fallback_to_sink_density_when_no_converse():
    cfg = ScanConfig(project_path="/x", max_files=2)
    counts = {"a.c": 5, "b.py": 1, "auth.py": 3}
    ranked = rank_files(counts, cfg, converse=None)
    assert [r["file"] for r in ranked] == ["a.c", "auth.py"]
    assert ranked[0]["rank"] == 1


def test_fallback_when_llm_raises():
    cfg = ScanConfig(project_path="/x", max_files=3)

    class Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("bedrock down")

    counts = {"a.c": 1, "b.c": 9}
    ranked = rank_files(counts, cfg, converse=Boom())
    assert ranked[0]["file"] == "b.c"


def test_empty_counts_returns_empty():
    cfg = ScanConfig(project_path="/x")
    assert rank_files({}, cfg, converse=None) == []
