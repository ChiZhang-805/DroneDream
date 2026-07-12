import { Link, NavLink, Outlet, matchPath, useLocation } from "react-router-dom";

import { isDesktopRuntime } from "./desktop/bridge";
import {
  DesktopRuntimeAccessProvider,
  useDesktopRuntimeAccess,
} from "./desktop/access";
import { useI18n } from "./i18n/I18nProvider";
import type { TranslationKey } from "./i18n/I18nProvider";

const NAV_ITEMS: {
  to: string;
  labelKey?: TranslationKey;
  label?: string;
  end?: boolean;
  desktopTo?: string;
  requiresRuntime?: boolean;
}[] = [
  { to: "/", desktopTo: "/dashboard", labelKey: "app.dashboard", end: true },
  { to: "/jobs/new", labelKey: "app.newExperiment", requiresRuntime: true },
  { to: "/batches/new", labelKey: "app.newBatch", end: true, requiresRuntime: true },
  { to: "/batches", labelKey: "app.batches", end: true, requiresRuntime: true },
  { to: "/history", labelKey: "app.history" },
  { to: "/desktop/setup", labelKey: "app.desktopSetup" },
  { to: "/ece498", label: "ECE498" },
];

export function AppShell() {
  return (
    <DesktopRuntimeAccessProvider>
      <AppShellContent />
    </DesktopRuntimeAccessProvider>
  );
}

function AppShellContent() {
  const location = useLocation();
  const desktopRuntime = isDesktopRuntime();
  const runtimeAccess = useDesktopRuntimeAccess();
  const { locale, setLocale, t } = useI18n();
  const runtimeNavDescription = runtimeAccess.status === "checking"
    ? t("runtimeGate.navChecking")
    : t("runtimeGate.navLocked");

  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        {t("app.skipToContent")}
      </a>
      <aside className="app-sidebar">
        <Link to="/" className="app-title">
          <span className="app-title-mark" aria-hidden="true">◆</span>
          <span>DroneDream</span>
        </Link>
        <nav className="app-nav" aria-label={t("app.primaryNav")}>
          <span id="runtime-nav-description" className="sr-only">
            {runtimeNavDescription}
          </span>
          {NAV_ITEMS.map((item) => {
            const destination = desktopRuntime && item.desktopTo
              ? item.desktopTo
              : item.to;
            const runtimeLocked = Boolean(
              desktopRuntime &&
              item.requiresRuntime &&
              runtimeAccess.status !== "ready",
            );
            const isBatchesItem = destination === "/batches";
            const isBatchesActive =
              isBatchesItem &&
              location.pathname !== "/batches/new" &&
              (Boolean(matchPath("/batches", location.pathname)) ||
                Boolean(matchPath("/batches/:batchId", location.pathname)));

            return (
              <NavLink
                key={item.to}
                to={destination}
                end={item.end}
                title={runtimeLocked ? runtimeNavDescription : undefined}
                aria-describedby={runtimeLocked ? "runtime-nav-description" : undefined}
                className={({ isActive }) => {
                  const classes = runtimeLocked ? ["runtime-locked"] : [];
                  if (isBatchesItem) {
                    if (isBatchesActive) classes.push("active");
                    return classes.length > 0 ? classes.join(" ") : undefined;
                  }
                  if (isActive) classes.push("active");
                  return classes.length > 0 ? classes.join(" ") : undefined;
                }}
              >
                <span>{item.labelKey ? t(item.labelKey) : item.label}</span>
                {runtimeLocked ? (
                  <span className="nav-runtime-badge" aria-hidden="true">
                    {runtimeAccess.status === "checking"
                      ? t("runtimeGate.checkingShort")
                      : `🔒 ${t("runtimeGate.requiredShort")}`}
                  </span>
                ) : null}
              </NavLink>
            );
          })}
        </nav>
        <div className="app-sidebar-footer">
          <span className="phase-pill">{t("app.previewVersion")}</span>
        </div>
      </aside>
      <div className="app-body">
        <header className="app-header">
          <div className="app-header-title">DroneDream — {t("app.platform")}</div>
          <div className="app-header-meta">
            <span className="env-chip">
              {desktopRuntime ? t("app.desktopEnvironment") : t("app.webEnvironment")}
            </span>
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
        <main id="main-content" className="app-main" tabIndex={-1}>
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
