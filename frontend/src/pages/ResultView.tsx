import { ScanReport, ScanSummary as Summary, Gate } from "../api/types";
import { PipelineProgress } from "../components/PipelineProgress";
import { ScanSummaryCards } from "../components/ScanSummary";
import { CicdGate } from "../components/CicdGate";
import { FindingsTable } from "../components/FindingsTable";

export function ResultView({
  summary,
  report,
  gate,
  done,
  currentPhase,
  error,
}: {
  summary?: Summary;
  report?: ScanReport;
  gate?: Gate;
  done: boolean;
  currentPhase?: string;
  error?: string;
}) {
  return (
    <div style={{ display: "grid", gap: "var(--space-6)" }}>
      {error && (
        <div
          className="card"
          style={{
            padding: "var(--space-4) var(--space-5)",
            borderLeft: "4px solid var(--negative)",
            color: "var(--negative-text)",
          }}
        >
          스캔 실패: {error}
        </div>
      )}
      <PipelineProgress done={done} currentPhase={currentPhase} />
      {gate && <CicdGate gate={gate} />}
      {summary && <ScanSummaryCards summary={summary} />}
      {report && <FindingsTable findings={report.findings} />}
    </div>
  );
}
