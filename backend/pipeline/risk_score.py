"""Deterministic file risk triage (Phase 2 candidate scoring).

Cheap, LLM-free scoring so the backend can prioritize the riskiest files repo-wide before
spending Opus tokens. Signals from the v2 design panel: sink density, path/name signals,
data-sensitivity terms, input/taint surface, language weight — minus exclusion penalties.
Uses plain substring checks (no heavy regex) since it runs over many files.

Anti-gaming: the exclusion penalty is *capped* when a file shows strong positive signals, so a
malicious file can't hide by stuffing `test`/`mock` into its name/path.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from pipeline.config import Language

# path/filename signals (high-value surfaces)
_NAME_SIGNALS = [
    "auth", "login", "session", "token", "jwt", "password", "passwd", "credential",
    "crypto", "cipher", "secret", "payment", "transfer", "remit", "account", "admin",
    "api", "gateway", "handler", "controller", "middleware", "router", "route", "upload",
]
# data-sensitivity terms (content)
_SENSITIVE_TERMS = [
    "account", "balance", "ledger", "settlement", "transfer", "payment", "card",
    "ssn", "pii", "kyc", "aml", "passport", "resident", "iban", "swift",
]
# input/taint sources (content)
_TAINT_SOURCES = [
    "request", "param", "body", "query", "getenv", "environ", "argv", "stdin",
    "readfile", "read_file", "socket", "input(", "formvalue", "r.url",
]
# exclusion markers (path)
_EXCLUDE = [
    "/test", "test/", "_test.", ".test.", "spec.", "/mock", "mock/", "generated",
    "vendor", "node_modules", ".min.", "/dist/", "/build/", "lock", "fixture",
]

_LANG_WEIGHT = {
    Language.C: 4.0, Language.CPP: 4.0,
    Language.JAVA: 1.5, Language.GO: 1.5,
    Language.PYTHON: 1.0, Language.JAVASCRIPT: 1.0, Language.TYPESCRIPT: 1.0,
    Language.KOTLIN: 1.0, Language.SWIFT: 1.0,
}

_STRONG_NAME = {"auth", "login", "token", "jwt", "password", "crypto", "secret",
                "payment", "transfer", "account", "admin", "credential"}


def score_file(path: str, language, sink_count: int = 0, content: str = "") -> Tuple[float, List[str]]:
    """Return ``(score, reasons)`` for one file. Higher = more security-relevant."""
    p = path.lower()
    c = (content or "").lower()
    reasons: List[str] = []
    score = 0.0

    if sink_count:
        s = min(sink_count, 10) * 2.0
        score += s
        reasons.append(f"sinks×{sink_count}")

    strong = False
    for sig in _NAME_SIGNALS:
        if sig in p:
            score += 3.0
            reasons.append(f"path:{sig}")
            if sig in _STRONG_NAME:
                strong = True

    sens = {t for t in _SENSITIVE_TERMS if t in c}
    if sens:
        score += 2.0 * len(sens)
        reasons.append("data:" + ",".join(sorted(sens)[:4]))
        strong = strong or len(sens) >= 2

    taint = {t for t in _TAINT_SOURCES if t in c}
    if taint:
        score += 1.5 * len(taint)
        reasons.append(f"taint×{len(taint)}")

    lw = _LANG_WEIGHT.get(language, 1.0)
    score += lw
    if lw >= 4.0:
        reasons.append("lang:C/C++")
        strong = True

    if sink_count >= 3:
        strong = True

    # Exclusion penalty — capped when strong signals exist (anti-gaming).
    if any(m in p for m in _EXCLUDE):
        penalty = 8.0
        if strong:
            penalty = min(penalty, score * 0.5)  # can't zero out a genuinely risky file
            reasons.append("excluded(capped: strong signals)")
        else:
            reasons.append("excluded")
        score -= penalty

    return max(0.0, round(score, 3)), reasons


def rank_by_risk(scores: Dict[str, Tuple[float, List[str]]], max_files: int) -> List[dict]:
    """Order files by descending risk score; return top ``max_files`` with reasons."""
    ordered = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
    out: List[dict] = []
    for i, (path, (sc, reasons)) in enumerate(ordered[:max_files]):
        out.append({"file": path, "rank": i + 1, "score": sc, "reasons": reasons})
    return out
