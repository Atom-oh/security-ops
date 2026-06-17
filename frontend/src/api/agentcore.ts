// Calls the AgentCore Runtime data-plane /invocations endpoint directly from the browser,
// authorized by the Cognito ACCESS token (Bearer). The JWT authorizer on the runtime
// validates the token's client_id claim.
import { config } from "../config";
import { HistoryItem, ScanRequest, ScanResult } from "./types";

function invocationsUrl(): string {
  const arn = encodeURIComponent(config.runtimeArn);
  return `https://bedrock-agentcore.${config.region}.amazonaws.com/runtimes/${arn}/invocations?qualifier=DEFAULT`;
}

async function invoke<T>(token: string, payload: Record<string, unknown>): Promise<T> {
  const res = await fetch(invocationsUrl(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`AgentCore ${res.status}: ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function scan(token: string, req: ScanRequest): Promise<ScanResult> {
  return invoke<ScanResult>(token, { action: "scan", ...req });
}

export function scanAsync(token: string, req: ScanRequest): Promise<ScanResult> {
  return invoke<ScanResult>(token, { action: "scan_async", ...req });
}

export function getScan(token: string, scanId: string): Promise<{ scan: HistoryItem | null }> {
  return invoke(token, { action: "get_scan", scanId });
}

export function listHistory(token: string, limit = 50): Promise<{ items: HistoryItem[] }> {
  return invoke(token, { action: "list_history", limit });
}
