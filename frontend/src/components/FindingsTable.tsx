import { Fragment, useState } from "react";
import { Finding, Severity } from "../api/types";

const SEV_COLOR: Record<Severity, string> = {
  critical: "var(--negative-text)",
  high: "#B75E40",
  medium: "var(--text-secondary)",
  low: "var(--text-muted)",
  info: "var(--text-faint)",
};

const COLS = 8; // severity, 취약점, CWE, 파일, 판정, 신뢰도, 체이닝, (펼침 화살표)

function DetailRow({ f }: { f: Finding }) {
  const cross = f.cross_family === "both" ? "양 패밀리 확인" : f.cross_family === "disagree" ? "패밀리 불일치(에스컬레이션)" : null;
  const Field = ({ label, value, mono }: { label: string; value?: string; mono?: boolean }) =>
    value ? (
      <div style={{ display: "grid", gap: "2px" }}>
        <span style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>{label}</span>
        <span style={{ fontFamily: mono ? "var(--font-mono)" : "inherit", whiteSpace: "pre-wrap", color: "var(--text-primary)" }}>
          {value}
        </span>
      </div>
    ) : null;
  return (
    <tr>
      <td colSpan={COLS} style={{ padding: "var(--space-4) var(--space-6)", background: "var(--surface-sunken)", borderTop: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "grid", gap: "var(--space-3)", maxWidth: 900 }}>
          <Field label="위치" value={`${f.file_path}:${f.line_range[0]}-${f.line_range[1]}`} mono />
          <Field label="설명" value={f.description} />
          <Field label="악용 시나리오" value={f.exploitation_scenario} />
          <Field label="패치 제안" value={f.patch_suggestion} />
          <div style={{ display: "flex", gap: "var(--space-4)", fontSize: "var(--text-sm)", color: "var(--text-secondary)", flexWrap: "wrap" }}>
            <span>{f.cwe_id ?? "CWE 미상"}</span>
            <span>신뢰도 {Math.round(f.confidence * 100)}%</span>
            <span>판정 {f.verdict ?? "—"}</span>
            {f.chain_potential && <span>체이닝 가능</span>}
            {cross && <span>🤝 {cross}</span>}
          </div>
        </div>
      </td>
    </tr>
  );
}

export function FindingsTable({ findings }: { findings?: Finding[] }) {
  const list = findings ?? []; // IN_PROGRESS records carry an empty report → no findings yet
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "var(--space-4) var(--space-5)", borderBottom: "1px solid var(--border-subtle)" }}>
        <strong>발견된 취약점 ({list.length})</strong>
        <span style={{ marginInlineStart: "var(--space-3)", fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
          행을 클릭하면 상세(설명·악용 시나리오·패치)가 펼쳐집니다
        </span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-sm)" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--text-secondary)" }}>
            {["심각도", "취약점", "CWE", "파일", "판정", "신뢰도", "체이닝", ""].map((h, i) => (
              <th key={i} style={{ padding: "var(--space-2) var(--space-5)", fontSize: "var(--text-xs)" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {list.map((f) => {
            const isOpen = open === f.id;
            return (
              <Fragment key={f.id}>
                <tr
                  onClick={() => setOpen(isOpen ? null : f.id)}
                  style={{ borderTop: "1px solid var(--border-subtle)", cursor: "pointer", background: isOpen ? "var(--brand-subtle)" : undefined }}
                >
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
                  <td style={{ ...cell, color: "var(--text-muted)" }}>{isOpen ? "▾" : "▸"}</td>
                </tr>
                {isOpen && <DetailRow f={f} />}
              </Fragment>
            );
          })}
          {list.length === 0 && (
            <tr>
              <td colSpan={COLS} style={{ ...cell, color: "var(--text-muted)", textAlign: "center" }}>
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
