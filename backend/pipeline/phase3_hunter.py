"""Phase 3 — agentic hunter.

Runs the Hunter model ``pass_at_k`` times independently (temperature 1.0 → diverse
perspectives), then deduplicates. A finding's reproducibility across runs becomes its
preliminary confidence (frequency / k); the Validator refines it later.
"""
from __future__ import annotations

import re
from typing import Dict, List

from agents.bedrock import extract_json
from agents.prompts import HUNTER_SYSTEM, hunter_user_prompt
from pipeline.config import Finding, ScanConfig, Severity


def _parse_line_range(lr) -> tuple:
    """Coerce a model-supplied line range into ``(start, end)``.

    Tolerates ``[a, b]``, ``[a]``, ``a`` (int), ``"a-b"``, ``"a"`` and junk → ``(0, 0)``.
    """
    if isinstance(lr, int):
        return (lr, lr)
    if isinstance(lr, str):
        nums = [int(n) for n in re.findall(r"\d+", lr)]
        lr = nums
    if isinstance(lr, (list, tuple)):
        nums = []
        for v in lr:
            try:
                nums.append(int(v))
            except (TypeError, ValueError):
                continue
        if len(nums) >= 2:
            return (nums[0], nums[1])
        if len(nums) == 1:
            return (nums[0], nums[0])
    return (0, 0)


def _to_finding(raw: dict, file_path: str) -> Finding:
    try:
        severity = Severity(str(raw.get("severity", "info")).lower())
    except ValueError:
        severity = Severity.INFO
    return Finding(
        title=str(raw.get("title", "untitled")),
        file_path=file_path,
        line_range=_parse_line_range(raw.get("line_range")),
        severity=severity,
        cwe_id=raw.get("cwe_id"),
        description=str(raw.get("description", "")),
        exploitation_scenario=str(raw.get("exploitation_scenario", "")),
        patch_suggestion=str(raw.get("patch_suggestion", "")),
        chain_potential=bool(raw.get("chain_potential", False)),
    )


def _dedup_key(f: Finding):
    return (f.file_path, f.line_range, f.cwe_id)


def hunt(target: Dict, config: ScanConfig, converse) -> List[Finding]:
    """Hunt one target ``{file, language, code, sink_summary}`` with pass@k dedup."""
    file_path = target["file"]
    language = target["language"]
    language_name = getattr(language, "value", str(language))
    prompt = hunter_user_prompt(
        language=language_name,
        code_content=target.get("code", ""),
        sink_summary=target.get("sink_summary", ""),
        related_context=target.get("related_context", ""),
    )

    k = max(1, config.pass_at_k)
    seen: Dict[tuple, Finding] = {}
    counts: Dict[tuple, int] = {}

    for _ in range(k):
        out = converse.invoke(config.hunter_model, HUNTER_SYSTEM, prompt, effort="high")
        parsed = extract_json(out.get("output", "")) or []
        if not isinstance(parsed, list):
            continue
        run_keys = set()
        for raw in parsed:
            if not isinstance(raw, dict):
                continue
            f = _to_finding(raw, file_path)
            key = _dedup_key(f)
            seen.setdefault(key, f)
            run_keys.add(key)
        for key in run_keys:
            counts[key] = counts.get(key, 0) + 1

    findings: List[Finding] = []
    for key, f in seen.items():
        f.confidence = round(counts.get(key, 0) / k, 4)
        findings.append(f)
    return findings
