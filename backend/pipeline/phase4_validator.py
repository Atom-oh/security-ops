"""Phase 4 — final skeptical validation.

The Validator (the strongest model) assigns each surviving finding a final verdict and a
calibrated confidence. ``dismissed`` findings are dropped; everything else is kept with
its verdict recorded. If the model returns nothing for a finding, we keep it
conservatively as ``likely`` rather than silently dropping a possible real bug.
"""
from __future__ import annotations

import json
from typing import Dict, List

from agents.bedrock import extract_json
from agents.prompts import VALIDATOR_SYSTEM, validator_user_prompt
from pipeline.config import Finding, Verdict


def _coerce_verdict(value: str) -> Verdict:
    try:
        return Verdict(str(value).lower())
    except ValueError:
        return Verdict.LIKELY


def validate(findings: List[Finding], target: Dict, config, converse) -> List[Finding]:
    if not findings:
        return findings
    language = target.get("language", "")
    language_name = getattr(language, "value", str(language))

    findings_json = json.dumps([f.to_dict() for f in findings], ensure_ascii=False)
    out = converse.invoke(
        config.validator_model,
        VALIDATOR_SYSTEM,
        validator_user_prompt(
            findings_json=findings_json,
            language=language_name,
            code_content=target.get("code", ""),
        ),
        effort="high",
    )
    parsed = extract_json(out.get("output", "")) or []
    by_id: Dict[str, dict] = {}
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and item.get("id"):
                by_id[item["id"]] = item

    result: List[Finding] = []
    for f in findings:
        verdict_data = by_id.get(f.id)
        if verdict_data is None:
            f.verdict = Verdict.LIKELY  # conservative default
            f.validated = True
            result.append(f)
            continue
        verdict = _coerce_verdict(verdict_data.get("verdict", "likely"))
        if verdict is Verdict.DISMISSED:
            continue  # final false positive
        f.verdict = verdict
        if "confidence" in verdict_data:
            try:
                f.confidence = float(verdict_data["confidence"])
            except (TypeError, ValueError):
                pass
        f.validated = bool(verdict_data.get("validated", True))
        result.append(f)
    return result
