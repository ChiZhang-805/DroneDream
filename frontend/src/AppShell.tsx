import { Link, NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/jobs/new", label: "New Job" },
  { to: "/history", label: "History / Reports" },
];

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <Link to="/" className="app-title">
          <span className="app-title-mark">◆</span>
          <span>DroneDream</span>
        </Link>
        <nav className="app-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="app-sidebar-footer">
          <span className="phase-pill">Phase 1 · Mock Data</span>
        </div>
      </aside>
      <div className="app-body">
        <header className="app-header">
          <div className="app-header-title">DroneDream MVP</div>
          <div className="app-header-meta">
            <span className="env-chip">mock API</span>
          </div>
        </header>
        <main className="app-main">
          <Outlet />
        </main>
        <footer className="app-footer">
          Phase 1 frontend skeleton · all data is mocked · real backend wired in Phase 2
        </footer>
      </div>
    </div>
  );
}
