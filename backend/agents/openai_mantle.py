"""Cross-family provider: OpenAI models on Amazon Bedrock via the ``bedrock-mantle``
OpenAI-compatible endpoint.

In-AWS boundary (no public api.openai.com): requests are SigV4-signed with the runtime's IAM
role — no stored API key (data residency stays within the chosen Bedrock region). Exposes the
same ``invoke(...) -> {"thinking", "output"}`` shape as ``BedrockConverse`` so it's a drop-in
ensemble member.

Verified live against ``openai.gpt-oss-120b`` (us-east-2). AWS documents
``openai.gpt-5.5`` on the ``/openai/v1/responses`` mantle path once model access is entitled
in the account.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

DEFAULT_MANTLE_REGION = "us-east-2"


def _endpoint(region: str) -> str:
    # The mantle OpenAI-compatible surface lives under /openai/v1 (verified against the
    # working Codex-on-Bedrock config; gpt-5.5 is served here).
    return f"https://bedrock-mantle.{region}.api.aws/openai/v1"


class OpenAIMantleProvider:
    def __init__(
        self,
        model: str,
        region: Optional[str] = None,
        api_kind: str = "chat",  # "chat" (chat/completions) | "responses"
        credentials=None,
        http=None,
    ):
        self.model = model
        self.region = region or os.environ.get("MANTLE_REGION") or DEFAULT_MANTLE_REGION
        self.api_kind = api_kind
        self._credentials = credentials
        self._http = http  # injectable (signed_url, headers, body)->dict for tests

    # --- transport -----------------------------------------------------------------
    def _sigv4(self, path: str, body: bytes):
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        creds = self._credentials
        if creds is None:
            resolved = boto3.Session().get_credentials()
            if resolved is None:
                raise RuntimeError("No AWS credentials available for SigV4 signing to bedrock-mantle")
            creds = resolved.get_frozen_credentials()
        req = AWSRequest(
            method="POST", url=_endpoint(self.region) + path, data=body,
            headers={"Content-Type": "application/json"},
        )
        SigV4Auth(creds, "bedrock", self.region).add_auth(req)
        return req.prepare()

    def _post(self, path: str, payload: Dict) -> Dict:
        body = json.dumps(payload).encode()
        if self._http is not None:  # test seam
            return self._http(path, payload)
        import urllib.request

        pr = self._sigv4(path, body)
        with urllib.request.urlopen(
            urllib.request.Request(pr.url, data=body, headers=dict(pr.headers), method="POST"),
            timeout=120,
        ) as r:
            return json.loads(r.read())

    # --- public API (mirrors BedrockConverse.invoke) ---------------------------------
    def invoke(self, model: str, system: str, prompt: str, *, thinking: bool = True,
               effort: str = "high", max_tokens: int = 16384, temperature: float = 1.0) -> Dict[str, str]:
        mid = model or self.model
        if self.api_kind == "responses":
            payload = {
                "model": mid,
                "input": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
            return self._parse_responses(self._post("/responses", payload))
        payload = {
            "model": mid,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": max_tokens,
        }
        return self._parse_chat(self._post("/chat/completions", payload))

    @staticmethod
    def _parse_chat(resp: Dict) -> Dict[str, str]:
        msg = (resp.get("choices") or [{}])[0].get("message", {}) or {}
        return {"thinking": str(msg.get("reasoning", "") or ""), "output": str(msg.get("content", "") or "")}

    @staticmethod
    def _parse_responses(resp: Dict) -> Dict[str, str]:
        if resp.get("output_text"):
            return {"thinking": "", "output": str(resp["output_text"])}
        out, thinking = "", ""
        for item in resp.get("output", []) or []:
            itype = item.get("type")
            for block in item.get("content", []) or []:
                txt = block.get("text", "")
                if itype == "reasoning" or block.get("type") == "reasoning_text":
                    thinking += txt
                else:
                    out += txt
        return {"thinking": thinking, "output": out}
