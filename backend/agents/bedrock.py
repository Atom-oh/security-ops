"""Thin Bedrock ``converse`` wrapper.

Centralizes the two reference-deployment rules: region comes from the container
(``AWS_REGION``), and the model id is resolved to the matching inference profile. The
boto3 client is created lazily and is injectable so unit tests never touch the network.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
import os

from agents.models import resolve_model_id, thinking_fields

DEFAULT_REGION = "us-west-2"


def extract_json(text: str) -> Any:
    """Best-effort parse of a JSON object/array out of an LLM response.

    Tolerates ```json fences and surrounding prose. Returns ``None`` if nothing parses.
    """
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    try:
        return json.loads(candidate.strip())
    except (ValueError, TypeError):
        pass
    # fall back to the first balanced [...] or {...} span
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start = candidate.find(open_c)
        end = candidate.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except (ValueError, TypeError):
                continue
    return None


class BedrockConverse:
    def __init__(self, region: Optional[str] = None, client=None):
        # Trust the container region; never a request payload's region.
        self.region = region or os.environ.get("AWS_REGION") or DEFAULT_REGION
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3  # lazy — not needed for unit tests

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def invoke(
        self,
        model_id: str,
        system: str,
        prompt: str,
        *,
        thinking: bool = True,
        effort: str = "high",
        max_tokens: int = 16384,
        temperature: float = 1.0,
    ) -> Dict[str, str]:
        resolved = resolve_model_id(model_id, self.region)
        fields = thinking_fields(effort=effort, enabled=thinking)
        response = self.client.converse(
            modelId=resolved,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            additionalModelRequestFields=fields,
        )
        return self._parse(response)

    @staticmethod
    def _parse(response: Dict) -> Dict[str, str]:
        result = {"thinking": "", "output": ""}
        content = (
            response.get("output", {}).get("message", {}).get("content", []) or []
        )
        for block in content:
            if "thinking" in block:
                result["thinking"] = block["thinking"].get("text", "")
            elif "reasoningContent" in block:  # alternate block name
                result["thinking"] = (
                    block["reasoningContent"].get("reasoningText", {}).get("text", "")
                )
            elif "text" in block:
                result["output"] += block["text"]
        return result
