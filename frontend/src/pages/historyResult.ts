import type { HistoryItem, ScanResult } from "../api/types";

export function isTerminalScanStatus(status: string | undefined): boolean {
  return status === "done" || status === "error";
}

export function historyItemToScanResult(item: HistoryItem): ScanResult {
  return {
    scanId: item.scanId,
    status: item.status as ScanResult["status"],
    summary: item.summary,
    report: item.report,
    gate: item.gate,
    coverage: item.coverage ?? item.summary?.coverage,
    currentPhase: item.currentPhase,
    error: item.error,
  };
}
