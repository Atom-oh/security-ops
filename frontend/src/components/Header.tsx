import { useAuth } from "../auth/AuthContext";

export function Header() {
  const { email, logout } = useAuth();
  return (
    <header
      style={{
        height: 56,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 var(--space-6)",
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--surface-card)",
      }}
    >
      <strong style={{ color: "var(--brand-text)" }}>FSI-Mythos on AgentCore</strong>
      <div style={{ display: "flex", gap: "var(--space-4)", alignItems: "center" }}>
        <span style={{ fontSize: "var(--text-sm)", color: "var(--text-secondary)" }}>{email}</span>
        <button
          onClick={logout}
          style={{
            background: "transparent",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-1) var(--space-3)",
            color: "var(--text-primary)",
          }}
        >
          로그아웃
        </button>
      </div>
    </header>
  );
}
