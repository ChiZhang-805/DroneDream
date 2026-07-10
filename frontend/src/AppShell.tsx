import { Link, NavLink, Outlet, matchPath, useLocation } from "react-router-dom";

import { useI18n } from "./i18n/I18nProvider";
import type { TranslationKey } from "./i18n/I18nProvider";

const NAV_ITEMS: {
  to: string;
  labelKey?: TranslationKey;
  label?: string;
  end?: boolean;
}[] = [
  { to: "/", labelKey: "app.dashboard", end: true },
  { to: "/jobs/new", labelKey: "app.newExperiment" },
  { to: "/batches/new", labelKey: "app.newBatch", end: true },
  { to: "/batches", labelKey: "app.batches", end: true },
  { to: "/history", labelKey: "app.history" },
  { to: "/ece498", label: "ECE498" },
];

export function AppShell() {
  const location = useLocation();
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <Link to="/" className="app-title">
          <span className="app-title-mark" aria-hidden="true">◆</span>
          <span>DroneDream</span>
        </Link>
        <nav className="app-nav" aria-label={t("app.primaryNav")}>
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
                {item.labelKey ? t(item.labelKey) : item.label}
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
          <div className="app-header-title">DroneDream — {t("app.platform")}</div>
          <div className="app-header-meta">
            <span className="env-chip">live API</span>
            <label className="language-switcher">
              <span className="sr-only">{t("app.language")}</span>
              <select
                aria-label={t("app.language")}
                value={locale}
                onChange={(event) =>
                  setLocale(event.target.value === "zh-CN" ? "zh-CN" : "en")
                }
              >
                <option value="en">EN</option>
                <option value="zh-CN">中文</option>
              </select>
            </label>
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
