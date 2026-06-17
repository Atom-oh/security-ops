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
    # files dropped over budget were never scanned → gate must fail-closed (HIGH #1)
    assert res["gate"]["status"] == "INCOMPLETE"


class _CaptureHunter(EmptyConverse):
    """Records Hunter prompts so we can assert on cross-file context."""

    def __init__(self):
        self.hunter_prompts = []

    def invoke(self, model, system, prompt, **k):
        if "보안 연구원" in system:  # hunter system prompt
            self.hunter_prompts.append(prompt)
        return super().invoke(model, system, prompt, **k)


def test_hunter_receives_cross_file_context(tmp_path):
    # HIGH-4a: with multiple candidates, the Hunter prompt must carry a related-context map
    # (related_context is no longer permanently empty).
    (tmp_path / "auth.py").write_text("import os\ndef login(p):\n    return p == os.environ['PW']\n")
    (tmp_path / "payment.py").write_text("def pay(req):\n    return req.body['amount']\n")
    cfg = ScanConfig(project_path=str(tmp_path), max_files=2, pass_at_k=1)
    cap = _CaptureHunter()
    FSIMythosPipeline(cfg, converse=cap).run()
    assert cap.hunter_prompts, "hunter should have run"
    assert any("크로스파일" in p for p in cap.hunter_prompts), "cross-file context missing"


def test_secret_found_in_unscanned_low_risk_file(tmp_path):
    # HIGH #3: a secret in a low-risk file NOT deep-scanned (max_files cap) is still caught,
    # because the prefilter now scans every file.
    (tmp_path / "payment_gateway.py").write_text(
        "def pay(request):\n    acct = request.body['account']\n    return acct\n"
    )
    (tmp_path / "util.py").write_text('API_TOKEN = "aZ4!kQ19vXp7Lm2RtY8wQ"\n')
    cfg = ScanConfig(project_path=str(tmp_path), max_files=1, pass_at_k=1)
    res = FSIMythosPipeline(cfg, converse=EmptyConverse()).run()
    assert res["coverage"]["scanned_files"] == 1  # only the riskiest file is deep-scanned
    cwes = [f.get("cwe_id") for f in res["report"]["findings"]]
    assert "CWE-798" in cwes, "secret in the unscanned util.py must still be found"


def test_cap_unscanned_passes_with_advisory(tmp_path):
    # HIGH #1 (refined): lower-risk files left below the max_files cap are still secret-scanned
    # and risk-ranked → clean PASS with an advisory, NOT a perpetual INCOMPLETE.
    for i in range(3):
        (tmp_path / f"m{i}.py").write_text("def f():\n    return 1\n")
    cfg = ScanConfig(project_path=str(tmp_path), max_files=1, pass_at_k=1)
    res = FSIMythosPipeline(cfg, converse=EmptyConverse()).run()
    assert res["coverage"]["unscanned_files"] == 2
    assert res["coverage"]["dropped_over_budget"] == 0
    assert res["gate"]["status"] == "PASSED"
    assert any("advisory" in r for r in res["gate"]["reasons"])


def test_prefilter_secret_is_suppressible(tmp_path):
    # HIGH #2: a prefilter secret finding now goes through FP memory, so it can be dismissed
    # (previously it bypassed suppression and was an unsuppressible permanent block).
    from pipeline.config import Finding, Severity
    from pipeline.phase7_fpmemory import InMemoryFPStore, record_false_positives

    (tmp_path / "util.py").write_text('API_TOKEN = "aZ4!kQ19vXp7Lm2RtY8wQ"\n')
    cfg = ScanConfig(project_path=str(tmp_path), max_files=2, pass_at_k=1)
    store = InMemoryFPStore()

    res1 = FSIMythosPipeline(cfg, converse=EmptyConverse(), fp_store=store).run()
    secret = next(f for f in res1["report"]["findings"] if f.get("cwe_id") == "CWE-798")

    record_false_positives(
        store,
        [Finding(title=secret["title"], file_path=secret["file_path"],
                 line_range=tuple(secret["line_range"]), severity=Severity.HIGH, cwe_id="CWE-798")],
        "anonymous",
    )

    res2 = FSIMythosPipeline(cfg, converse=EmptyConverse(), fp_store=store).run()
    assert all(f.get("cwe_id") != "CWE-798" for f in res2["report"]["findings"]), \
        "dismissed secret FP should be suppressed on the next scan"
