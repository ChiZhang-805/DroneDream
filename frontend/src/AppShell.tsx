import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { isDesktopRuntime } from "./desktop/bridge";
import type { RuntimeComponentState } from "./desktop/bridge";
import {
  DesktopRuntimeAccessProvider,
  useDesktopRuntimeAccess,
} from "./desktop/access";
import type { DesktopRuntimeAccess } from "./desktop/access";
import { MINIMUM_MEMORY_BYTES } from "./desktop/readiness";
import { OPEN_APP_SETTINGS_EVENT } from "./appSettings";
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
  { to: "/history", labelKey: "app.history" },
  { to: "/ece498", label: "ECE498" },
];

export function AppShell() {
  return (
    <DesktopRuntimeAccessProvider>
      <AppShellContent />
    </DesktopRuntimeAccessProvider>
  );
}

function LanguageRegionIcon({ region }: { region: "west" | "east" }) {
  return (
    <span className={`launcher-language-icon launcher-language-icon-${region}`} aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.25" />
        <path d="M3.9 12h16.2M12 3.75c2.1 2.25 3.2 5 3.2 8.25S14.1 18 12 20.25C9.9 18 8.8 15.25 8.8 12S9.9 6 12 3.75Z" />
        <circle className="launcher-language-region" cx={region === "west" ? "8" : "16"} cy="10" r="1.65" />
      </svg>
    </span>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3.15" />
      <path d="M19.45 13.25a7.9 7.9 0 0 0 0-2.5l2-1.55-2-3.46-2.48 1a8.4 8.4 0 0 0-2.17-1.25L14.45 2h-4.9L9.2 5.49a8.4 8.4 0 0 0-2.17 1.25l-2.48-1-2 3.46 2 1.55a7.9 7.9 0 0 0 0 2.5l-2 1.55 2 3.46 2.48-1a8.4 8.4 0 0 0 2.17 1.25L9.55 22h4.9l.35-3.49a8.4 8.4 0 0 0 2.17-1.25l2.48 1 2-3.46-2-1.55Z" />
    </svg>
  );
}

type RuntimeHealthLevel = "unknown" | "healthy" | "warning" | "error";

const COMPONENT_STATE_KEY: Record<RuntimeComponentState, TranslationKey> = {
  ready: "desktop.component.ready",
  missing: "desktop.component.missing",
  stopped: "desktop.component.stopped",
  unhealthy: "desktop.component.unhealthy",
  unknown: "desktop.component.unknown",
};

function runtimeHealthLevel(access: DesktopRuntimeAccess): RuntimeHealthLevel {
  if (!access.desktopRuntime) return "unknown";
  if (!access.snapshot) return "unknown";
  if (!access.snapshot.ready) return "error";
  const { prerequisites, runtime } = access.snapshot;
  const hasWarning = prerequisites.probeErrors.length > 0 ||
    runtime.diagnostics.length > 0 ||
    runtime.components.some((component) =>
      !component.required && component.status !== "ready"
    );
  return hasWarning ? "warning" : "healthy";
}

