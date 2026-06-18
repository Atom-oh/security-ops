"""FSI-Mythos pipeline orchestrator.

Wires phases 0→7 over a target directory. Every external dependency (the Bedrock
``converse`` client, the FP store, the sandbox) is injected, so the whole orchestration is
unit-testable with fakes. A ``progress`` callback is invoked per phase so async mode can
persist live status to DynamoDB.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable, Dict, List, Optional

log = logging.getLogger("fsi.pipeline")

from pipeline.config import Finding, ScanConfig, enforce_budget
from pipeline.phase0_languages import detect_languages
from pipeline.phase1_slicing import numbered_file, sink_guided_slice
from pipeline.phase25_prefilter import scan_secrets
from pipeline.risk_score import rank_by_risk, score_file
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
        heartbeat: Optional[Callable[[], None]] = None,
        openai_provider=None,
    ):
        self.config = config
        self.converse = converse
        self.account_id = account_id
        self.fp_store = fp_store
        self.sandbox = sandbox
        self.user_id = user_id
        self._progress = progress
        self._heartbeat = heartbeat
        self.openai_provider = openai_provider

    def _emit(self, phase: str) -> None:
        if self._progress:
            try:
                self._progress(phase)
            except Exception:
                pass  # progress reporting must never break the scan

    def _beat(self) -> None:
        """Liveness ping during long phases (e.g. the multi-minute Phase-3 Hunter). Without
        intra-phase heartbeats a healthy long scan would trip the staleness guard."""
        if self._heartbeat:
            try:
                self._heartbeat()
            except Exception:
                pass  # heartbeat must never break the scan

    def run(self) -> Dict:
        cfg = self.config
        t0 = time.time()
        log.info("scan start: path=%s max_files=%s pass_at_k=%s region=%s models=[hunter=%s ranker=%s validator=%s]",
                 cfg.project_path, cfg.max_files, cfg.pass_at_k, cfg.region,
                 cfg.hunter_model, cfg.ranker_model, cfg.validator_model)

        # Phase 0
        self._emit(PHASES[0])
        lang_files = detect_languages(cfg.project_path)
        log.info("phase0: %s", {k.value: len(v) for k, v in lang_files.items()})

        # Phase 1 — slice every file, build per-file slices + sink counts
        self._emit(PHASES[1])
        # Track ALL code files (not only ones with sinks). Files without an explicit sink are
        # still candidates — the Hunter examines the whole file (semantic reasoning catches
        # vulns that keyword slicing misses). sink_counts drives ranking priority.
        slices_by_file: Dict[str, List[dict]] = {}
        lang_by_file: Dict[str, object] = {}
        sink_counts: Dict[str, int] = {}
        risk_scores: Dict[str, tuple] = {}
        file_sizes: List[tuple] = []
        for language, files in lang_files.items():
            for path in files:
                sl = sink_guided_slice(path, language)
                slices_by_file[path] = sl
                lang_by_file[path] = language
                sink_counts[path] = len(sl)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read(20000)  # sample for risk signals
                    size = os.path.getsize(path)
                except OSError:
                    content, size = "", 0
                risk_scores[path] = score_file(path, language, len(sl), content)
                file_sizes.append((path, size))
        total_code_files = len(file_sizes)
        files_with_sinks = sum(1 for c in sink_counts.values() if c > 0)
        log.info("phase1: %d code files, %d with explicit sinks", total_code_files, files_with_sinks)

        # Phase 2 — deterministic risk triage (FSI-weighted), budget-guarded, then top-N.
        self._emit(PHASES[2])
        risk_ordered = sorted(file_sizes, key=lambda ps: risk_scores[ps[0]][0], reverse=True)
        kept, dropped_over_budget = enforce_budget(
            risk_ordered, cfg.max_total_files, cfg.max_total_bytes
        )
        kept_paths = [p for p, _ in kept]
        ranked = rank_by_risk({p: risk_scores[p] for p in kept_paths}, cfg.max_files)
        log.info("phase2: triaged %d→%d candidates (budget dropped %d); top %d: %s",
                 total_code_files, len(kept_paths), dropped_over_budget, len(ranked),
                 [r.get("file") for r in ranked])

        # Phase 2.5 — deterministic secret pre-filter (cheap, no LLM). Run over EVERY detected
        # file, not just the ranked/budget-kept subset: secret scanning costs no tokens, so a
        # hardcoded key in a low-risk or budget-dropped file must not be missed (HIGH #3).
        prefilter_findings: List[Finding] = []
        for path in lang_by_file:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    prefilter_findings.extend(scan_secrets(path, lang_by_file.get(path), fh.read(40000)))
            except OSError:
                continue
        if prefilter_findings:
            log.info("phase2.5: %d deterministic secret findings (all files)", len(prefilter_findings))

        # Cross-file awareness map: a compact index of the other candidate files so the Hunter
        # can reason about interactions spanning files (HIGH-4a). Full interprocedural taint is
        # deferred to v2.2; this at least stops related_context from being permanently empty.
        candidate_index = [
            {
                "file": p,
                "lang": getattr(lang_by_file.get(p), "value", str(lang_by_file.get(p))),
                "sinks": sink_counts.get(p, 0),
            }
            for p in kept_paths
        ]

        def _related_context(path: str) -> str:
            others = [c for c in candidate_index if c["file"] != path][:20]
            if not others:
                return ""
            lines = ["다른 후보 파일(크로스파일 데이터 흐름·상호작용 검토용):"]
            lines += [f"- {o['file']} ({o['lang']}, sinks={o['sinks']})" for o in others]
            return "\n".join(lines)

        # Phase 3/3.5/4 — per ranked file
        self._emit(PHASES[3])
        all_findings: List[Finding] = []
        per_file_targets: Dict[str, Dict] = {}
        hunt_failures = 0
        for entry in ranked:
            path = entry["file"]
            slices = slices_by_file.get(path, [])
            if slices:
                code = "\n...\n".join(s["numbered_context"] for s in slices)
                sink_summary = ", ".join(f"{s['sink']}@{s['line']}" for s in slices)
            else:
                # No explicit sink → hand the Hunter the whole file to reason over.
                code = numbered_file(path)
                sink_summary = "(명시적 싱크 없음 — 전체 파일을 의미론적으로 검토)"
            target = {
                "file": path,
                "language": lang_by_file.get(path),
                "code": code,
                "sink_summary": sink_summary,
                "related_context": _related_context(path),
            }
            per_file_targets[path] = target
            self._beat()  # intra-phase liveness ping (Phase 3 can run many minutes)
            # Isolate per-file hunt errors (e.g. a transient Bedrock failure) so one bad file
            # doesn't abort the whole scan.
            try:
                found = hunt(target, cfg, converse=self.converse)
                log.info("phase3 hunt %s: %d findings", path, len(found))
                all_findings.extend(found)
            except Exception:
                hunt_failures += 1
                log.exception("phase3 hunt failed for %s", path)

        # A few failed files are tolerated, but if EVERY hunt failed the scan can't claim the
        # target is clean — surface it as an error (false-negative guard for a security tool).
        if ranked and hunt_failures == len(ranked):
            raise RuntimeError(f"all {hunt_failures} file hunts failed (e.g. Bedrock unavailable)")

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
                try:
                    validated.extend(validate(group, target, cfg, converse=self.converse))
                except Exception:
                    log.exception("phase4 validate failed for %s; keeping unvalidated", path)
                    validated.extend(group)
        validated.extend([f for f in challenged if f.file_path not in per_file_targets])

        # optional sandbox PoC verification
        if cfg.sandbox_enabled and self.sandbox is not None:
            from tools.sandbox import verify_findings

            for path, target in per_file_targets.items():
                group = [f for f in validated if f.file_path == path]
                verify_findings(self.sandbox, group, target.get("code", ""), enabled=True)

        # Phase 4.5 — cross-family ensemble (opt-in). An independent OpenAI model re-judges
        # each finding; disagreement escalates rather than silently dropping.
        if cfg.ensemble_enabled and self.openai_provider is not None:
            from pipeline.ensemble import cross_family_validate
            ensembled: List[Finding] = []
            for path, target in per_file_targets.items():
                group = [f for f in validated if f.file_path == path]
                if group:
                    ensembled.extend(cross_family_validate(group, target, cfg, self.openai_provider))
            ensembled.extend([f for f in validated if f.file_path not in per_file_targets])
            log.info("phase4.5 ensemble: %d→%d findings (cross-family)", len(validated), len(ensembled))
            validated = ensembled

        # Merge deterministic Phase 2.5 secret findings — but route them through FP suppression
        # too (HIGH #2). Prefilter findings are validated=True and skip the Challenger/Validator,
        # so without this a regex false positive would be an unsuppressible permanent CI block.
        if self.fp_store is not None:
            prefilter_findings = suppress_known_fps(self.fp_store, prefilter_findings, self.user_id)
        validated = validated + prefilter_findings

        # Coverage must be computed BEFORE the gate so an incomplete scan can fail-closed (#1).
        coverage = {
            "total_code_files": total_code_files,
            "scanned_files": len(ranked),
            "unscanned_files": max(0, total_code_files - len(ranked)),
            "dropped_over_budget": dropped_over_budget,
            "secret_prefilter_findings": len(prefilter_findings),
        }

        # Phase 6 — report + gate (gate is coverage-aware: unscanned/dropped → INCOMPLETE)
        self._emit(PHASES[6])
        report = generate_report(validated)
        report["asff"] = [to_asff(f, self.account_id, cfg.region) for f in validated]
        gate = cicd_gate_check(validated, coverage=coverage)
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

        summary["coverage"] = coverage
        log.info("scan done in %.1fs: %s gate=%s coverage=%s",
                 time.time() - t0, {k: v for k, v in summary.items() if k != "coverage"},
                 gate["status"], coverage)
        return {"summary": summary, "report": report, "gate": gate, "coverage": coverage}
