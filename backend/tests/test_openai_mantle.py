"""Tests for the OpenAI-on-Bedrock (mantle) cross-family provider (HTTP mocked)."""
from __future__ import annotations

from botocore.credentials import Credentials

from agents.openai_mantle import OpenAIMantleProvider


def test_chat_completions_parse_and_request_shape():
    captured = {}

    def fake_http(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "OK", "reasoning": "thought"}}]}

    p = OpenAIMantleProvider(model="openai.gpt-5.5", region="us-east-2", api_kind="chat", http=fake_http)
    out = p.invoke("openai.gpt-5.5", "sys", "hello")
    assert out["output"] == "OK"
    assert out["thinking"] == "thought"
    assert captured["path"] == "/chat/completions"
    assert captured["payload"]["model"] == "openai.gpt-5.5"
    roles = [m["role"] for m in captured["payload"]["messages"]]
    assert roles == ["system", "user"]


def test_responses_parse():
    def fake_http(path, payload):
        assert path == "/responses"
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "RESP-OK"}]}]}

    p = OpenAIMantleProvider(model="openai.gpt-5.5", api_kind="responses", http=fake_http)
    out = p.invoke("openai.gpt-5.5", "sys", "hi")
    assert out["output"] == "RESP-OK"


def test_gpt55_responses_uses_openai_v1_mantle_path():
    p = OpenAIMantleProvider(
        model="openai.gpt-5.5",
        region="us-east-2",
        api_kind="responses",
        credentials=Credentials("ak", "sk", "token"),
    )

    req = p._sigv4("/responses", b"{}")

    assert req.url == "https://bedrock-mantle.us-east-2.api.aws/openai/v1/responses"


def test_responses_output_text_shortcut():
    p = OpenAIMantleProvider(model="m", api_kind="responses", http=lambda path, payload: {"output_text": "X"})
    assert p.invoke("m", "s", "p")["output"] == "X"


def test_region_default():
    p = OpenAIMantleProvider(model="m")
    assert p.region == "us-east-2"
