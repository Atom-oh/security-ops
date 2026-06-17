"""Phase 4.5 — cross-family ensemble validation.

An independent OpenAI model (different training family than the Claude Hunter/Validator)
re-judges each validated finding. Voting across families reduces correlated blind spots:

  both families confirm  → CONFIRMED  (confidence boosted)
  disagree               → ESCALATE   (human review — gate treats as blocking)
  both dismiss           → dropped

Opt-in escalation; the orchestrator only calls this when ``ensemble_enabled`` and an OpenAI
provider is supplied. Isolated: any provider error leaves the Claude verdict untouched.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List

from agents.bedrock import extract_json
from agents.prompts import VALIDATOR_SYSTEM, validator_user_prompt
from pipeline.config import Finding, Verdict

log = logging.getLogger("fsi.ensemble")

_CONFIRMING = {Verdict.CONFIRMED, Verdict.LIKELY}


def cross_family_validate(findings: List[Finding], target: Dict, config, openai_provider) -> List[Finding]:
    if not findings or openai_provider is None:
        return findings
    language = target.get("language", "")
    language_name = getattr(language, "value", str(language))
    code = target.get("code", "")

    result: List[Finding] = []
    for f in findings:
        claude_confirms = (f.verdict in _CONFIRMING) if f.verdict else True
        try:
            out = openai_provider.invoke(
                config.openai_model,
                VALIDATOR_SYSTEM,
                validator_user_prompt(
                    findings_json=json.dumps([f.to_dict()], ensure_ascii=False),
                    language=language_name,
                    code_content=code,
                ),
                effort="high",
            )
            parsed = extract_json(out.get("output", "")) or []
            item = parsed[0] if isinstance(parsed, list) and parsed else (parsed if isinstance(parsed, dict) else {})
            other_verdict = str(item.get("verdict", "confirmed")).lower()
        except Exception:
            log.exception("ensemble: openai provider failed for %s; keeping Claude verdict", f.id)
            result.append(f)
            continue

        other_confirms = other_verdict in ("confirmed", "likely")
        if claude_confirms and other_confirms:
            f.verdict = Verdict.CONFIRMED
            f.confidence = max(f.confidence, 0.95)
            f.cross_family = "both"
            result.append(f)
        elif claude_confirms != other_confirms:
            # families disagree → escalate for human review (do not silently drop)
            f.verdict = Verdict.ESCALATE
            f.cross_family = "disagree"
            result.append(f)
        else:
            # both dismiss → drop
            continue
    return result
