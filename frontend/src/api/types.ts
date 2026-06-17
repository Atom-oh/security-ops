export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Verdict = "confirmed" | "likely" | "dismissed" | "escalate";

export interface Finding {
  id: string;
  title: string;
  file_path: string;
  line_range: [number, number];
  severity: Severity;
  cwe_id: string | null;
  description: string;
  exploitation_scenario: string;
  patch_suggestion: string;
  confidence: number;
  chain_potential: boolean;
  verdict: Verdict | null;
  validated: boolean;
}

export interface ScanSummary {
  total_findings: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  chaining: number;
  gate_status: "BLOCKED" | "PASSED";
}

export interface Gate {
  status: "BLOCKED" | "PASSED";
  blocked: number;
  info: number;
  reasons: string[];
}

export interface ScanReport {
  total_findings: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
  chaining: number;
  findings: Finding[];
  asff?: unknown[];
}

export interface ScanResult {
  scanId: string;
  status: "done" | "IN_PROGRESS" | "error";
  summary?: ScanSummary;
  report?: ScanReport;
  gate?: Gate;
  currentPhase?: string;
  error?: string;
}

export interface HistoryItem {
  userId: string;
  scanId: string;
  createdAt: string;
  projectPath: string;
  maxFiles: number;
  passAtK: number;
  status: string;
  summary?: ScanSummary;
  report?: ScanReport;
  gate?: Gate;
}

export interface ScanRequest {
  project_path?: string;
  max_files?: number;
  pass_at_k?: number;
  hunter_model?: string;
  challenger_model?: string;
  validator_model?: string;
  ranker_model?: string;
  sandbox_enabled?: boolean;
  upload?: { files: { path: string; content_b64: string }[] };
}
