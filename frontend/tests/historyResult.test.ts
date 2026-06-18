import assert from "node:assert/strict";
import { historyItemToScanResult, isTerminalScanStatus } from "../src/pages/historyResult";
import type { HistoryItem } from "../src/api/types";

const base: HistoryItem = {
  userId: "u1",
  scanId: "s1",
  createdAt: "2026-06-18T00:00:00Z",
  projectPath: "/app/sample-target",
  maxFiles: 3,
  passAtK: 1,
  status: "IN_PROGRESS",
};

const progress = historyItemToScanResult({
  ...base,
  currentPhase: "Phase 3 · 에이전틱 헌트",
});

assert.equal(progress.scanId, "s1");
assert.equal(progress.status, "IN_PROGRESS");
assert.equal(progress.currentPhase, "Phase 3 · 에이전틱 헌트");
assert.equal(isTerminalScanStatus(progress.status), false);

assert.equal(isTerminalScanStatus("done"), true);
assert.equal(isTerminalScanStatus("error"), true);
