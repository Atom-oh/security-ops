"""Phase 2 — file risk ranking.

Asks the Ranker model to order files by exploitability using FSI weighting. Falls back
to pure sink-density ordering when the model is unavailable or returns nothing, so the
pipeline degrades gracefully (and stays cheap) instead of failing.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from agents.bedrock import extract_json
from agents.prompts import RANKER_SYSTEM, ranker_user_prompt
from pipeline.config import ScanConfig


def _sink_density_fallback(sink_counts: Dict[str, int], max_files: int) -> List[dict]:
    ordered = sorted(sink_counts.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"file": path, "rank": i + 1, "reason": f"sink density={count}"}
        for i, (path, count) in enumerate(ordered[:max_files])
    ]


def rank_files(
    sink_counts: Dict[str, int],
    config: ScanConfig,
    converse=None,
) -> List[dict]:
    """Return ``[{file, rank, reason}]`` capped at ``config.max_files``."""
    if not sink_counts:
        return []
    if converse is None:
        return _sink_density_fallback(sink_counts, config.max_files)

    analysis = "\n".join(f"- {path}: 싱크 {count}개" for path, count in sink_counts.items())
    try:
        out = converse.invoke(
            config.ranker_model,
            RANKER_SYSTEM,
            ranker_user_prompt(file_analysis=analysis, max_files=config.max_files),
            effort="medium",
        )
        parsed = extract_json(out.get("output", ""))
    except Exception:
        parsed = None

    if not isinstance(parsed, list) or not parsed:
        return _sink_density_fallback(sink_counts, config.max_files)

    ranked = [r for r in parsed if isinstance(r, dict) and r.get("file")]
    ranked.sort(key=lambda r: r.get("rank", 1_000_000))
    # normalize rank to 1..N and cap
    capped = ranked[: config.max_files]
    for i, r in enumerate(capped):
        r["rank"] = i + 1
    return capped
