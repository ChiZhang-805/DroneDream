import { useEffect, useRef, useState } from "react";
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
  const [launcherSettingsOpen, setLauncherSettingsOpen] = useState(false);
  const launcherSettingsButtonRef = useRef<HTMLButtonElement>(null);
  const launcherSettingsCloseRef = useRef<HTMLButtonElement>(null);
  const launcherMode = desktopRuntime && location.pathname === "/desktop/setup";
  const runtimeNavDescription = runtimeAccess.status === "checking"
    ? t("runtimeGate.navChecking")
    : t("runtimeGate.navLocked");

  useEffect(() => {
    if (!launcherSettingsOpen) return;
    const focusFrame = requestAnimationFrame(() => launcherSettingsCloseRef.current?.focus());
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setLauncherSettingsOpen(false);
      launcherSettingsButtonRef.current?.focus();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [launcherSettingsOpen]);

  if (launcherMode) {
    return (
      <div className="app-shell app-shell-launcher">
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
        <header className="launcher-chrome">
          <Link to="/desktop/setup" className="launcher-brand" aria-label="DroneDream">
            <span className="launcher-brand-mark" aria-hidden="true">
              <span />
            </span>
            <span>DroneDream</span>
          </Link>
          <div className="launcher-chrome-actions">
            <span className="launcher-runtime-indicator">
              <span aria-hidden="true" />
              {runtimeAccess.status === "checking"
                ? t("runtimeGate.checkingShort")
                : runtimeAccess.status === "ready"
                  ? t("desktop.ready")
                  : t("runtimeGate.requiredShort")}
            </span>
            <button
              ref={launcherSettingsButtonRef}
              type="button"
              className="launcher-settings-button"
              aria-label={t("app.settings")}
              aria-haspopup="dialog"
              aria-expanded={launcherSettingsOpen}
              onClick={() => setLauncherSettingsOpen(true)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 8.25A3.75 3.75 0 1 0 12 15.75 3.75 3.75 0 0 0 12 8.25Z" />
                <path d="M19.3 13.48c.04-.48.04-.96 0-1.44l1.66-1.3-1.78-3.08-1.98.8a8.2 8.2 0 0 0-1.24-.72l-.3-2.1h-3.56l-.3 2.1c-.44.2-.85.44-1.24.72l-1.98-.8-1.78 3.08 1.66 1.3a8.8 8.8 0 0 0 0 1.44l-1.66 1.3 1.78 3.08 1.98-.8c.39.28.8.52 1.24.72l.3 2.1h3.56l.3-2.1c.44-.2.85-.44 1.24-.72l1.98.8 1.78-3.08-1.66-1.3Z" />
              </svg>
            </button>
          </div>
        </header>
        {launcherSettingsOpen ? (
          <div
            className="launcher-settings-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target !== event.currentTarget) return;
              setLauncherSettingsOpen(false);
              launcherSettingsButtonRef.current?.focus();
            }}
          >
            <section
              className="launcher-settings-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="launcher-settings-title"
            >
              <div className="launcher-settings-heading">
                <div>
                  <span className="launcher-settings-kicker">DroneDream</span>
                  <h2 id="launcher-settings-title">{t("app.settingsTitle")}</h2>
                </div>
                <button
                  ref={launcherSettingsCloseRef}
                  type="button"
                  className="launcher-settings-close"
                  aria-label={t("app.closeSettings")}
                  onClick={() => {
                    setLauncherSettingsOpen(false);
                    launcherSettingsButtonRef.current?.focus();
                  }}
                >
                  <span aria-hidden="true">×</span>
                </button>
              </div>
              <fieldset className="launcher-language-options">
                <legend>{t("app.interfaceLanguage")}</legend>
                <button
                  type="button"
                  className={locale === "en" ? "selected" : undefined}
                  aria-label={t("app.languageEnglish")}
                  aria-pressed={locale === "en"}
                  onClick={() => {
                    setLocale("en");
                    setLauncherSettingsOpen(false);
                    launcherSettingsButtonRef.current?.focus();
                  }}
                >
                  <span>EN</span>
                  <strong>{t("app.languageEnglish")}</strong>
                  <i aria-hidden="true">✓</i>
                </button>
                <button
                  type="button"
                  className={locale === "zh-CN" ? "selected" : undefined}
                  aria-label={t("app.languageChinese")}
                  aria-pressed={locale === "zh-CN"}
                  onClick={() => {
                    setLocale("zh-CN");
                    setLauncherSettingsOpen(false);
                    launcherSettingsButtonRef.current?.focus();
                  }}
                >
                  <span>中</span>
                  <strong>{t("app.languageChinese")}</strong>
                  <i aria-hidden="true">✓</i>
                </button>
              </fieldset>
            </section>
          </div>
        ) : null}
        <main id="main-content" className="launcher-main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    );
  }

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
