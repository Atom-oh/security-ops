import { ScanReport, ScanSummary as Summary, Gate, Coverage } from "../api/types";
import { PipelineProgress } from "../components/PipelineProgress";
import { ScanSummaryCards } from "../components/ScanSummary";
import { CicdGate } from "../components/CicdGate";
import { FindingsTable } from "../components/FindingsTable";

function CoverageBar({ c }: { c: Coverage }) {
  return (
    <div
      className="card"
      style={{ padding: "var(--space-3) var(--space-5)", fontSize: "var(--text-sm)", color: "var(--text-secondary)" }}
    >
      📊 커버리지: 전체 코드파일 <b>{c.total_code_files}</b>개 중 <b>{c.scanned_files}</b>개 심층 스캔
      {c.unscanned_files > 0 ? ` · 미스캔 ${c.unscanned_files}개` : ""}
      {c.dropped_over_budget > 0 ? ` · 예산초과 제외 ${c.dropped_over_budget}개` : ""}
      {c.secret_prefilter_findings > 0 ? ` · 시크릿 사전탐지 ${c.secret_prefilter_findings}건` : ""}
      {c.unscanned_files > 0 && (
        <span style={{ color: "var(--text-muted)" }}> — 전체 감사가 아닌 위험도 상위 샘플입니다.</span>
      )}
    </div>
  );
}

export function ResultView({
  summary,
  report,
  gate,
  coverage,
  done,
  currentPhase,
  currentDetail,
  error,
}: {
  summary?: Summary;
  report?: ScanReport;
  gate?: Gate;
  coverage?: Coverage;
  done: boolean;
  currentPhase?: string;
  currentDetail?: string;
  error?: string;
}) {
  // IN_PROGRESS records persist empty objects ({}); treat those as "no data yet" so we don't
  // render a summary/findings table over undefined fields (which crashes on .length).
  const hasSummary = summary && typeof summary.total_findings === "number";
  const hasReport = report && Array.isArray(report.findings);
  const hasGate = gate && typeof gate.status === "string";
  const covRaw = coverage ?? summary?.coverage;
  const cov = covRaw && typeof covRaw.total_code_files === "number" ? covRaw : undefined;
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
      <PipelineProgress done={done} currentPhase={currentPhase} currentDetail={currentDetail} />
      {cov && <CoverageBar c={cov} />}
      {hasGate && <CicdGate gate={gate!} />}
      {hasSummary && <ScanSummaryCards summary={summary!} />}
      {hasReport && <FindingsTable findings={report!.findings} />}
    </div>
  );
}
