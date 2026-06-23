export type Route = "scan" | "history" | "prompts";

export function Sidebar({
  route,
  onNavigate,
  isAdmin = false,
}: {
  route: Route;
  onNavigate: (r: Route) => void;
  isAdmin?: boolean;
}) {
  const items: { key: Route; label: string }[] = [
    { key: "scan", label: "새 스캔" },
    { key: "history", label: "스캔 이력" },
    ...(isAdmin ? [{ key: "prompts" as Route, label: "프롬프트 관리" }] : []),
  ];
  return (
    <nav
      style={{
        width: "var(--sidebar-w)",
        background: "var(--surface-sunken)",
        borderRight: "1px solid var(--border-subtle)",
        padding: "var(--space-6) var(--space-4)",
      }}
    >
      <h2 style={{ fontSize: "var(--text-md)", marginBottom: "var(--space-4)" }}>FSI-Mythos</h2>
      <ul style={{ listStyle: "none", display: "grid", gap: "var(--space-1)" }}>
        {items.map((it) => {
          const active = route === it.key;
          return (
            <li key={it.key}>
              <button
                onClick={() => onNavigate(it.key)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "var(--space-2) var(--space-3)",
                  borderRadius: "var(--radius-md)",
                  border: "none",
                  background: active ? "var(--brand-subtle)" : "transparent",
                  color: active ? "var(--brand-text)" : "var(--text-primary)",
                  fontWeight: active ? "var(--weight-medium)" : "var(--weight-regular)",
                }}
              >
                {it.label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
