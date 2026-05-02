import { Link, NavLink, Outlet, matchPath, useLocation } from "react-router-dom";
import { useState } from "react";
import { clearDemoAuthToken, getDemoAuthToken, setDemoAuthToken } from "./api/client";

const NAV_ITEMS: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/jobs/new", label: "New Job" },
  { to: "/batches/new", label: "New Batch", end: true },
  { to: "/batches", label: "Batches", end: true },
  { to: "/history", label: "History / Reports" },
  { to: "/ece498", label: "ECE498" },
];

export function AppShell() {
  const requireDemoToken = import.meta.env.VITE_REQUIRE_DEMO_AUTH_TOKEN === "true";
  const [tokenInput, setTokenInput] = useState("");
  const [savedToken, setSavedToken] = useState<string | null>(getDemoAuthToken());
  const location = useLocation();

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <Link to="/" className="app-title">
          <span className="app-title-mark">◆</span>
          <span>DroneDream</span>
        </Link>
        <nav className="app-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => {
            const isBatchesItem = item.to === "/batches";
            const isBatchesActive =
              isBatchesItem &&
              location.pathname !== "/batches/new" &&
              (Boolean(matchPath("/batches", location.pathname)) ||
                Boolean(matchPath("/batches/:batchId", location.pathname)));

            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => {
                  if (isBatchesItem) {
                    return isBatchesActive ? "active" : undefined;
                  }
                  return isActive ? "active" : undefined;
                }}
              >
                {item.label}
              </NavLink>
            );
          })}
        </nav>
        <div className="app-sidebar-footer">
          <span className="phase-pill">DroneDream V1.0</span>
        </div>
      </aside>
      <div className="app-body">
        <header className="app-header">
          <div className="app-header-title">DroneDream —— Auto Parameter Tuning Platform</div>
          <div className="app-header-meta">
            <span className="env-chip">live API</span>
            {requireDemoToken ? (
              <div>
                <input
                  placeholder="Access token"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                />
                <button type="button" onClick={() => { setDemoAuthToken(tokenInput); setSavedToken(getDemoAuthToken()); setTokenInput(""); }}>
                  Save Token
                </button>
                {savedToken ? <button type="button" onClick={() => { clearDemoAuthToken(); setSavedToken(null); }}>Clear</button> : null}
              </div>
            ) : null}
          </div>
        </header>
        <main className="app-main">
          <Outlet />
        </main>
        <footer className="app-footer">
          <div className="app-footer-content">
            <span>Author: Chi Zhang</span>
            <span>Contact: cz005623@gmail.com</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