function SettingsDialog({
  access,
  closeRef,
  onClose,
}: {
  access: DesktopRuntimeAccess;
  closeRef: RefObject<HTMLButtonElement>;
  onClose: () => void;
}) {
  const { locale, setLocale, t } = useI18n();
  const level = runtimeHealthLevel(access);
  const snapshot = access.snapshot;
  const details: string[] = [];
  if (snapshot) {
    const { prerequisites, runtime } = snapshot;
    if (!prerequisites.supported) details.push(t("settings.runtime.unsupportedSystem"));
    if (!prerequisites.windows) details.push(t("settings.runtime.windowsMissing"));
    if (!prerequisites.wsl.executableAvailable) details.push(t("settings.runtime.wslMissing"));
    if (!prerequisites.memory || prerequisites.memory.totalBytes < MINIMUM_MEMORY_BYTES) {
      details.push(t("settings.runtime.memoryLow"));
    }
    details.push(...prerequisites.probeErrors);
    if (!runtime.installed) details.push(t("settings.runtime.notInstalled"));
    else if (!runtime.running) details.push(t("settings.runtime.notRunning"));
    for (const component of runtime.components) {
      if (component.status === "ready") continue;
      details.push(
        `${component.label}: ${t(COMPONENT_STATE_KEY[component.status])}` +
          (component.detail ? ` — ${component.detail}` : ""),
      );
    }
    details.push(...runtime.diagnostics);
  } else if (!access.isChecking) {
    details.push(t("settings.runtime.noResult"));
  }
  const uniqueDetails = [...new Set(details.filter(Boolean))];
  const statusLabel = access.isChecking
    ? t("settings.runtime.checking")
    : level === "healthy"
      ? t("settings.runtime.healthy")
      : level === "warning"
        ? t("settings.runtime.warning")
        : level === "error"
          ? t("settings.runtime.error")
          : t("settings.runtime.unknown");
  const statusIcon = access.isChecking
    ? "…"
    : level === "healthy"
      ? "✓"
      : level === "warning"
        ? "!"
        : level === "error"
          ? "×"
          : "?";
  const lastChecked = access.lastFullCheckAt
    ? new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(access.lastFullCheckAt)
    : t("settings.runtime.neverChecked");

  return (
    <section
      className="launcher-settings-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="launcher-settings-title"
    >
      <div className="launcher-settings-heading">
        <h2 id="launcher-settings-title">{t("app.settingsTitle")}</h2>
        <button
          ref={closeRef}
          type="button"
          className="launcher-settings-close"
          aria-label={t("app.closeSettings")}
          onClick={onClose}
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
      <fieldset className="launcher-language-options" aria-label={t("app.interfaceLanguage")}>
        <button
          type="button"
          className={locale === "en" ? "selected" : undefined}
          aria-label={t("app.languageEnglish")}
          aria-pressed={locale === "en"}
          onClick={() => setLocale("en")}
        >
          <LanguageRegionIcon region="west" />
          <strong>{t("app.languageEnglish")}</strong>
          <i aria-hidden="true">✓</i>
        </button>
        <button
          type="button"
          className={locale === "zh-CN" ? "selected" : undefined}
          aria-label={t("app.languageChinese")}
          aria-pressed={locale === "zh-CN"}
          onClick={() => setLocale("zh-CN")}
        >
          <LanguageRegionIcon region="east" />
          <strong>{t("app.languageChinese")}</strong>
          <i aria-hidden="true">✓</i>
        </button>
      </fieldset>
      {access.desktopRuntime ? (
        <section className="settings-runtime-panel" aria-labelledby="settings-runtime-title">
          <div className="settings-runtime-heading">
            <div>
              <h3 id="settings-runtime-title">{t("settings.runtime.title")}</h3>
            </div>
            <button
              type="button"
              className="btn settings-runtime-check"
              disabled={access.isChecking}
              onClick={() => void access.refresh()}
            >
              {access.isChecking
                ? t("settings.runtime.checking")
                : t("settings.runtime.checkNow")}
            </button>
          </div>
          <div
            className={`settings-runtime-status settings-runtime-status-${access.isChecking ? "checking" : level}`}
            role="status"
            aria-live="polite"
          >
            <span className="settings-runtime-status-icon" aria-hidden="true">{statusIcon}</span>
            <div>
              <strong>{statusLabel}</strong>
              <small>{t("settings.runtime.lastChecked")}: {lastChecked}</small>
            </div>
          </div>
          {!access.isChecking && level !== "healthy" && uniqueDetails.length > 0 ? (
            <details className="settings-runtime-details">
              <summary>{t("settings.runtime.viewDetails")}</summary>
              <div className="settings-runtime-details-scroll">
                <ul>
                  {uniqueDetails.map((detail) => <li key={detail}>{detail}</li>)}
                </ul>
              </div>
            </details>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

function AppShellContent() {
  const location = useLocation();
  const desktopRuntime = isDesktopRuntime();
  const runtimeAccess = useDesktopRuntimeAccess();
  const { t } = useI18n();
  const [launcherSettingsOpen, setLauncherSettingsOpen] = useState(false);
  const launcherSettingsButtonRef = useRef<HTMLButtonElement>(null);
  const launcherSettingsCloseRef = useRef<HTMLButtonElement>(null);
  const launcherMode = desktopRuntime && location.pathname === "/desktop/setup";
  const experimentWizardMode = location.pathname === "/jobs/new";
  const runtimeIsBusy = runtimeAccess.status === "checking" ||
    runtimeAccess.status === "starting";
  const runtimeNavDescription = runtimeAccess.status === "checking"
    ? t("runtimeGate.navChecking")
    : runtimeAccess.status === "starting"
      ? t("runtimeGate.navStarting")
      : t("runtimeGate.navLocked");

  const closeSettings = useCallback(() => {
    setLauncherSettingsOpen(false);
    // The trigger is inert while the modal is open. Restore focus on the next
    // frame, after the dialog effect has removed inert from the app shell.
    requestAnimationFrame(() => launcherSettingsButtonRef.current?.focus());
  }, []);

  useEffect(() => {
    const openSettings = () => setLauncherSettingsOpen(true);
    window.addEventListener(OPEN_APP_SETTINGS_EVENT, openSettings);
    return () => window.removeEventListener(OPEN_APP_SETTINGS_EVENT, openSettings);
  }, []);

  useEffect(() => {
    if (new URLSearchParams(location.search).get("settings") === "runtime") {
      setLauncherSettingsOpen(true);
    }
  }, [location.search]);

  useEffect(() => {
    if (!launcherSettingsOpen) return;
    const previousOverflow = document.body.style.overflow;
    const inertTargets = Array.from(document.querySelectorAll<HTMLElement>(
      ".launcher-chrome, .launcher-main, .app-sidebar, .app-header, .app-main, .app-footer, .skip-link",
    ));
    const previousInertStates = inertTargets.map((target) => target.inert);
    document.body.style.overflow = "hidden";
    inertTargets.forEach((target) => { target.inert = true; });
    const focusFrame = requestAnimationFrame(() => launcherSettingsCloseRef.current?.focus());
    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeSettings();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = launcherSettingsCloseRef.current?.closest<HTMLElement>(
        '[role="dialog"]',
      );
      if (!dialog) return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), '
          + 'textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hasAttribute("hidden"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleDialogKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      inertTargets.forEach((target, index) => {
        target.inert = previousInertStates[index] ?? false;
      });
      cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleDialogKeyDown);
    };
  }, [closeSettings, launcherSettingsOpen]);

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
                : runtimeAccess.status === "starting"
                  ? t("runtimeGate.startingShort")
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
              <SettingsIcon />
            </button>
          </div>
        </header>
        {launcherSettingsOpen ? (
          <div
            className="launcher-settings-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target !== event.currentTarget) return;
              closeSettings();
            }}
          >
            <SettingsDialog
              access={runtimeAccess}
              closeRef={launcherSettingsCloseRef}
              onClose={closeSettings}
            />
          </div>
        ) : null}
        <main id="main-content" className="launcher-main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    );
  }

  return (
    <div className={`app-shell${experimentWizardMode ? " app-shell-wizard" : ""}`}>
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

            return (
              <NavLink
                key={item.to}
                to={destination}
                end={item.end}
                title={runtimeLocked ? runtimeNavDescription : undefined}
                aria-describedby={runtimeLocked ? "runtime-nav-description" : undefined}
                className={({ isActive }) => {
                  const classes = runtimeLocked ? ["runtime-locked"] : [];
                  if (isActive) classes.push("active");
                  return classes.length > 0 ? classes.join(" ") : undefined;
                }}
              >
                <span>{item.labelKey ? t(item.labelKey) : item.label}</span>
                {runtimeLocked ? (
                  <span className="nav-runtime-badge" aria-hidden="true">
                    {runtimeIsBusy
                      ? runtimeAccess.status === "starting"
                        ? t("runtimeGate.startingShort")
                        : t("runtimeGate.checkingShort")
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
      <div className={`app-body${experimentWizardMode ? " app-body-wizard" : ""}`}>
        <header className="app-header">
          <div className="app-header-title">DroneDream — {t("app.platform")}</div>
          <div className="app-header-meta">
            <button
              ref={launcherSettingsButtonRef}
              type="button"
              className="launcher-settings-button"
              aria-label={t("app.settings")}
              aria-haspopup="dialog"
              aria-expanded={launcherSettingsOpen}
              onClick={() => setLauncherSettingsOpen(true)}
            >
              <SettingsIcon />
            </button>
          </div>
        </header>
        {launcherSettingsOpen ? (
          <div
            className="launcher-settings-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target !== event.currentTarget) return;
              closeSettings();
            }}
          >
            <SettingsDialog
              access={runtimeAccess}
              closeRef={launcherSettingsCloseRef}
              onClose={closeSettings}
            />
          </div>
        ) : null}
        <main id="main-content" className={`app-main${experimentWizardMode ? " app-main-wizard" : ""}`} tabIndex={-1}>
          <Outlet />
        </main>
        <footer className="app-footer">
          <div className="app-footer-content">
            <span>{t("app.author")}: Chi Zhang</span>
            <span>{t("app.contact")}: cz005623@gmail.com</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
