import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { getScan, listHistory } from "../api/agentcore";
import { HistoryItem } from "../api/types";
import { ResultView } from "./ResultView";

export function HistoryPage() {
  const { getToken } = useAuth();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [selected, setSelected] = useState<HistoryItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = await getToken();
      const { items } = await listHistory(token);
      setItems(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "이력 조회 실패");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function view(scanId: string) {
    const token = await getToken();
    const { scan } = await getScan(token, scanId);
    if (scan) setSelected(scan);
  }

  if (selected) {
    return (
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        <button
          onClick={() => setSelected(null)}
          style={{ justifySelf: "start", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "var(--space-1) var(--space-3)" }}
        >
          ← 이력으로
        </button>
        <ResultView summary={selected.summary} report={selected.report} gate={selected.gate} done />
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ fontSize: "var(--text-xl)" }}>스캔 이력 ({items.length})</h1>
        <button className="btn-primary" onClick={refresh} disabled={loading}>
          {loading ? "불러오는 중…" : "새로고침"}
        </button>
      </div>
      {error && <div style={{ color: "var(--negative-text)" }}>{error}</div>}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-sm)" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--text-secondary)" }}>
              {["실행 시각", "상태", "대상", "확정", "Critical", "High", "설정", ""].map((h) => (
                <th key={h} style={{ padding: "var(--space-2) var(--space-5)", fontSize: "var(--text-xs)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.scanId} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                <td style={cell}>{new Date(it.createdAt).toLocaleString("ko-KR")}</td>
                <td style={cell}>{it.status}</td>
                <td style={{ ...cell, fontFamily: "var(--font-mono)" }}>{it.projectPath}</td>
                <td style={cell}>{it.summary?.total_findings ?? "—"}</td>
                <td style={cell}>{it.summary?.critical ?? "—"}</td>
                <td style={cell}>{it.summary?.high ?? "—"}</td>
                <td style={cell}>파일 {it.maxFiles} · pass@{it.passAtK}</td>
                <td style={cell}>
                  <button
                    onClick={() => view(it.scanId)}
                    style={{ background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", padding: "2px var(--space-3)" }}
                  >
                    결과 보기
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && !loading && (
              <tr>
                <td colSpan={8} style={{ ...cell, textAlign: "center", color: "var(--text-muted)" }}>
                  스캔 이력이 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const cell: React.CSSProperties = { padding: "var(--space-2) var(--space-5)" };
