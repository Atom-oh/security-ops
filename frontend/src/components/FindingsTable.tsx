import { Finding, Severity } from "../api/types";

const SEV_COLOR: Record<Severity, string> = {
  critical: "var(--negative-text)",
  high: "#B75E40",
  medium: "var(--text-secondary)",
  low: "var(--text-muted)",
  info: "var(--text-faint)",
};

export function FindingsTable({ findings }: { findings: Finding[] }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "var(--space-4) var(--space-5)", borderBottom: "1px solid var(--border-subtle)" }}>
        <strong>발견된 취약점 ({findings.length})</strong>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-sm)" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--text-secondary)" }}>
            {["심각도", "취약점", "CWE", "파일", "판정", "신뢰도", "체이닝"].map((h) => (
              <th key={h} style={{ padding: "var(--space-2) var(--space-5)", fontSize: "var(--text-xs)" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {findings.map((f) => (
            <tr key={f.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
              <td style={{ ...cell, color: SEV_COLOR[f.severity], fontWeight: "var(--weight-medium)" }}>
                {f.severity.toUpperCase()}
              </td>
              <td style={cell}>{f.title}</td>
              <td style={cell}>{f.cwe_id ?? "—"}</td>
              <td style={{ ...cell, fontFamily: "var(--font-mono)" }}>
                {f.file_path.split("/").pop()}:{f.line_range[0]}
              </td>
              <td style={cell}>{f.verdict ?? "—"}</td>
              <td style={{ ...cell, fontVariantNumeric: "tabular-nums" }}>{Math.round(f.confidence * 100)}%</td>
              <td style={cell}>{f.chain_potential ? "가능" : "—"}</td>
            </tr>
          ))}
          {findings.length === 0 && (
            <tr>
              <td colSpan={7} style={{ ...cell, color: "var(--text-muted)", textAlign: "center" }}>
                확인된 취약점이 없습니다.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

const cell: React.CSSProperties = { padding: "var(--space-2) var(--space-5)" };
