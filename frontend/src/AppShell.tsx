import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { apiClient } from "./api/client";
import { getDesktopWindowHandle, isDesktopRuntime } from "./desktop/bridge";
import type { DesktopWindowHandle, RuntimeComponentState } from "./desktop/bridge";
import {
  DesktopRuntimeAccessProvider,
  useDesktopRuntimeAccess,
} from "./desktop/access";
import type { DesktopRuntimeAccess } from "./desktop/access";
import { MINIMUM_MEMORY_BYTES } from "./desktop/readiness";
import { useAppUpdater } from "./desktop/updater";
import { OPEN_APP_SETTINGS_EVENT } from "./appSettings";
import { useModelAccess } from "./features/settings/ModelAccessContext";
import type { ModelProvider } from "./features/settings/ModelAccessContext";
import { ModelAccessProvider } from "./features/settings/ModelAccessProvider";
import {
  clearExperimentDraft,
  hasExperimentDraft,
} from "./features/experiment/draftStorage";
import { useI18n } from "./i18n/I18nProvider";
import type { TranslationKey } from "./i18n/I18nProvider";
import type { JobStatus } from "./types/api";

const NAV_ITEMS: {
  to: string;
  labelKey?: TranslationKey;
  label?: string;
  end?: boolean;
  desktopTo?: string;
  requiresRuntime?: boolean;
}[] = [
  { to: "/", desktopTo: "/dashboard", labelKey: "app.dashboard", end: true },
  { to: "/history", labelKey: "app.history" },
  { to: "/ece498", label: "ECE498BH" },
];

const EXIT_GUARD_JOB_STATUSES: JobStatus[] = [
  "CREATED",
  "QUEUED",
  "RUNNING",
  "AGGREGATING",
  "FINALIZING",
];
const ACTIVE_JOB_CHECK_TIMEOUT_MS = 2_500;

interface ExitPromptState {
  hasDraft: boolean;
  activeJobCount: number;
  activeJobsUnknown: boolean;
}

async function countActiveJobsBeforeExit(): Promise<number> {
  let timeoutId: number | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timeoutId = window.setTimeout(
      () => reject(new Error("Timed out while checking active experiments.")),
      ACTIVE_JOB_CHECK_TIMEOUT_MS,
    );
  });
  try {
    const pages = await Promise.race([
      Promise.all(EXIT_GUARD_JOB_STATUSES.map((status) =>
        apiClient.listJobs({ page: 1, page_size: 1, status })
      )),
      timeout,
    ]);
    return pages.reduce((total, page) => total + page.total, 0);
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
}

