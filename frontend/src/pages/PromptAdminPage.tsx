// ADR-001 admin UI: view/edit/version/preview/activate the four editable agent SYSTEM
// prompts. Admin-only (gated in Shell by useAuth().isAdmin; the backend re-enforces RBAC).
// All prompt bodies/diffs render as plain text in <pre> (React escapes them) — never
// dangerouslySetInnerHTML — so a malicious stored body cannot inject markup.
import { useCallback, useEffect, useState } from "react";
import {
  AgentKey,
  activatePrompt,
  createPromptVersion,
  listPrompts,
  previewPrompt,
} from "../api/agentcore";
import { PromptVersion } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const AGENTS: { key: AgentKey; label: string }[] = [
  { key: "ranker", label: "Ranker (위험 랭킹)" },
  { key: "hunter", label: "Hunter (취약점 헌트)" },
  { key: "challenger", label: "Challenger (반박)" },
  { key: "validator", label: "Validator (최종 검증)" },
];

const box: React.CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: "var(--space-3)",
  background: "var(--surface-raised)",
};

const pre: React.CSSProperties = {
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  fontFamily: "var(--font-mono, monospace)",
  fontSize: "var(--text-sm)",
  background: "var(--surface-sunken)",
  padding: "var(--space-3)",
  borderRadius: "var(--radius-sm)",
  maxHeight: 320,
  overflow: "auto",
  margin: 0,
};

