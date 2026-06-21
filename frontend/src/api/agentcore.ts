// Calls the AgentCore Runtime data-plane /invocations endpoint directly from the browser,
// authorized by the Cognito ACCESS token (Bearer). The JWT authorizer on the runtime
// validates the token's client_id claim.
import { config } from "../config";
import {
  HistoryItem,
  PromptActivateResponse,
  PromptCreateResponse,
  PromptListResponse,
  PromptPreviewResponse,
  ScanRequest,
  ScanResult,
} from "./types";

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

// --- ADR-001 prompt admin (admin Cognito group only; backend re-enforces RBAC) ----------

export type AgentKey = "ranker" | "hunter" | "challenger" | "validator";

export function listPrompts(token: string, agentKey: AgentKey): Promise<PromptListResponse> {
  return invoke<PromptListResponse>(token, { action: "prompt_list", agentKey });
}

export function createPromptVersion(
  token: string,
  agentKey: AgentKey,
  body: string,
  note: string,
): Promise<PromptCreateResponse> {
  return invoke<PromptCreateResponse>(token, { action: "prompt_create", agentKey, body, note });
}

export function previewPrompt(
  token: string,
  agentKey: AgentKey,
  version: number,
): Promise<PromptPreviewResponse> {
  return invoke<PromptPreviewResponse>(token, { action: "prompt_preview", agentKey, version });
}

export function activatePrompt(
  token: string,
  agentKey: AgentKey,
  version: number,
): Promise<PromptActivateResponse> {
  return invoke<PromptActivateResponse>(token, { action: "prompt_activate", agentKey, version });
}
