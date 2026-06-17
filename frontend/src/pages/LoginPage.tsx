import { FormEvent, useState } from "react";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "로그인 실패");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100%", display: "grid", placeItems: "center", padding: "var(--space-6)" }}>
      <div className="card" style={{ width: 380, padding: "var(--space-8)" }}>
        <h1 style={{ fontSize: "var(--text-xl)", letterSpacing: "var(--tracking-tight)" }}>
          FSI-Mythos 로그인
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: "var(--space-2)", fontSize: "var(--text-sm)" }}>
          국내 금융사 AI 보안 스캐닝 플랫폼
        </p>
        <form onSubmit={onSubmit} style={{ marginTop: "var(--space-6)", display: "grid", gap: "var(--space-4)" }}>
          <label style={{ display: "grid", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>이메일</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={inputStyle}
            />
          </label>
          <label style={{ display: "grid", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>비밀번호</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              style={inputStyle}
            />
          </label>
          {error && (
            <div style={{ color: "var(--negative-text)", fontSize: "var(--text-sm)" }}>{error}</div>
          )}
          <button className="btn-primary" disabled={busy} type="submit">
            {busy ? "로그인 중…" : "로그인"}
          </button>
        </form>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "var(--space-2) var(--space-3)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-card)",
  color: "var(--text-primary)",
};
