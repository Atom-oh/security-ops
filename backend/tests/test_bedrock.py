"""Tests for agents.bedrock — converse wrapper with region trust + block parsing."""
from __future__ import annotations

from agents.bedrock import BedrockConverse


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


_RESP = {
    "output": {
        "message": {
            "content": [
                {"thinking": {"text": "let me reason..."}},
                {"text": "final answer"},
            ]
        }
    }
}


def test_region_trusted_from_init_not_payload():
    fake = FakeClient(_RESP)
    bc = BedrockConverse(region="ap-northeast-2", client=fake)
    bc.invoke("anthropic.claude-opus-4-7-20260415-v1:0", "sys", "hi")
    sent = fake.calls[0]
    # Seoul region → apac.* inference profile
    assert sent["modelId"].startswith("apac.")
    assert sent["system"] == [{"text": "sys"}]
    assert sent["additionalModelRequestFields"]["thinking"]["type"] == "adaptive"


def test_parse_thinking_and_output():
    bc = BedrockConverse(region="us-west-2", client=FakeClient(_RESP))
    out = bc.invoke("anthropic.claude-opus-4-8-20260601-v1:0", "sys", "hi")
    assert out["thinking"] == "let me reason..."
    assert out["output"] == "final answer"


def test_thinking_off_omits_fields():
    fake = FakeClient(_RESP)
    bc = BedrockConverse(region="us-west-2", client=fake)
    bc.invoke("anthropic.claude-opus-4-6-20260205-v1:0", "sys", "hi", thinking=False)
    assert fake.calls[0]["additionalModelRequestFields"] == {}


def test_region_defaults_to_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    bc = BedrockConverse(client=FakeClient(_RESP))
    assert bc.region == "ap-northeast-2"
