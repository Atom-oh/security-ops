import { useEffect, useState } from "react";
import { Header } from "./Header";
import { Route, Sidebar } from "./Sidebar";
import { ScanPage } from "../pages/ScanPage";
import { HistoryPage } from "../pages/HistoryPage";

function routeFromHash(): Route {
  return window.location.hash.replace("#", "") === "history" ? "history" : "scan";
}

export function Shell() {
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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Header />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <Sidebar route={route} onNavigate={navigate} />
        <main style={{ flex: 1, overflow: "auto", padding: "var(--page-pad)" }}>
          {route === "scan" ? <ScanPage /> : <HistoryPage />}
        </main>
      </div>
    </div>
  );
}
