"""Tests for agents.prompts formatters."""
from __future__ import annotations

import re

from agents import prompts


def _no_unfilled_braces(s: str) -> bool:
    # no leftover single-brace placeholders like {foo}
    return re.search(r"(?<!\{)\{[a-zA-Z_]\w*\}(?!\})", s) is None


def test_system_prompts_are_defensive():
    for p in (
        prompts.RANKER_SYSTEM,
        prompts.HUNTER_SYSTEM,
        prompts.CHALLENGER_SYSTEM,
        prompts.VALIDATOR_SYSTEM,
    ):
        assert isinstance(p, str) and len(p) > 50


def test_ranker_user_prompt_fills():
    out = prompts.ranker_user_prompt(file_analysis="f1: 3 sinks", max_files=8)
    assert "f1: 3 sinks" in out and "8" in out
    assert _no_unfilled_braces(out)


def test_hunter_user_prompt_fills():
    out = prompts.hunter_user_prompt(
        language="c", code_content="strcpy(a,b);", sink_summary="strcpy@4", related_context=""
    )
    assert "strcpy(a,b);" in out and "strcpy@4" in out
    assert _no_unfilled_braces(out)


def test_challenger_user_prompt_fills():
    out = prompts.challenger_user_prompt(
        finding_json='{"title":"x"}', language="c", code_content="code"
    )
    assert '{"title":"x"}' in out
    assert _no_unfilled_braces(out)


def test_validator_user_prompt_fills():
    out = prompts.validator_user_prompt(
        findings_json='[{"title":"x"}]', language="c", code_content="code"
    )
    assert "[{" in out
    assert _no_unfilled_braces(out)
