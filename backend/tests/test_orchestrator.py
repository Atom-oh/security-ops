"""End-to-end orchestrator test with all Bedrock calls faked."""
from __future__ import annotations

from pathlib import Path

from pipeline.config import ScanConfig
from pipeline.orchestrator import PHASES, FSIMythosPipeline
from pipeline.phase7_fpmemory import InMemoryFPStore


class RoleConverse:
    """Routes by system-prompt keyword to canned per-role JSON."""

    def invoke(self, model, system, prompt, **k):
        if "랭킹" in system:  # ranker
            return {"thinking": "", "output": '[{"file":"FILE","rank":1,"reason":"r"}]'.replace("FILE", _TARGET[0])}
        if "시니어 보안 연구원" in system:  # hunter
            return {
                "thinking": "",
                "output": '[{"title":"strcpy overflow","cwe_id":"CWE-120","severity":"critical",'
                '"line_range":[4,4],"chain_potential":true}]',
            }
        if "반박" in system:  # challenger
            return {"thinking": "", "output": '{"verdict":"confirmed","confidence":0.95}'}
        if "최종" in system:  # validator
            return {"thinking": "", "output": '[]'}  # filled in test via monkey
        return {"thinking": "", "output": "[]"}


_TARGET = [""]  # set per test to the scanned file path


def _make_target(tmp_path: Path) -> str:
    f = tmp_path / "transfer.c"
    f.write_text("void f(char*u){\n char b[16];\n strcpy(b,u);\n system(u);\n}\n")
    _TARGET[0] = str(f)
    return str(f)


class ValidatingConverse(RoleConverse):
    """Validator confirms the single hunted finding by id."""

    def invoke(self, model, system, prompt, **k):
        if "최종" in system:
            # confirm everything the prompt references
            return {
                "thinking": "",
                "output": '[{"id":"%s","verdict":"confirmed","confidence":0.97,"validated":true}]'
                % _find_id(prompt),
            }
        return super().invoke(model, system, prompt, **k)


def _find_id(prompt: str) -> str:
    import re

    m = re.search(r'"id":\s*"(fsi-[0-9a-f]{16})"', prompt)
    return m.group(1) if m else "fsi-0000000000000000"


def test_pipeline_end_to_end(tmp_path):
    _make_target(tmp_path)
    cfg = ScanConfig(project_path=str(tmp_path), max_files=5, pass_at_k=1)
    seen = []
    pipe = FSIMythosPipeline(
        cfg, converse=ValidatingConverse(), fp_store=InMemoryFPStore(),
        progress=seen.append,
    )
    result = pipe.run()
    assert set(result) == {"summary", "report", "gate"}
    assert result["summary"]["critical"] == 1
    assert result["gate"]["status"] == "BLOCKED"  # critical + chaining
    assert result["report"]["asff"][0]["Severity"]["Label"] == "CRITICAL"
    # progress callback fired for every phase
    assert seen == PHASES


def test_persistence_isolation_via_progress_error(tmp_path):
    _make_target(tmp_path)
    cfg = ScanConfig(project_path=str(tmp_path), max_files=5, pass_at_k=1)

    def boom(_phase):
        raise RuntimeError("ddb write failed")

    pipe = FSIMythosPipeline(cfg, converse=ValidatingConverse(), progress=boom)
    # progress errors are swallowed → result still returned
    result = pipe.run()
    assert result["summary"]["total_findings"] == 1