export function PromptAdminPage() {
  const { getToken } = useAuth();
  const [agent, setAgent] = useState<AgentKey>("hunter");
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [selected, setSelected] = useState<PromptVersion | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [rendered, setRendered] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(
    async (a: AgentKey) => {
      setErr(null);
      setRendered(null);
      try {
        const token = await getToken();
        const res = await listPrompts(token, a);
        if (res.status !== "ok") throw new Error(res.error || "조회 실패");
        setVersions(res.versions || []);
        setActive(res.active ?? null);
        const cur = (res.versions || []).find((v) => v.version === res.active) || null;
        setSelected(cur);
      } catch (e) {
        setErr((e as Error).message);
        setVersions([]);
        setActive(null);
        setSelected(null);
      }
    },
    [getToken],
  );

  useEffect(() => {
    void refresh(agent);
  }, [agent, refresh]);

  function pick(v: PromptVersion) {
    setSelected(v);
    setRendered(null);
    setMsg(null);
  }

  async function onCreate() {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const token = await getToken();
      const res = await createPromptVersion(token, agent, draft, note);
      if (res.status !== "ok") throw new Error(res.error || "생성 실패");
      setMsg(`v${res.version} 생성됨 — 활성화하려면 먼저 미리보기/검증하세요.`);
      setDraft("");
      setNote("");
      await refresh(agent);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onPreview(v: PromptVersion) {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const token = await getToken();
      const res = await previewPrompt(token, agent, v.version);
      if (res.status !== "ok") throw new Error(res.error || "검증 실패");
      setRendered(res.rendered || "");
      setMsg(`v${v.version} 검증 통과 — 이제 활성화할 수 있습니다.`);
      await refresh(agent);
      setSelected(v);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onActivate(v: PromptVersion) {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const token = await getToken();
      const res = await activatePrompt(token, agent, v.version);
      if (res.status !== "ok") throw new Error(res.error || "활성화 실패");
      setMsg(`v${v.version} 활성화됨 (롤백도 동일 동작).`);
      await refresh(agent);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-4)", maxWidth: 1100 }}>
      <header>
        <h1 style={{ fontSize: "var(--text-lg)", margin: 0 }}>프롬프트 관리</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: "var(--text-sm)" }}>
          편집 대상은 각 에이전트의 system 프롬프트 본문뿐입니다. 인젝션 방어 골격(nonce 래핑)과
          고정 안전 지침은 코드에 고정되어 편집할 수 없습니다. 활성 버전은 다음 스캔 생성 시점에
          고정(pin)되어 진행 중 스캔에는 영향을 주지 않습니다.
        </p>
      </header>

      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
        {AGENTS.map((a) => (
          <button
            key={a.key}
            onClick={() => setAgent(a.key)}
            style={{
              padding: "var(--space-2) var(--space-3)",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-subtle)",
              background: agent === a.key ? "var(--brand-subtle)" : "transparent",
              color: agent === a.key ? "var(--brand-text)" : "var(--text-primary)",
              fontWeight: agent === a.key ? "var(--weight-medium)" : "var(--weight-regular)",
            }}
          >
            {a.label}
          </button>
        ))}
      </div>

      {err && (
        <div style={{ ...box, borderColor: "var(--danger-border, #E11D48)", color: "var(--danger-text, #9F1239)" }}>
          {err}
        </div>
      )}
      {msg && <div style={{ ...box, borderColor: "var(--brand-border, #D97757)" }}>{msg}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 320px) 1fr", gap: "var(--space-4)" }}>
        {/* version list */}
        <section style={box}>
          <h2 style={{ fontSize: "var(--text-md)", marginTop: 0 }}>
            버전 ({versions.length}) · 활성: {active != null ? `v${active}` : "코드 기본값"}
          </h2>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "var(--space-1)" }}>
            {versions.length === 0 && (
              <li style={{ color: "var(--text-secondary)", fontSize: "var(--text-sm)" }}>
                저장된 버전 없음 — 현재 코드 기본 프롬프트가 사용됩니다.
              </li>
            )}
            {versions
              .slice()
              .reverse()
              .map((v) => (
                <li key={v.version}>
                  <button
                    onClick={() => pick(v)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "var(--space-2)",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--border-subtle)",
                      background:
                        selected?.version === v.version ? "var(--brand-subtle)" : "transparent",
                    }}
                  >
                    <strong>v{v.version}</strong>
                    {v.version === active && " · 활성"}
                    {v.validatedHash && v.validatedHash === v.hash ? " · ✅검증" : " · 미검증"}
                    <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
                      {v.author} · {v.createdAt?.slice(0, 19)}
                    </div>
                  </button>
                </li>
              ))}
          </ul>
        </section>

        {/* detail + actions */}
        <section style={{ display: "grid", gap: "var(--space-3)" }}>
          {selected && (
            <div style={box}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h2 style={{ fontSize: "var(--text-md)", margin: 0 }}>
                  v{selected.version} {selected.note ? `— ${selected.note}` : ""}
                </h2>
                <div style={{ display: "flex", gap: "var(--space-2)" }}>
                  <button disabled={busy} onClick={() => onPreview(selected)}>
                    미리보기/검증
                  </button>
                  <button
                    disabled={busy || selected.validatedHash !== selected.hash}
                    title={
                      selected.validatedHash !== selected.hash
                        ? "활성화 전에 미리보기/검증이 필요합니다"
                        : ""
                    }
                    onClick={() => onActivate(selected)}
                  >
                    {selected.version === active ? "재활성화" : "활성화 / 롤백"}
                  </button>
                  <button onClick={() => setDraft(selected.body)}>이 버전으로 편집 시작</button>
                </div>
              </div>
              <pre style={pre}>{selected.body}</pre>
            </div>
          )}

          {rendered != null && (
            <div style={box}>
              <h3 style={{ fontSize: "var(--text-sm)", marginTop: 0 }}>
                미리보기 (모델이 실제로 보는 프롬프트 — 안전 preamble + nonce 펜스 포함)
              </h3>
              <pre style={pre}>{rendered}</pre>
            </div>
          )}

          {/* editor → new version */}
          <div style={box}>
            <h3 style={{ fontSize: "var(--text-sm)", marginTop: 0 }}>새 버전 작성</h3>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="에이전트 system 프롬프트 본문…"
              rows={10}
              style={{ width: "100%", fontFamily: "var(--font-mono, monospace)", fontSize: "var(--text-sm)" }}
            />
            <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="변경 메모 (선택, ≤500자)"
                maxLength={500}
                style={{ flex: 1 }}
              />
              <button disabled={busy || !draft.trim()} onClick={onCreate}>
                새 버전 생성
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
