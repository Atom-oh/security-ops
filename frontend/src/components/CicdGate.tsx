import { Gate } from "../api/types";

export function CicdGate({ gate }: { gate: Gate }) {
  const blocked = gate.status === "BLOCKED";
  return (
    <div
      className="card"
      style={{
        padding: "var(--space-4) var(--space-5)",
        borderLeft: `4px solid ${blocked ? "var(--negative)" : "var(--positive)"}`,
      }}
    >
      <div style={{ fontWeight: "var(--weight-semibold)", color: blocked ? "var(--negative-text)" : "var(--positive-text)" }}>
        {blocked ? "❌ 배포 차단 (BLOCKED)" : "✅ 배포 허용 (PASSED)"}
      </div>
      <div style={{ fontSize: "var(--text-sm)", color: "var(--text-secondary)", marginTop: "var(--space-1)" }}>
        차단 {gate.blocked}건 · 참고 {gate.info}건 · Critical/High/체이닝 취약점은 자동 차단됩니다.
      </div>
      {gate.reasons.length > 0 && (
        <ul style={{ marginTop: "var(--space-2)", paddingLeft: "var(--space-5)", fontSize: "var(--text-sm)" }}>
          {gate.reasons.slice(0, 8).map((r, i) => (
            <li key={i} style={{ color: "var(--text-secondary)" }}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
