import { Link, NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/jobs/new", label: "New Job" },
  { to: "/batches/new", label: "New Batch" },
  { to: "/batches", label: "Batches" },
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
          <span className="phase-pill">DroneDream V1.0</span>
        </div>
      </aside>
      <div className="app-body">
        <header className="app-header">
          <div className="app-header-title">DreamDrone —— Auto Parameter Tuning Platform</div>
          <div className="app-header-meta">
            <span className="env-chip">live API</span>
          </div>
        </header>
        <main className="app-main">
          <Outlet />
        </main>
        <footer className="app-footer">
          Author: Chi Zhang    Contact: cz005623@gmail.com
        </footer>
      </div>
    </div>
  );
}
