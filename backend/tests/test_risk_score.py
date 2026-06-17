"""Tests for pipeline.risk_score — deterministic file risk triage."""
from __future__ import annotations

from pipeline.config import Language
from pipeline.risk_score import rank_by_risk, score_file


def test_auth_payment_outrank_inert_util():
    auth, _ = score_file("src/auth/login.py", Language.PYTHON, sink_count=1,
                         content="def verify(request): token = request.headers['Authorization']")
    util, _ = score_file("src/util/math.py", Language.PYTHON, sink_count=0,
                         content="def add(a, b):\n    return a + b")
    assert auth > util


def test_excluded_paths_score_low():
    score, reasons = score_file("vendor/lib/helper.js", Language.JAVASCRIPT, sink_count=0,
                                content="export const x = 1;")
    assert score <= 1.0
    assert any("exclu" in r.lower() for r in reasons)


def test_anti_gaming_sink_dense_test_named_file_still_ranks():
    # malicious file stuffs 'test' in the name but is sink-dense + auth-related
    gamed, _ = score_file("payment_test_helper.c", Language.C, sink_count=8,
                          content="strcpy(buf, account); system(transfer_cmd);")
    inert, _ = score_file("util/strings.go", Language.GO, sink_count=0, content="package u")
    assert gamed > inert, "exclusion keyword must not hide a sink-dense risky file"


def test_language_weight_c_high():
    c, _ = score_file("a.c", Language.C, sink_count=2, content="strcpy(x,y);")
    py, _ = score_file("a.py", Language.PYTHON, sink_count=2, content="x=1")
    assert c > py


def test_rank_by_risk_orders_and_caps():
    scores = {
        "auth.py": (10.0, ["auth"]),
        "pay.go": (8.0, ["payment"]),
        "util.py": (1.0, []),
        "misc.js": (0.5, []),
    }
    ranked = rank_by_risk(scores, max_files=2)
    assert [r["file"] for r in ranked] == ["auth.py", "pay.go"]
    assert ranked[0]["rank"] == 1 and "reasons" in ranked[0]
