"""Tests for agents.models — region-aware inference profiles + thinking config."""
from __future__ import annotations

import pytest

from agents.models import (
    region_profile_prefix,
    resolve_model_id,
    thinking_fields,
)


def test_region_profile_prefix():
    assert region_profile_prefix("ap-northeast-2") == "apac"
    assert region_profile_prefix("ap-southeast-1") == "apac"
    assert region_profile_prefix("us-west-2") == "us"
    assert region_profile_prefix("us-east-1") == "us"
    assert region_profile_prefix("eu-west-1") == "eu"


def test_resolve_model_id_adds_profile_prefix():
    bare = "anthropic.claude-opus-4-7-20260415-v1:0"
    assert resolve_model_id(bare, "ap-northeast-2") == "apac." + bare
    assert resolve_model_id(bare, "us-west-2") == "us." + bare


def test_resolve_model_id_idempotent():
    already = "apac.anthropic.claude-opus-4-7-20260415-v1:0"
    assert resolve_model_id(already, "ap-northeast-2") == already


def test_thinking_fields_adaptive_on():
    f = thinking_fields(effort="high", enabled=True)
    assert f["thinking"]["type"] == "adaptive"
    assert f["output_config"]["effort"] == "high"


def test_thinking_fields_off():
    # Challenger runs with thinking disabled
    assert thinking_fields(effort="high", enabled=False) == {}


def test_thinking_fields_validates_effort():
    with pytest.raises(ValueError):
        thinking_fields(effort="bogus", enabled=True)
