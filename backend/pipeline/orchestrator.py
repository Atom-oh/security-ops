"""FSI-Mythos pipeline orchestrator.

Wires phases 0→7 over a target directory. Every external dependency (the Bedrock
``converse`` client, the FP store, the sandbox) is injected, so the whole orchestration is
unit-testable with fakes. A ``progress`` callback is invoked per phase so async mode can
persist live status to DynamoDB.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from pipeline.config import Finding, ScanConfig
from pipeline.phase0_languages import detect_languages
from pipeline.phase1_slicing import sink_guided_slice
from pipeline.phase2_ranker import rank_files
from pipeline.phase3_hunter import hunt
from pipeline.phase35_challenger import challenge
from pipeline.phase4_validator import validate
from pipeline.phase6_report import cicd_gate_check, generate_report, to_asff
from pipeline.phase7_fpmemory import record_false_positives, suppress_known_fps

PHASES = [
    "Phase 0 · 언어 감지",
    "Phase 1 · 싱크 슬라이싱",
    "Phase 2 · 파일 랭킹",
    "Phase 3 · 에이전틱 헌트",
    "Phase 3.5 · 적대적 자기도전",
    "Phase 4 · 회의적 검증",
    "Phase 6 · 집계/보고",
    "Phase 7 · FP 메모리",
]


class FSIMythosPipeline:
    def __init__(
        self,
        config: ScanConfig,
        converse,
        account_id: str = "000000000000",
        fp_store=None,
        sandbox=None,
        user_id: str = "anonymous",
        progress: Optional[Callable[[str], None]] = None,
    ):
        self.config = config
        self.converse = converse
        self.account_id = account_id
        self.fp_store = fp_store
        self.sandbox = sandbox
        self.user_id = user_id
        self._progress = progress

    def _emit(self, phase: str) -> None:
        if self._progress:
            try:
                self._progress(phase)
            except Exception:
                pass  # progress reporting must never break the scan

    def run(self) -> Dict:
        cfg = self.config

        # Phase 0
        self._emit(PHASES[0])
        lang_files = detect_languages(cfg.project_path)

        # Phase 1 — slice every file, build per-file slices + sink counts
        self._emit(PHASES[1])
        slices_by_file: Dict[str, List[dict]] = {}
        lang_by_file: Dict[str, object] = {}
        sink_counts: Dict[str, int] = {}
        for language, files in lang_files.items():
            for path in files:
                sl = sink_guided_slice(path, language)
                if sl:
                    slices_by_file[path] = sl
                    lang_by_file[path] = language
                    sink_counts[path] = len(sl)

        # Phase 2 — rank
        self._emit(PHASES[2])
        ranked = rank_files(sink_counts, cfg, converse=self.converse)

        # Phase 3/3.5/4 — per ranked file
        self._emit(PHASES[3])
        all_findings: List[Finding] = []
        per_file_targets: Dict[str, Dict] = {}
        for entry in ranked:
            path = entry["file"]
            slices = slices_by_file.get(path, [])
            target = {
                "file": path,
                "language": lang_by_file.get(path),
                "code": "\n...\n".join(s["numbered_context"] for s in slices),
                "sink_summary": ", ".join(f"{s['sink']}@{s['line']}" for s in slices),
            }
            per_file_targets[path] = target
            all_findings.extend(hunt(target, cfg, converse=self.converse))

        # Phase 7 (pre) — suppress known FPs before challenging (cheaper)
        if self.fp_store is not None:
            all_findings = suppress_known_fps(self.fp_store, all_findings, self.user_id)
        hunted_candidates = list(all_findings)  # post-suppression candidate set (for FP memory)

        # Phase 3.5 — challenge (grouped by file for code context)
        self._emit(PHASES[4])
        challenged: List[Finding] = []
        for path, target in per_file_targets.items():
            group = [f for f in all_findings if f.file_path == path]
            if group:
                challenged.extend(challenge(group, target, cfg, converse=self.converse))
        # keep any findings whose file wasn't a ranked target (defensive)
        challenged.extend([f for f in all_findings if f.file_path not in per_file_targets])

        # Phase 4 — validate (grouped by file)
        self._emit(PHASES[5])
        validated: List[Finding] = []
        for path, target in per_file_targets.items():
            group = [f for f in challenged if f.file_path == path]
            if group:
                validated.extend(validate(group, target, cfg, converse=self.converse))
        validated.extend([f for f in challenged if f.file_path not in per_file_targets])

        # optional sandbox PoC verification
        if cfg.sandbox_enabled and self.sandbox is not None:
            from tools.sandbox import verify_findings

            for path, target in per_file_targets.items():
                group = [f for f in validated if f.file_path == path]
                verify_findings(self.sandbox, group, target.get("code", ""), enabled=True)

        # Phase 6 — report + gate
        self._emit(PHASES[6])
        report = generate_report(validated)
        report["asff"] = [to_asff(f, self.account_id, cfg.region) for f in validated]
        gate = cicd_gate_check(validated)
        summary = {
            "total_findings": report["total_findings"],
            "critical": report["critical"],
            "high": report["high"],
            "medium": report["medium"],
            "low": report["low"],
            "chaining": report["chaining"],
            "gate_status": gate["status"],
        }

        # Phase 7 — record dismissed as FPs (best-effort)
        self._emit(PHASES[7])
        if self.fp_store is not None:
            # everything hunted but not finally validated is a (candidate) false positive —
            # including findings dropped by the Challenger in Phase 3.5.
            dismissed = [f for f in hunted_candidates if f not in validated]
            record_false_positives(self.fp_store, dismissed, self.user_id)

        return {"summary": summary, "report": report, "gate": gate}