export function AppShell() {
  return (
    <DesktopRuntimeAccessProvider>
      <ModelAccessProvider>
        <AppShellContent />
      </ModelAccessProvider>
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

function UpdateDownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3.75v10.5m0 0 4-4m-4 4-4-4" />
      <path d="M5.25 15.75v2.5a2 2 0 0 0 2 2h9.5a2 2 0 0 0 2-2v-2.5" />
    </svg>
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
  const { settings: modelAccess, selectProvider, updateSettings } = useModelAccess();
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
      <section className="settings-model-panel" aria-labelledby="settings-model-title">
        <div className="settings-model-heading">
          <h3 id="settings-model-title">{t("settings.model.title")}</h3>
          <span className={modelAccess.apiKey ? "configured" : undefined}>
            <i aria-hidden="true" />
            {t(modelAccess.apiKey ? "settings.model.configured" : "settings.model.notConfigured")}
          </span>
        </div>
        <div className="settings-model-grid">
          <label htmlFor="settings_model_provider">
            <span>{t("wizard.field.llmProvider")}</span>
            <select
              id="settings_model_provider"
              value={modelAccess.provider}
              onChange={(event) => selectProvider(event.target.value as ModelProvider)}
            >
              <option value="openai">OpenAI</option>
              <option value="qwen">Qwen</option>
              <option value="deepseek">DeepSeek</option>
              <option value="custom">{t("wizard.llm.customProvider")}</option>
            </select>
          </label>
          <label htmlFor="settings_model_name">
            <span>{t("wizard.field.llmModel")}</span>
            <input
              id="settings_model_name"
              value={modelAccess.model}
              onChange={(event) => updateSettings({ model: event.target.value })}
              placeholder={t("wizard.field.backendDefault")}
            />
          </label>
          <label className="settings-model-wide" htmlFor="settings_model_api_key">
            <span>{t("wizard.field.llmApiKey")}</span>
            <input
              id="settings_model_api_key"
              type="password"
              autoComplete="off"
              value={modelAccess.apiKey}
              onChange={(event) => updateSettings({ apiKey: event.target.value })}
              placeholder={t("settings.model.apiKeyPlaceholder")}
            />
          </label>
          <label className="settings-model-wide" htmlFor="settings_model_base_url">
            <span>{t("wizard.field.llmBaseUrl")}</span>
            <input
              id="settings_model_base_url"
              type="url"
              value={modelAccess.baseUrl}
              onChange={(event) => updateSettings({ baseUrl: event.target.value })}
              placeholder="https://…/v1"
            />
          </label>
        </div>
        <p className="settings-model-security-note">{t("settings.model.securityNote")}</p>
      </section>
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

function ExitGuardDialog({
  state,
  onReturn,
  onConfirmExit,
}: {
  state: ExitPromptState;
  onReturn: () => void;
  onConfirmExit: () => void;
}) {
  const { t } = useI18n();
  const paragraphKey: TranslationKey = state.hasDraft
    ? state.activeJobsUnknown
      ? "exitGuard.draftActiveUnknown"
      : state.activeJobCount > 0
        ? "exitGuard.draftActive"
        : "exitGuard.draft"
    : state.activeJobsUnknown
      ? "exitGuard.activeUnknown"
      : "exitGuard.active";

  return (
    <div className="app-exit-backdrop" role="presentation">
      <section
        className="app-exit-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="app-exit-title"
        aria-describedby="app-exit-description"
      >
        <h2 id="app-exit-title">{t("exitGuard.title")}</h2>
        <p id="app-exit-description">
          {t(paragraphKey, { count: state.activeJobCount })}
        </p>
        <div className="app-exit-actions">
          <button type="button" className="btn" autoFocus onClick={onReturn}>
            {t("exitGuard.return")}
          </button>
          <button
            type="button"
            className="btn app-exit-confirm"
            onClick={onConfirmExit}
          >
            {t(state.hasDraft ? "exitGuard.exitDiscard" : "exitGuard.exitAnyway")}
          </button>
        </div>
      </section>
    </div>
  );
}

function AppShellContent() {
  const location = useLocation();
  const desktopRuntime = isDesktopRuntime();
  const runtimeAccess = useDesktopRuntimeAccess();
  const appUpdater = useAppUpdater();
  const { t } = useI18n();
  const [launcherSettingsOpen, setLauncherSettingsOpen] = useState(false);
  const [exitPrompt, setExitPrompt] = useState<ExitPromptState | null>(null);
  const launcherSettingsButtonRef = useRef<HTMLButtonElement>(null);
  const launcherSettingsCloseRef = useRef<HTMLButtonElement>(null);
  const desktopWindowRef = useRef<DesktopWindowHandle | null>(null);
  const currentPathRef = useRef(location.pathname);
  const exitPromptRef = useRef<ExitPromptState | null>(null);
  const exitCheckInFlightRef = useRef(false);
  const exitApprovedRef = useRef(false);
  const launcherMode = desktopRuntime && location.pathname === "/desktop/setup";
  const experimentWizardMode = location.pathname === "/jobs/new";
  const runtimeIsBusy = runtimeAccess.status === "checking" ||
    runtimeAccess.status === "starting";
  const launcherRuntimeChecking = runtimeAccess.isChecking || runtimeIsBusy;
  const launcherRuntimeChecked =
    runtimeAccess.status === "ready" && !runtimeAccess.isChecking;
  const runtimeNavDescription = runtimeAccess.status === "checking"
    ? t("runtimeGate.navChecking")
    : runtimeAccess.status === "starting"
      ? t("runtimeGate.navStarting")
      : t("runtimeGate.navLocked");
  const updateAvailable = appUpdater.status === "available";
  const updateBusy = appUpdater.status === "checking" ||
    appUpdater.status === "downloading" ||
    appUpdater.status === "installing";
  const updateTitle = appUpdater.status === "available"
    ? t("updater.available", { version: appUpdater.availableVersion ?? "" })
    : appUpdater.status === "checking"
      ? t("updater.checking")
      : appUpdater.status === "downloading"
        ? t("updater.downloading", { progress: appUpdater.progress ?? 0 })
        : appUpdater.status === "installing"
          ? t("updater.installing")
          : appUpdater.status === "error"
            ? t("updater.error")
            : t("updater.current");

  const closeSettings = useCallback(() => {
    setLauncherSettingsOpen(false);
    // The trigger is inert while the modal is open. Restore focus on the next
    // frame, after the dialog effect has removed inert from the app shell.
    requestAnimationFrame(() => launcherSettingsButtonRef.current?.focus());
  }, []);

  const returnFromExitPrompt = useCallback(() => {
    exitPromptRef.current = null;
    setExitPrompt(null);
  }, []);

  const confirmExit = useCallback(() => {
    const desktopWindow = desktopWindowRef.current;
    if (!desktopWindow) return;
    clearExperimentDraft();
    exitApprovedRef.current = true;
    exitPromptRef.current = null;
    setExitPrompt(null);
    void desktopWindow.destroy().catch(() => {
      exitApprovedRef.current = false;
    });
  }, []);

  useEffect(() => {
    currentPathRef.current = location.pathname;
  }, [location.pathname]);

  useEffect(() => {
    exitPromptRef.current = exitPrompt;
  }, [exitPrompt]);

  useEffect(() => {
    if (!desktopRuntime) return;
    const desktopWindow = getDesktopWindowHandle();
    if (!desktopWindow) return;
    desktopWindowRef.current = desktopWindow;
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    void desktopWindow.onCloseRequested(async (event) => {
      if (exitApprovedRef.current) return;
      event.preventDefault();
      if (exitCheckInFlightRef.current || exitPromptRef.current) return;
      exitCheckInFlightRef.current = true;

      const path = currentPathRef.current;
      const hasDraft = path === "/jobs/new" || hasExperimentDraft();
      let activeJobCount = 0;
      let activeJobsUnknown = false;
      if (path !== "/desktop/setup") {
        try {
          activeJobCount = await countActiveJobsBeforeExit();
        } catch {
          activeJobsUnknown = true;
        }
      }

      const state = { hasDraft, activeJobCount, activeJobsUnknown };
      const mustConfirm = hasDraft || activeJobCount > 0 || activeJobsUnknown;
      if (mustConfirm) {
        if (!cancelled) {
          exitPromptRef.current = state;
          setExitPrompt(state);
        }
      } else {
        clearExperimentDraft();
        exitApprovedRef.current = true;
        try {
          await desktopWindow.destroy();
        } catch {
          exitApprovedRef.current = false;
        }
      }
      exitCheckInFlightRef.current = false;
    }).then((dispose) => {
      if (cancelled) dispose();
      else unlisten = dispose;
    }).catch(() => {
      desktopWindowRef.current = null;
    });

    return () => {
      cancelled = true;
      desktopWindowRef.current = null;
      unlisten?.();
    };
  }, [desktopRuntime]);

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

  const exitGuard = exitPrompt ? (
    <ExitGuardDialog
      state={exitPrompt}
      onReturn={returnFromExitPrompt}
      onConfirmExit={confirmExit}
    />
  ) : null;

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
            <span className={`launcher-runtime-indicator${launcherRuntimeChecked ? " is-checked" : ""}`}>
              <span aria-hidden="true" />
              {launcherRuntimeChecking
                ? t("runtimeGate.checkingShort")
                : launcherRuntimeChecked
                  ? t("runtimeGate.checkedShort")
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
        {exitGuard}
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
              !runtimeAccess.canUseRuntime,
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
          <div className={`app-version-pill${updateAvailable ? " is-update-available" : ""}`}>
            <span>{t("app.previewVersion")}</span>
            {appUpdater.desktopRuntime ? (
              <button
                type="button"
                className="app-update-button"
                aria-label={updateTitle}
                title={updateTitle}
                disabled={updateBusy}
                onClick={() => {
                  if (updateAvailable) void appUpdater.installAvailableUpdate();
                  else void appUpdater.checkForUpdates();
                }}
              >
                <UpdateDownloadIcon />
              </button>
            ) : null}
          </div>
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
        {exitGuard}
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
