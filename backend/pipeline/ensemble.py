"""Phase 4.5 — cross-family ensemble validation.

An independent OpenAI model (different training family than the Claude Hunter/Validator)
re-judges each validated finding. Voting across families reduces correlated blind spots:

  both families confirm        → CONFIRMED  (confidence boosted)
  families disagree            → ESCALATE   (human review — gate treats as blocking)
  both explicitly dismiss      → dropped

By the time this runs (after Phase 4) Claude has already dropped its own dismissals, so in
practice the Claude side "wants attention" (verdict != DISMISSED) and the realistic outcomes
are CONFIRMED or ESCALATE. We deliberately do NOT let a single OpenAI dismissal drop a finding
(security: one model must not silently suppress another's finding) — disagreement escalates.

Opt-in; the orchestrator only calls this when ``ensemble_enabled`` and an OpenAI provider is
supplied. Per-finding isolated and run concurrently; any provider error keeps the Claude verdict.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from agents.bedrock import extract_json
from agents.prompts import VALIDATOR_SYSTEM, validator_user_prompt, system_for
from pipeline.config import Finding, Verdict

log = logging.getLogger("fsi.ensemble")

_MAX_WORKERS = 4


def cross_family_validate(findings: List[Finding], target: Dict, config, openai_provider) -> List[Finding]:
    if not findings or openai_provider is None:
        return findings
    language = target.get("language", "")
    language_name = getattr(language, "value", str(language))
    code = target.get("code", "")

    def judge(f: Finding) -> Optional[Finding]:
        # Claude side "wants attention" unless it explicitly dismissed — an ESCALATE must never
        # be silently dropped by an OpenAI dismissal.
        claude_confirms = f.verdict is not Verdict.DISMISSED
        try:
            out = openai_provider.invoke(
                config.openai_model,
                system_for(config, "validator", VALIDATOR_SYSTEM),
                validator_user_prompt(  # already wraps code in the nonce untrusted-data block
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
            return f

        other_confirms = other_verdict in ("confirmed", "likely")
        if claude_confirms and other_confirms:
            f.verdict = Verdict.CONFIRMED
            f.confidence = max(f.confidence, 0.95)
            f.cross_family = "both"
            return f
        if claude_confirms != other_confirms:
            f.verdict = Verdict.ESCALATE  # disagreement → human review, never silent drop
            f.cross_family = "disagree"
            return f
        return None  # both explicitly dismiss → drop

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(findings))) as ex:
        judged = list(ex.map(judge, findings))
    return [f for f in judged if f is not None]
