import { useRef, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { getScan, scan, scanAsync } from "../api/agentcore";
import { ScanResult } from "../api/types";
import { ScanForm, ScanFormValue } from "../components/ScanForm";
import { ResultView } from "./ResultView";

export function ScanPage() {
  const { getToken } = useAuth();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);

  function stopPoll() {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function run({ req, async: isAsync }: ScanFormValue) {
    setError("");
    setBusy(true);
    setResult(null);
    stopPoll();
    try {
      const token = await getToken();
      if (!isAsync) {
        const res = await scan(token, req);
        setResult(res);
        setBusy(false);
        return;
      }
      const started = await scanAsync(token, req);
      setResult(started);
      // poll get_scan until done/error
      pollRef.current = window.setInterval(async () => {
        try {
          const t = await getToken();
          const { scan: item } = await getScan(t, started.scanId);
          if (!item) return;
          setResult({
            scanId: item.scanId,
            status: item.status as ScanResult["status"],
            summary: item.summary,
            report: item.report,
            gate: item.gate,
            currentPhase: (item as unknown as { currentPhase?: string }).currentPhase,
            error: (item as unknown as { error?: string }).error,
          });
          if (item.status === "done" || item.status === "error") {
            stopPoll();
            setBusy(false);
          }
        } catch {
          /* transient — keep polling */
        }
      }, 6000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "스캔 실패");
      setBusy(false);
    }
  }

  const done = result?.status === "done";

  return (
    <div style={{ display: "grid", gap: "var(--space-6)" }}>
      <div>
        <h1 style={{ fontSize: "var(--text-xl)", letterSpacing: "var(--tracking-tight)" }}>
          AI 보안 스캐닝 대시보드
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: "var(--space-1)" }}>
          Strands Agents · Amazon Bedrock AgentCore 기반 국내 금융사 자율 보안 스캐닝 파이프라인
        </p>
      </div>
      <ScanForm busy={busy} onSubmit={run} />
      {error && <div style={{ color: "var(--negative-text)" }}>{error}</div>}
      {result && (
        <ResultView
          summary={result.summary}
          report={result.report}
          gate={result.gate}
          coverage={result.coverage}
          done={!!done}
          currentPhase={result.currentPhase}
          error={result.error}
        />
      )}
    </div>
  );
}
