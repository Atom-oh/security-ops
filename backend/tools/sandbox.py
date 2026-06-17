"""PoC verification via AgentCore Code Interpreter (network-isolated sandbox).

Defensive use only: the sandbox observes whether a candidate finding *reproduces* (e.g. a
crash / non-zero exit) to raise confidence — it does not synthesize weaponized exploits.
Reproduction is strong evidence, so a reproduced finding is marked validated with high
confidence. Failures are isolated and never drop findings.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pipeline.config import Finding

REPRODUCED_CONFIDENCE = 0.95


class CodeInterpreterSandbox:
    """AgentCore Code Interpreter client wrapper (lazy-bound)."""

    def __init__(self, region: Optional[str] = None, client=None):
        self._client = client
        self._region = region

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-agentcore", region_name=self._region)
        return self._client

    def verify_poc_in_sandbox(self, finding: Finding, code: str) -> Dict:
        """Run the candidate in an isolated interpreter session and report reproduction.

        Returns ``{"reproduced": bool, "output": str}``. Kept intentionally conservative —
        a real deployment wires this to ``start_code_interpreter_session`` /
        ``invoke_code_interpreter`` with no network egress.
        """
        session = self.client.start_code_interpreter_session(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            name="fsi-mythos-poc",
        )
        session_id = session["sessionId"]
        try:
            resp = self.client.invoke_code_interpreter(
                codeInterpreterIdentifier="aws.codeinterpreter.v1",
                sessionId=session_id,
                name="executeCode",
                arguments={"language": "python", "code": code},
            )
            output = str(resp.get("output", ""))
            reproduced = any(
                marker in output.lower()
                for marker in ("segmentation fault", "core dumped", "traceback", "aborted")
            )
            return {"reproduced": reproduced, "output": output}
        finally:
            try:
                self.client.stop_code_interpreter_session(
                    codeInterpreterIdentifier="aws.codeinterpreter.v1", sessionId=session_id
                )
            except Exception:
                pass


def verify_findings(
    sandbox, findings: List[Finding], code: str, enabled: bool
) -> List[Finding]:
    """When enabled, attempt sandbox reproduction per finding and boost confirmed ones."""
    if not enabled:
        return findings
    # NOTE(perf): one interpreter session per finding. A future optimization is to reuse a
    # single session per file and run multiple PoC checks within it.
    for f in findings:
        try:
            result = sandbox.verify_poc_in_sandbox(f, code)
        except Exception:
            continue  # isolation: a sandbox error must not drop findings
        if result.get("reproduced"):
            f.validated = True
            f.confidence = max(f.confidence, REPRODUCED_CONFIDENCE)
    return findings
