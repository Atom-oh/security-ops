import { Gate } from "../api/types";

// Older / IN_PROGRESS records may lack some gate fields — never assume they're present.
const LABEL: Record<string, string> = {
  BLOCKED: "❌ 배포 차단 (BLOCKED)",
  INCOMPLETE: "⚠️ 커버리지 부족 (INCOMPLETE)",
  PASSED: "✅ 배포 허용 (PASSED)",
};

export function CicdGate({ gate }: { gate: Gate }) {
  const status = gate.status ?? "PASSED";
  const reasons = gate.reasons ?? [];
  const bad = status === "BLOCKED" || status === "INCOMPLETE";
  const color = status === "BLOCKED" ? "var(--negative)" : status === "INCOMPLETE" ? "#B75E40" : "var(--positive)";
  return (
    <div className="card" style={{ padding: "var(--space-4) var(--space-5)", borderLeft: `4px solid ${color}` }}>
      <div style={{ fontWeight: "var(--weight-semibold)", color: bad ? "var(--negative-text)" : "var(--positive-text)" }}>
        {LABEL[status] ?? status}
      </div>
      <div style={{ fontSize: "var(--text-sm)", color: "var(--text-secondary)", marginTop: "var(--space-1)" }}>
        차단 {gate.blocked ?? 0}건 · 참고 {gate.info ?? 0}건 · Critical/High/체이닝 취약점은 자동 차단됩니다.
      </div>
      {reasons.length > 0 && (
        <ul style={{ marginTop: "var(--space-2)", paddingLeft: "var(--space-5)", fontSize: "var(--text-sm)" }}>
          {reasons.slice(0, 8).map((r, i) => (
            <li key={i} style={{ color: "var(--text-secondary)" }}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
