"""Advisory staleness guard for scan history (Task 2).

A scan can be stranded ``IN_PROGRESS`` if its worker is frozen/reaped (see the durable-dispatch
fix). Rather than mutate the canonical ``status`` on read — which would race a late, legitimate
completion — we annotate each record with an *advisory* view: ``statusView`` / ``stale`` /
``staleReason``. The poller/UI shows ``statusView`` so a dead scan never spins forever, while the
stored ``status`` stays authoritative for whenever (if ever) the worker finishes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

DEFAULT_STALE_AFTER_SEC = 1800  # 30m — comfortably exceeds the worst-case single phase


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def annotate_stale(record: Dict, now_iso: str, stale_after_sec: int = DEFAULT_STALE_AFTER_SEC) -> Dict:
    """Return a COPY of ``record`` with ``statusView`` / ``stale`` / ``staleReason`` added.

    Only ``IN_PROGRESS`` records can be stale. The canonical ``status`` is never changed. Missing
    timestamps are treated as stale (fail-closed — better a false "timed_out" view than a record
    that spins forever)."""
    out = dict(record)
    status = out.get("status")
    if status != "IN_PROGRESS":
        out["stale"] = False
        out["statusView"] = status
        return out

    now = _parse(now_iso)
    last = _parse(out.get("updatedAt")) or _parse(out.get("createdAt"))
    if now is None or last is None:
        out["stale"] = True
        out["statusView"] = "timed_out"
        out["staleReason"] = "no heartbeat timestamp"
        return out

    age = (now - last.astimezone(timezone.utc)).total_seconds()
    if age > stale_after_sec:
        out["stale"] = True
        out["statusView"] = "timed_out"
        out["staleReason"] = (
            f"no heartbeat for {int(age)}s (> {stale_after_sec}s); last phase: "
            f"{out.get('currentPhase', 'unknown')}"
        )
    else:
        out["stale"] = False
        out["statusView"] = "IN_PROGRESS"
    return out
