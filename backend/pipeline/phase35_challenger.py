"""Phase 3.5 — adversarial self-challenge.

The Challenger tries to *refute* each Hunter finding (thinking OFF — fast, skeptical).
Findings it judges ``dismissed`` are dropped as false positives. The whole phase is
isolated: if the Challenger errors, we preserve the Hunter findings rather than lose them.
"""
from __future__ import annotations

from typing import Dict, List

from agents.bedrock import extract_json
from agents.prompts import CHALLENGER_SYSTEM, challenger_user_prompt
from pipeline.config import Finding


def challenge(
    findings: List[Finding], target: Dict, config, converse
) -> List[Finding]:
    """Return the surviving findings after adversarial refutation."""
    if not findings:
        return findings
    language = target.get("language", "")
    language_name = getattr(language, "value", str(language))
    code = target.get("code", "")

    try:
        survivors: List[Finding] = []
        for f in findings:
            import json

            out = converse.invoke(
                config.challenger_model,
                CHALLENGER_SYSTEM,
                challenger_user_prompt(
                    finding_json=json.dumps(f.to_dict(), ensure_ascii=False),
                    language=language_name,
                    code_content=code,
                ),
                thinking=False,  # Challenger runs thinking-off
            )
            parsed = extract_json(out.get("output", "")) or {}
            verdict = parsed.get("verdict", "likely") if isinstance(parsed, dict) else "likely"
            if str(verdict).lower() == "dismissed":
                continue  # refuted → drop
            survivors.append(f)
        return survivors
    except Exception:
        # Isolation: a Challenger failure must not discard Hunter findings.
        return findings
