import { Link, NavLink, Outlet } from "react-router-dom";

export function AppShell() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="app-title">
          DroneDream
        </Link>
        <nav className="app-nav">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/jobs/new">New Job</NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
      <footer className="app-footer">Phase 0 skeleton · DroneDream MVP</footer>
    </div>
  );
}
