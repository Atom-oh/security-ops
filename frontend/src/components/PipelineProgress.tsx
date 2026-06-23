export const PHASES = [
  "Phase 0 · 언어 감지",
  "Phase 1 · 싱크 슬라이싱",
  "Phase 2 · 파일 랭킹",
  "Phase 3 · 에이전틱 헌트",
  "Phase 3.5 · 적대적 자기도전",
  "Phase 4 · 회의적 검증",
  "Phase 6 · 집계/보고",
  "Phase 7 · FP 메모리",
];

export function PipelineProgress({
  done,
  currentPhase,
  currentDetail,
}: {
  done: boolean;
  currentPhase?: string;
  currentDetail?: string;
}) {
  const activeIdx = done ? PHASES.length : Math.max(0, PHASES.indexOf(currentPhase ?? ""));
  return (
    <div className="card" style={{ padding: "var(--space-6)" }}>
      <h2 style={{ fontSize: "var(--text-lg)", marginBottom: "var(--space-1)" }}>파이프라인 진행 상황</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: "var(--text-sm)", marginBottom: "var(--space-4)" }}>
        {done ? "스캔 완료" : "스캔 진행 중…"}
      </p>
      <ol style={{ listStyle: "none", display: "grid", gap: "var(--space-2)" }}>
        {PHASES.map((p, i) => {
          const complete = done || i < activeIdx;
          const active = !done && i === activeIdx;
          return (
            <li
              key={p}
              style={{
                padding: "var(--space-2) var(--space-3)",
                borderRadius: "var(--radius-md)",
                background: active ? "var(--brand-subtle)" : "transparent",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontWeight: active ? "var(--weight-medium)" : "var(--weight-regular)" }}>{p}</span>
                <span style={{ fontSize: "var(--text-xs)", color: complete ? "var(--positive-text)" : "var(--text-muted)" }}>
                  {complete ? "완료" : active ? "진행 중" : "대기"}
                </span>
              </div>
              {/* live per-phase detail (e.g. detected languages, files chosen to scan, current hunt target) */}
              {active && currentDetail && (
                <div style={{ marginTop: "2px", fontSize: "var(--text-xs)", color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                  ↳ {currentDetail}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
