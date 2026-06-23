import { useEffect, useState } from "react";
import { Header } from "./Header";
import { Route, Sidebar } from "./Sidebar";
import { ScanPage } from "../pages/ScanPage";
import { HistoryPage } from "../pages/HistoryPage";
import { PromptAdminPage } from "../pages/PromptAdminPage";
import { useAuth } from "../auth/AuthContext";

function routeFromHash(): Route {
  const h = window.location.hash.replace("#", "");
  return h === "history" || h === "prompts" ? (h as Route) : "scan";
}

export function Shell() {
  const { isAdmin } = useAuth();
  const [route, setRoute] = useState<Route>(routeFromHash());

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function navigate(r: Route) {
    window.location.hash = r;
    setRoute(r);
  }

  // Guard: the prompt admin page renders only for admins (the backend also re-enforces RBAC).
  const effective: Route = route === "prompts" && !isAdmin ? "scan" : route;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Header />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <Sidebar route={effective} onNavigate={navigate} isAdmin={isAdmin} />
        <main style={{ flex: 1, overflow: "auto", padding: "var(--page-pad)" }}>
          {effective === "scan" && <ScanPage />}
          {effective === "history" && <HistoryPage />}
          {effective === "prompts" && <PromptAdminPage />}
        </main>
      </div>
    </div>
  );
}
