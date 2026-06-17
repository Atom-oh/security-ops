"""v2.1 orchestrator: risk triage drives selection, coverage report, secret prefilter."""
from __future__ import annotations

from pipeline.config import ScanConfig
from pipeline.orchestrator import FSIMythosPipeline


class EmptyConverse:
    """Hunter/challenger/validator all return empty → findings come only from the prefilter."""

    def invoke(self, model, system, prompt, **k):
        return {"thinking": "", "output": "[]"}


def _repo(tmp_path):
    (tmp_path / "util").mkdir()
    (tmp_path / "util" / "math.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "util" / "strings.py").write_text("def up(s):\n    return s.upper()\n")
    pay = tmp_path / "payment"
    pay.mkdir()
    pay.write_text  # noop
    (pay / "transfer.py").write_text(
        "def transfer(request):\n"
        "    account = request.body['account']\n"
        "    password = \"S3cretKeyValue!longEnough\"\n"
    )
    return str(tmp_path)


def test_risk_triage_selects_riskiest_and_reports_coverage(tmp_path):
    root = _repo(tmp_path)
    cfg = ScanConfig(project_path=root, max_files=1, pass_at_k=1)
    res = FSIMythosPipeline(cfg, converse=EmptyConverse()).run()

    cov = res["coverage"]
    assert cov["total_code_files"] == 3
    assert cov["scanned_files"] == 1
    assert cov["unscanned_files"] == 2
    # the payment/transfer file (risky name + sensitive terms + taint) must be the one scanned;
    # its hardcoded password is caught deterministically by the Phase 2.5 prefilter.
    titles = [f["title"] for f in res["report"]["findings"]]
    assert any("시크릿" in t or "CWE-798" in str(f.get("cwe_id")) for t, f in
               zip(titles, res["report"]["findings"]))
    assert cov["secret_prefilter_findings"] >= 1


def test_coverage_present_when_budget_trims(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text("x = 1\n")
    cfg = ScanConfig(project_path=str(tmp_path), max_files=2, pass_at_k=1)
    cfg.max_total_files = 3  # force budget trim
    res = FSIMythosPipeline(cfg, converse=EmptyConverse()).run()
    assert res["coverage"]["dropped_over_budget"] == 2
    assert res["coverage"]["total_code_files"] == 5
