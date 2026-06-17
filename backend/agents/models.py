"""Region-aware Bedrock model resolution + extended-thinking request fields.

Two lessons from the reference deployment are encoded here:

1. Opus 4.7/4.8 use ``thinking.type = "adaptive"`` paired with ``output_config.effort`` —
   NOT the legacy ``thinking.type = "enabled"`` + ``budget_tokens``.
2. The cross-region inference-profile prefix is derived from the *container* region.
   Seoul (ap-northeast-2) needs ``apac.*`` profiles; us-west-2 needs ``us.*``. Sending a
   ``us.*`` id to a Seoul runtime yields "model identifier is invalid".
"""
from __future__ import annotations

from typing import Dict

_VALID_EFFORT = {"low", "medium", "high"}

# region prefix → inference-profile namespace.
# Heuristic for Bedrock cross-region inference profiles. us/ap/eu are the real geo
# namespaces; ca/sa have no dedicated Opus profile today so they borrow ``us`` — override
# by passing an already-prefixed model id in ScanConfig if a region needs something else.
_GEO_PREFIX = {
    "us": "us",
    "ap": "apac",
    "eu": "eu",
    "ca": "us",
    "sa": "us",
}

_KNOWN_PROFILE_PREFIXES = ("us.", "apac.", "eu.")


def region_profile_prefix(region: str) -> str:
    """Map an AWS region to its Bedrock inference-profile namespace."""
    geo = (region or "").split("-", 1)[0].lower()
    return _GEO_PREFIX.get(geo, "us")


def resolve_model_id(model_id: str, region: str) -> str:
    """Prefix a bare ``anthropic.*`` model id with the region's profile namespace.

    Idempotent: an id that already carries a known profile prefix is returned unchanged.
    """
    if model_id.startswith(_KNOWN_PROFILE_PREFIXES):
        return model_id
    return f"{region_profile_prefix(region)}.{model_id}"


def thinking_fields(effort: str = "high", enabled: bool = True) -> Dict:
    """Build ``additionalModelRequestFields`` for extended thinking.

    Returns ``{}`` when disabled (e.g. the Challenger, which runs thinking-off).
    """
    if not enabled:
        return {}
    if effort not in _VALID_EFFORT:
        raise ValueError(f"effort must be one of {_VALID_EFFORT}, got {effort!r}")
    return {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }
