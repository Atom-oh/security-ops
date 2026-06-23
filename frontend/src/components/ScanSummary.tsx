import { ScanSummary as Summary } from "../api/types";

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="card" style={{ padding: "var(--space-4)", textAlign: "center" }}>
      <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>{label}</div>
      <div
        className="tnum"
        style={{
          fontSize: "var(--text-2xl)",
          fontWeight: "var(--weight-semibold)",
          color: accent ? "var(--brand-text)" : "var(--text-primary)",
          letterSpacing: "var(--tracking-tight)",
        }}
      >
        {value}
      </div>
    </div>
  );
}

export function ScanSummaryCards({ summary }: { summary: Summary }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "var(--grid-gap)" }}>
      <Stat label="확인된 취약점" value={summary.total_findings} accent />
      <Stat label="Critical" value={summary.critical} />
      <Stat label="High" value={summary.high} />
      <Stat label="Medium" value={summary.medium} />
      <Stat label="Low" value={summary.low} />
      <Stat label="체이닝 가능" value={summary.chaining} />
    </div>
  );
}
