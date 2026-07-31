import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ChangeEvent, MouseEvent, RefObject } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Apple,
  BotMessageSquare,
  Camera,
  CircleUserRound,
  GraduationCap,
  History,
  ImagePlus,
  LayoutDashboard,
  LogIn,
  MailCheck,
  MoreHorizontal,
  Save,
  Settings,
  X,
  type LucideIcon,
} from "lucide-react";

import { apiClient } from "./api/client";
import {
  ArchivedExperimentManager,
  ExperimentWorkspaceSidebar,
} from "./components/ExperimentWorkspaceSidebar";
import {
  AvatarCropDialog,
  type AvatarCropCopy,
} from "./components/AvatarCropDialog";
import { BrandLockup } from "./components/BrandLockup";
import {
  getDesktopWindowHandle,
  isDesktopRuntime,
  stopRuntimeForExit,
} from "./desktop/bridge";
import type { DesktopWindowHandle, RuntimeComponentState } from "./desktop/bridge";
import {
  DesktopRuntimeAccessProvider,
  useDesktopRuntimeAccess,
} from "./desktop/access";
import type { DesktopRuntimeAccess } from "./desktop/access";
import { MINIMUM_MEMORY_BYTES } from "./desktop/readiness";
import {
  approveDesktopStartupGateWithoutCloudAuth,
  setDesktopStartupGateState,
  verifyDesktopStartupGate,
} from "./desktop/startupGate";
import {
  AppUpdaterProvider,
  useAppUpdaterState,
} from "./desktop/updaterContext";
import { OPEN_APP_SETTINGS_EVENT } from "./appSettings";
import { AuthCaptcha } from "./features/auth/AuthCaptcha";
import { AuthProvider, useAuth } from "./features/auth/AuthContext";
import { OPEN_ACCOUNT_DIALOG_EVENT } from "./features/auth/events";
import {
  captchaProtectionConfigured,
  turnstileSiteKey,
} from "./features/auth/supabaseClient";
import { useModelAccess } from "./features/settings/ModelAccessContext";
import {
  modelProviderLabel,
  type ModelProvider,
} from "./features/settings/ModelAccessContext";
import { ModelAccessProvider } from "./features/settings/ModelAccessProvider";
import {
  CloudModelAccessError,
  getManagedModelUsage,
  type ManagedModelUsageSnapshot,
} from "./features/settings/cloudModelAccess";
import {
  hasExperimentDraft,
  persistExperimentDraftsForExit,
} from "./features/experiment/draftStorage";
import { useI18n } from "./i18n/I18nProvider";
import type { TranslationKey } from "./i18n/I18nProvider";
import type {
  Job,
  JobStatus,
  StarterExperienceTemplateKey,
  UserDefaultTrackType,
  UserExperiencePreferences,
} from "./types/api";
import { ECE498BH_COURSE_URL } from "./externalLinks";

const NAV_ITEMS: {
  to: string;
  labelKey?: TranslationKey;
  label?: string;
  end?: boolean;
  desktopTo?: string;
  requiresRuntime?: boolean;
  externalUrl?: string;
  icon: LucideIcon;
}[] = [
  {
    to: "/assistant",
    labelKey: "app.conversation",
    end: true,
    requiresRuntime: true,
    icon: BotMessageSquare,
  },
  {
    to: "/dashboard",
    labelKey: "app.dashboard",
    end: true,
    icon: LayoutDashboard,
  },
  { to: "/history", labelKey: "app.history", icon: History },
  {
    to: ECE498BH_COURSE_URL,
    label: "ECE498BH",
    externalUrl: ECE498BH_COURSE_URL,
    icon: GraduationCap,
  },
];

const EXIT_GUARD_JOB_STATUSES: JobStatus[] = [
  "CREATED",
  "QUEUED",
  "RUNNING",
  "AGGREGATING",
  "FINALIZING",
];

const DOCS_PREVIEW_MANAGED_USAGE: ManagedModelUsageSnapshot = {
  plan: {
    id: "plus",
    name: "Plus",
    monthly_price_cny_fen: 6_900,
    included_ai_credits: 2_000,
    capability_set: "core-v1",
  },
  period: {
    starts_at: "2026-07-01T00:00:00Z",
    ends_at: "2026-08-01T00:00:00Z",
  },
  usage: {
    reserved_ai_credits: 0,
    consumed_ai_credits: 684,
    remaining_ai_credits: 1_316,
    request_count: 57,
    input_tokens: 184_320,
    output_tokens: 46_080,
    total_tokens: 230_400,
    estimated_request_count: 0,
    credit_policy_version: 1,
  },
  recent_requests: [],
};
const ACTIVE_JOB_CHECK_TIMEOUT_MS = 2_500;
const ACTIVE_JOB_CANCEL_TIMEOUT_MS = 2_000;
const RUNTIME_EXIT_TIMEOUT_MS = 6_000;
const ACTIVE_JOB_PAGE_SIZE = 100;
const MAX_ACTIVE_JOB_PAGES_PER_STATUS = 10;

interface ExperiencePreferenceDraft {
  memory_enabled: boolean;
  default_template_key: StarterExperienceTemplateKey | null;
  default_track_type: UserDefaultTrackType | null;
  default_altitude_m: number | null;
}

const EMPTY_EXPERIENCE_PREFERENCE_DRAFT: ExperiencePreferenceDraft = {
  memory_enabled: false,
  default_template_key: null,
  default_track_type: null,
  default_altitude_m: null,
};
const EXPERIENCE_PREFERENCE_LOAD_FAILED = "experience-preference-load-failed";

interface ExitPromptState {
  hasDraft: boolean;
  draftPreserved: boolean;
  activeJobCount: number;
  activeJobs: Pick<Job, "id" | "control_version">[];
  activeJobsUnknown: boolean;
}

async function listActiveJobsForStatus(status: JobStatus): Promise<{
  count: number;
  jobs: Pick<Job, "id" | "control_version">[];
}> {
  const first = await apiClient.listJobs({
    page: 1,
    page_size: ACTIVE_JOB_PAGE_SIZE,
    status,
  });
  const pageCount = Math.ceil(first.total / ACTIVE_JOB_PAGE_SIZE);
  if (pageCount > MAX_ACTIVE_JOB_PAGES_PER_STATUS) {
    throw new Error("Too many active experiments to enumerate safely before exit.");
  }
  const remaining = pageCount > 1
    ? await Promise.all(
        Array.from({ length: pageCount - 1 }, (_, index) =>
          apiClient.listJobs({
            page: index + 2,
            page_size: ACTIVE_JOB_PAGE_SIZE,
            status,
          })
        ),
      )
    : [];
  return {
    count: first.total,
    jobs: Array.from(
      new Map(
        [first, ...remaining]
          .flatMap((page) => page.items)
          .map((job) => [job.id, {
            id: job.id,
            control_version: job.control_version,
          }] as const),
      ).values(),
    ),
  };
}

async function findActiveJobsBeforeExit(): Promise<{
  count: number;
  jobs: Pick<Job, "id" | "control_version">[];
}> {
  let timeoutId: number | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timeoutId = window.setTimeout(
      () => reject(new Error("Timed out while checking active experiments.")),
      ACTIVE_JOB_CHECK_TIMEOUT_MS,
    );
  });
  try {
    const statuses = await Promise.race([
      Promise.all(EXIT_GUARD_JOB_STATUSES.map(listActiveJobsForStatus)),
      timeout,
    ]);
    return {
      count: statuses.reduce((total, result) => total + result.count, 0),
      jobs: Array.from(
        new Map(
          statuses
            .flatMap((result) => result.jobs)
            .map((job) => [job.id, job] as const),
        ).values(),
      ),
    };
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
}

async function stopKnownActiveJobsBeforeExit(
  jobs: Pick<Job, "id" | "control_version">[],
): Promise<void> {
  if (jobs.length === 0) return;
  let timeoutId: number | undefined;
  const timeout = new Promise<void>((resolve) => {
    timeoutId = window.setTimeout(resolve, ACTIVE_JOB_CANCEL_TIMEOUT_MS);
  });
  try {
    await Promise.race([
      Promise.allSettled(
        jobs.map((job) => apiClient.cancelJob(job.id, job.control_version)),
      ).then(() => undefined),
      timeout,
    ]);
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
}

async function stopDesktopRuntimeBeforeExit(): Promise<void> {
  let timeoutId: number | undefined;
  const timeout = new Promise<void>((resolve) => {
    timeoutId = window.setTimeout(resolve, RUNTIME_EXIT_TIMEOUT_MS);
  });
  try {
    await Promise.race([
      stopRuntimeForExit().catch(() => undefined),
      timeout,
    ]);
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
}

export function AppShell() {
  return (
    <AuthProvider>
      <DesktopRuntimeAccessProvider>
        <AppUpdaterProvider>
          <ModelAccessProvider>
            <AppShellContent />
          </ModelAccessProvider>
        </AppUpdaterProvider>
      </DesktopRuntimeAccessProvider>
    </AuthProvider>
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
  const auth = useAuth();
  const {
    settings: modelAccess,
    profiles: modelProfiles,
    activeProfileId,
    selectProfile,
    addProfile,
    removeActiveProfile,
    selectAccessMode,
    selectProvider,
    updateSettings,
  } = useModelAccess();
  const docsPreview = import.meta.env.DEV
    && new URLSearchParams(window.location.search).has("docsPreview");
  const [managedUsage, setManagedUsage] =
    useState<ManagedModelUsageSnapshot | null>(
      docsPreview ? DOCS_PREVIEW_MANAGED_USAGE : null,
    );
  const [managedUsageState, setManagedUsageState] =
    useState<"idle" | "loading" | "ready" | "error">(
      docsPreview ? "ready" : "idle",
    );
  const [managedUsageError, setManagedUsageError] = useState<string | null>(null);
  const [subscriptionOpenError, setSubscriptionOpenError] =
    useState<string | null>(null);
  const [experiencePreferences, setExperiencePreferences] =
    useState<UserExperiencePreferences | null>(null);
  const [experiencePreferenceDraft, setExperiencePreferenceDraft] =
    useState<ExperiencePreferenceDraft>(EMPTY_EXPERIENCE_PREFERENCE_DRAFT);
  const [experiencePreferenceState, setExperiencePreferenceState] =
    useState<"blocked" | "loading" | "ready" | "saving" | "saved" | "error">(
      access.canUseRuntime ? "loading" : "blocked",
    );
  const [experiencePreferenceMessage, setExperiencePreferenceMessage] =
    useState<string | null>(null);
  const [confirmExperiencePreferenceDelete, setConfirmExperiencePreferenceDelete] =
    useState(false);
  const openSubscriptionPage = useCallback((
    event: MouseEvent<HTMLAnchorElement>,
  ) => {
    if (!isDesktopRuntime()) return;
    event.preventDefault();
    setSubscriptionOpenError(null);
    void import("@tauri-apps/plugin-opener")
      .then(({ openUrl }) =>
        openUrl("https://getdronedream.com/pricing/")
      )
      .catch(() => {
        setSubscriptionOpenError(t("settings.model.subscriptionOpenFailed"));
      });
  }, [t]);
  const refreshManagedUsage = useCallback(async () => {
    if (modelAccess.accessMode !== "platform") return;
    if (docsPreview) {
      setManagedUsage(DOCS_PREVIEW_MANAGED_USAGE);
      setManagedUsageState("ready");
      setManagedUsageError(null);
      return;
    }
    if (!auth.account) return;
    setManagedUsageState("loading");
    setManagedUsageError(null);
    try {
      setManagedUsage(await getManagedModelUsage());
      setManagedUsageState("ready");
    } catch (error) {
      setManagedUsageState("error");
      setManagedUsageError(
        error instanceof CloudModelAccessError
          ? error.message
          : t("settings.model.usageUnavailable"),
      );
    }
  }, [auth.account, docsPreview, modelAccess.accessMode, t]);
  useEffect(() => {
    void refreshManagedUsage();
  }, [refreshManagedUsage]);
  useEffect(() => {
    if (!access.canUseRuntime) {
      setExperiencePreferenceState("blocked");
      setExperiencePreferenceMessage(null);
      setConfirmExperiencePreferenceDelete(false);
      return undefined;
    }
    let active = true;
    setExperiencePreferenceState("loading");
    setExperiencePreferenceMessage(null);
    void apiClient.getUserExperiencePreferences()
      .then((preferences) => {
        if (!active) return;
        setExperiencePreferences(preferences);
        setExperiencePreferenceDraft({
          memory_enabled: preferences.memory_enabled,
          default_template_key: preferences.default_template_key,
          default_track_type: preferences.default_track_type,
          default_altitude_m: preferences.default_altitude_m,
        });
        setExperiencePreferenceState("ready");
      })
      .catch(() => {
        if (!active) return;
        setExperiencePreferenceState("error");
        setExperiencePreferenceMessage(EXPERIENCE_PREFERENCE_LOAD_FAILED);
      });
    return () => {
      active = false;
    };
  }, [access.canUseRuntime]);
  const saveExperiencePreferences = async () => {
    if (
      !access.canUseRuntime ||
      experiencePreferenceState === "blocked" ||
      experiencePreferenceState === "loading" ||
      experiencePreferenceState === "saving"
    ) {
      return;
    }
    setExperiencePreferenceState("saving");
    setExperiencePreferenceMessage(null);
    try {
      const saved = await apiClient.updateUserExperiencePreferences({
        ...experiencePreferenceDraft,
        locale,
      });
      setExperiencePreferences(saved);
      setExperiencePreferenceState("saved");
      setExperiencePreferenceMessage(
        saved.deleted_memory_count > 0
          ? t("settings.memory.savedAndDeleted", {
              count: saved.deleted_memory_count,
            })
          : t("settings.memory.saved"),
      );
    } catch {
      setExperiencePreferenceState("error");
      setExperiencePreferenceMessage(t("settings.memory.saveFailed"));
    }
  };
  const deleteExperiencePreferences = async () => {
    if (
      !access.canUseRuntime ||
      experiencePreferenceState === "blocked" ||
      experiencePreferenceState === "loading" ||
      experiencePreferenceState === "saving"
    ) {
      return;
    }
    setExperiencePreferenceState("saving");
    setExperiencePreferenceMessage(null);
    try {
      const deleted = await apiClient.deleteUserExperiencePreferences();
      setExperiencePreferences(null);
      setExperiencePreferenceDraft(EMPTY_EXPERIENCE_PREFERENCE_DRAFT);
      setConfirmExperiencePreferenceDelete(false);
      setExperiencePreferenceState("ready");
      setExperiencePreferenceMessage(
        t("settings.memory.deleted", {
          count: deleted.deleted_memory_count,
        }),
      );
    } catch {
      setExperiencePreferenceState("error");
      setExperiencePreferenceMessage(t("settings.memory.deleteFailed"));
    }
  };
  const numberFormatter = new Intl.NumberFormat(locale === "zh-CN" ? "zh-CN" : "en");
  const experiencePreferenceControlsDisabled =
    experiencePreferenceState === "blocked" ||
    experiencePreferenceState === "loading" ||
    experiencePreferenceState === "saving";
  const creditRatio = managedUsage
    ? Math.min(
        100,
        Math.max(
          0,
          managedUsage.plan.included_ai_credits > 0
            ? managedUsage.usage.consumed_ai_credits
              / managedUsage.plan.included_ai_credits
              * 100
            : 0,
        ),
      )
    : 0;
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
      <section className="settings-memory-panel" aria-labelledby="settings-memory-title">
        <div className="settings-memory-heading">
          <div>
            <h3 id="settings-memory-title">{t("settings.memory.title")}</h3>
            <p>{t("settings.memory.description")}</p>
          </div>
          <span className={experiencePreferenceDraft.memory_enabled ? "configured" : undefined}>
            {t(
              experiencePreferenceDraft.memory_enabled
                ? "settings.memory.enabled"
                : "settings.memory.disabled",
            )}
          </span>
        </div>
        <label className="settings-memory-consent" htmlFor="settings_memory_enabled">
          <input
            id="settings_memory_enabled"
            type="checkbox"
            checked={experiencePreferenceDraft.memory_enabled}
            disabled={experiencePreferenceControlsDisabled}
            onChange={(event) => setExperiencePreferenceDraft((current) => ({
              ...current,
              memory_enabled: event.target.checked,
            }))}
          />
          <span>
            <strong>{t("settings.memory.consent")}</strong>
            <small>{t("settings.memory.consentDetail")}</small>
          </span>
        </label>
        <div className="settings-memory-grid">
          <label htmlFor="settings_default_template">
            <span>{t("settings.memory.defaultTemplate")}</span>
            <select
              id="settings_default_template"
              value={experiencePreferenceDraft.default_template_key ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_template_key: (
                  event.target.value || null
                ) as StarterExperienceTemplateKey | null,
              }))}
            >
              <option value="">{t("settings.memory.noDefault")}</option>
              <option value="hover-basics@1">{t("wizard.starter.hover.title")} · v1</option>
              <option value="first-circle@1">{t("wizard.starter.circle.title")} · v1</option>
              <option value="light-wind-circle@1">{t("wizard.starter.wind.title")} · v1</option>
            </select>
          </label>
          <label htmlFor="settings_default_track">
            <span>{t("settings.memory.defaultTrack")}</span>
            <select
              id="settings_default_track"
              value={experiencePreferenceDraft.default_track_type ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_track_type: (
                  event.target.value || null
                ) as UserDefaultTrackType | null,
              }))}
            >
              <option value="">{t("settings.memory.noDefault")}</option>
              <option value="hover">{t("wizard.track.hover")}</option>
              <option value="circle">{t("wizard.track.circle")}</option>
              <option value="u_turn">{t("wizard.track.uTurn")}</option>
              <option value="lemniscate">{t("wizard.track.lemniscate")}</option>
            </select>
          </label>
          <label htmlFor="settings_default_altitude">
            <span>{t("settings.memory.defaultAltitude")}</span>
            <input
              id="settings_default_altitude"
              type="number"
              min="1"
              max="20"
              step="0.1"
              value={experiencePreferenceDraft.default_altitude_m ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_altitude_m: event.target.value === ""
                  ? null
                  : Number(event.target.value),
              }))}
            />
          </label>
        </div>
        <p className="settings-memory-policy">
          {t("settings.memory.policy", {
            days: experiencePreferences?.retention_days ?? 90,
          })}
        </p>
        <div className="settings-memory-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={experiencePreferenceControlsDisabled}
            onClick={() => void saveExperiencePreferences()}
          >
            {experiencePreferenceState === "saving"
              ? t("settings.memory.saving")
              : t("settings.memory.save")}
          </button>
          {!confirmExperiencePreferenceDelete ? (
            <button
              type="button"
              className="btn btn-danger"
              disabled={experiencePreferenceControlsDisabled}
              onClick={() => setConfirmExperiencePreferenceDelete(true)}
            >
              {t("settings.memory.delete")}
            </button>
          ) : (
            <div className="settings-memory-delete-confirm" role="group" aria-label={t("settings.memory.confirmDelete")}>
              <span>{t("settings.memory.confirmDelete")}</span>
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => void deleteExperiencePreferences()}
              >
                {t("settings.memory.confirm")}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => setConfirmExperiencePreferenceDelete(false)}
              >
                {t("settings.memory.cancel")}
              </button>
            </div>
          )}
        </div>
        {experiencePreferenceState === "blocked" ? (
          <p className="settings-memory-message" role="status">
            {t("settings.memory.runtimeRequired")}
          </p>
        ) : null}
        {experiencePreferenceMessage ? (
          <p
            className="settings-memory-message"
            role={experiencePreferenceState === "error" ? "alert" : "status"}
          >
            {experiencePreferenceMessage === EXPERIENCE_PREFERENCE_LOAD_FAILED
              ? t("settings.memory.loadFailed")
              : experiencePreferenceMessage}
          </p>
        ) : null}
      </section>
      <section className="settings-model-panel" aria-labelledby="settings-model-title">
        <div className="settings-model-heading">
          <h3 id="settings-model-title">{t("settings.model.title")}</h3>
          <span className={
            modelAccess.accessMode === "platform" || modelAccess.apiKey
              ? "configured"
              : undefined
          }>
            <i aria-hidden="true" />
            {t(
              modelAccess.accessMode === "platform"
                ? "settings.model.managed"
                : modelAccess.apiKey
                  ? "settings.model.configured"
                  : "settings.model.notConfigured",
            )}
          </span>
        </div>
        <div className="settings-model-access-mode" role="group" aria-label={t("settings.model.accessMode")}>
          <button
            type="button"
            className={modelAccess.accessMode === "platform" ? "selected" : undefined}
            aria-pressed={modelAccess.accessMode === "platform"}
            onClick={() => selectAccessMode("platform")}
          >
            <strong>{t("settings.model.includedAllowance")}</strong>
            <span>{t("settings.model.includedAllowanceDetail")}</span>
          </button>
          <button
            type="button"
            className={modelAccess.accessMode === "byok" ? "selected" : undefined}
            aria-pressed={modelAccess.accessMode === "byok"}
            onClick={() => selectAccessMode("byok")}
          >
            <strong>{t("settings.model.byok")}</strong>
            <span>{t("settings.model.byokDetail")}</span>
          </button>
        </div>
        {modelAccess.accessMode === "platform" ? (
          <div className="settings-model-usage">
            <div className="settings-model-plan-row">
              <div>
                <span>{t("settings.model.currentPlan")}</span>
                <strong>{managedUsage?.plan.name ?? "Free / Plus / Pro"}</strong>
              </div>
              <a
                href="https://getdronedream.com/pricing/"
                target="_blank"
                rel="noreferrer"
                className="btn"
                onClick={openSubscriptionPage}
              >
                {t("settings.model.manageSubscription")}
              </a>
            </div>
            {subscriptionOpenError ? (
              <p className="settings-model-usage-message" role="alert">
                {subscriptionOpenError}
              </p>
            ) : null}
            {!auth.account && !docsPreview ? (
              <p className="settings-model-usage-message">
                {t("settings.model.signInForAllowance")}
              </p>
            ) : managedUsage ? (
              <>
                <div className="settings-model-quota-heading">
                  <span>{t("settings.model.periodUsage")}</span>
                  <strong>
                    {numberFormatter.format(managedUsage.usage.consumed_ai_credits)}
                    {" / "}
                    {numberFormatter.format(managedUsage.plan.included_ai_credits)}
                    {" "}
                    {t("settings.model.credits")}
                  </strong>
                </div>
                <div
                  className="settings-model-quota-track"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={managedUsage.plan.included_ai_credits}
                  aria-valuenow={managedUsage.usage.consumed_ai_credits}
                >
                  <span style={{ width: `${creditRatio}%` }} />
                </div>
                <div className="settings-model-usage-grid">
                  <div>
                    <span>{t("settings.model.remaining")}</span>
                    <strong>{numberFormatter.format(managedUsage.usage.remaining_ai_credits)}</strong>
                  </div>
                  <div>
                    <span>{t("settings.model.requests")}</span>
                    <strong>{numberFormatter.format(managedUsage.usage.request_count)}</strong>
                  </div>
                  <div>
                    <span>{t("settings.model.inputTokens")}</span>
                    <strong>{numberFormatter.format(managedUsage.usage.input_tokens)}</strong>
                  </div>
                  <div>
                    <span>{t("settings.model.outputTokens")}</span>
                    <strong>{numberFormatter.format(managedUsage.usage.output_tokens)}</strong>
                  </div>
                </div>
              </>
            ) : (
              <p className="settings-model-usage-message" role="status">
                {managedUsageState === "loading"
                  ? t("settings.model.loadingUsage")
                  : managedUsageError ?? t("settings.model.usageUnavailable")}
              </p>
            )}
            <div className="settings-model-usage-footer">
              {managedUsage ? (
                <p className="settings-model-period">
                  {t("settings.model.resetsAt")}:{" "}
                  {new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en", {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }).format(new Date(managedUsage.period.ends_at))}
                  {managedUsage.usage.estimated_request_count > 0
                    ? ` · ${t("settings.model.estimatedUsage", {
                        count: managedUsage.usage.estimated_request_count,
                      })}`
                    : ""}
                </p>
              ) : <span aria-hidden="true" />}
              {auth.account || docsPreview ? (
                <button
                  type="button"
                  className="btn settings-model-refresh"
                  disabled={managedUsageState === "loading"}
                  onClick={() => void refreshManagedUsage()}
                >
                  {t("settings.model.refreshUsage")}
                </button>
              ) : null}
            </div>
            <p className="settings-model-security-note">
              {t("settings.model.platformSecurityNote")}
            </p>
          </div>
        ) : (
          <>
            <div className="settings-model-profile-row">
              <label htmlFor="settings_model_profile">
                <span>{t("settings.model.profile")}</span>
                <select
                  id="settings_model_profile"
                  value={activeProfileId}
                  onChange={(event) => selectProfile(event.target.value)}
                >
                  {modelProfiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {modelProviderLabel(profile.provider)} ·{" "}
                      {profile.model || t("wizard.field.backendDefault")}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="btn"
                onClick={addProfile}
                disabled={modelProfiles.length >= 12}
              >
                {t("settings.model.addProfile")}
              </button>
              <button
                type="button"
                className="btn"
                onClick={removeActiveProfile}
                disabled={modelProfiles.length <= 1}
              >
                {t("settings.model.removeProfile")}
              </button>
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
                  maxLength={128}
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
                  maxLength={512}
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
                  maxLength={2048}
                  onChange={(event) => updateSettings({ baseUrl: event.target.value })}
                  placeholder="https://…/v1"
                />
              </label>
            </div>
            <p className="settings-model-security-note">{t("settings.model.securityNote")}</p>
          </>
        )}
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
        {state.hasDraft ? (
          <p role={state.draftPreserved ? "status" : "alert"}>
            {t(
              state.draftPreserved
                ? "exitGuard.draftSaved"
                : "exitGuard.draftSaveFailed",
            )}
          </p>
        ) : null}
        <div className="app-exit-actions">
          <button type="button" className="btn" autoFocus onClick={onReturn}>
            {t("exitGuard.return")}
          </button>
          <button
            type="button"
            className="btn app-exit-confirm"
            onClick={onConfirmExit}
          >
            {t(state.hasDraft ? "exitGuard.exitKeep" : "exitGuard.exitAnyway")}
          </button>
        </div>
      </section>
    </div>
  );
}

const ACCOUNT_COPY = {
  en: {
    title: "DroneDream account",
    signInTitle: "Sign in to DroneDream",
    registerTitle: "Create account",
    localTitle: "Local workspace",
    localBody:
      "This build keeps experiments on this computer. Connect the cloud account configuration to enable isolated email accounts, secure storage, and cross-device data sync.",
    email: "Email address",
    emailPlaceholder: "you@example.com",
    password: "Password",
    passwordPlaceholder: "At least 8 characters",
    confirmPassword: "Confirm password",
    confirmPasswordPlaceholder: "Enter the password again",
    sendCode: "Send code",
    resendCode: "Resend code",
    signIn: "Sign in",
    register: "Register",
    createAccount: "Create account",
    registerNow: "New to DroneDream? Register now",
    backToSignIn: "Already registered? Sign in",
    code: "Verification code",
    codePlaceholder: "Six-digit code",
    passwordTooShort: "Password must contain at least 8 characters.",
    passwordMismatch: "The two passwords do not match.",
    codeRequired: "Send and enter the verification code before creating the account.",
    completeCaptcha: "Complete the security check before continuing.",
    google: "Continue with Google",
    apple: "Continue with Apple",
    username: "Username",
    usernamePlaceholder: "Choose a username",
    saveUsername: "Save username",
    profilePhoto: "Profile photo",
    choosePhoto: "Choose from computer",
    useCamera: "Use camera",
    takePhoto: "Take photo",
    cancelCamera: "Cancel camera",
    invalidPhoto: "Choose a JPEG, PNG, or WebP image.",
    photoTooLarge: "Choose an image smaller than 8 MB.",
    cropTitle: "Crop profile photo",
    cropInstructions:
      "Drag the image to position it inside the circle. Use the slider, +/− keys, or arrow keys to adjust the crop before saving.",
    cropArea: "Profile photo crop area",
    cropZoom: "Zoom",
    cropPreview: "Circular preview",
    cropCancel: "Cancel",
    cropConfirm: "Save cropped photo",
    cropClose: "Close photo cropper",
    cropFailed: "The profile photo could not be cropped. Choose another image and try again.",
    cameraRequiresHttps:
      "Camera access requires HTTPS. Open the secure GitHub Pages site, or use the DroneDream desktop app.",
    cameraDenied:
      "Camera permission is blocked. Allow camera access in the browser site settings or Windows privacy settings, then try again.",
    cameraMissing: "No available camera was found on this device.",
    cameraBusy:
      "The camera could not be started. Close other apps using it, then try again.",
    cameraConstraint:
      "The camera cannot provide a compatible video stream on this device.",
    cameraUnavailable: "The camera is unavailable or permission was not granted.",
    cameraNotReady: "Wait for the camera preview before taking the photo.",
    signOut: "Sign out",
    close: "Close account",
    account: "Account",
    localUser: "Local user",
    localWorkspace: "Local workspace",
    cloudWorkspace: "Cloud workspace",
  },
  "zh-CN": {
    title: "DroneDream 账号",
    signInTitle: "登录 DroneDream",
    registerTitle: "创建账号",
    localTitle: "本地工作区",
    localBody:
      "当前构建将实验保存在这台电脑。完成云账号配置后，即可启用相互隔离的邮箱账号、跨设备数据与完整的安全存储能力。",
    email: "邮箱地址",
    emailPlaceholder: "you@example.com",
    password: "密码",
    passwordPlaceholder: "至少 8 个字符",
    confirmPassword: "确认密码",
    confirmPasswordPlaceholder: "再次输入密码",
    sendCode: "发送验证码",
    resendCode: "重新发送",
    signIn: "登录",
    register: "注册",
    createAccount: "创建账号",
    registerNow: "还没有账号？立即注册",
    backToSignIn: "已经注册？返回登录",
    code: "邮箱验证码",
    codePlaceholder: "六位验证码",
    passwordTooShort: "密码至少需要 8 个字符。",
    passwordMismatch: "两次输入的密码不一致。",
    codeRequired: "请先发送并填写邮箱验证码，再创建账号。",
    completeCaptcha: "请先完成安全验证，再继续。",
    google: "使用 Google 登录",
    apple: "使用 Apple 登录",
    username: "用户名",
    usernamePlaceholder: "输入用户名",
    saveUsername: "保存用户名",
    profilePhoto: "头像",
    choosePhoto: "从电脑选择",
    useCamera: "使用摄像头",
    takePhoto: "拍摄头像",
    cancelCamera: "关闭摄像头",
    invalidPhoto: "请选择 JPEG、PNG 或 WebP 图片。",
    photoTooLarge: "请选择小于 8 MB 的图片。",
    cropTitle: "裁剪头像",
    cropInstructions:
      "拖动图片，让需要保留的区域位于圆形框内。保存前可使用滑杆、加减键或方向键调整位置和缩放。",
    cropArea: "头像裁剪区域",
    cropZoom: "缩放",
    cropPreview: "圆形预览",
    cropCancel: "取消",
    cropConfirm: "保存裁剪后的头像",
    cropClose: "关闭头像裁剪窗口",
    cropFailed: "无法裁剪这张图片。请重新选择图片后再试。",
    cameraRequiresHttps:
      "摄像头只能在 HTTPS 安全页面中使用。请打开 GitHub Pages 正式站点，或使用 DroneDream 桌面软件。",
    cameraDenied:
      "摄像头权限已被阻止。请在浏览器网站设置或 Windows 隐私设置中允许摄像头，然后重试。",
    cameraMissing: "当前设备没有检测到可用摄像头。",
    cameraBusy: "摄像头无法启动。请关闭其他正在使用摄像头的软件，然后重试。",
    cameraConstraint: "当前摄像头无法提供兼容的视频画面。",
    cameraUnavailable: "摄像头不可用，或未获得摄像头权限。",
    cameraNotReady: "请等待摄像头画面出现后再拍摄。",
    signOut: "退出登录",
    close: "关闭账号窗口",
    account: "账号",
    localUser: "本地用户",
    localWorkspace: "本地工作区",
    cloudWorkspace: "云端工作区",
  },
} as const;

const MAX_AVATAR_FILE_BYTES = 8_000_000;

function cameraFrameBlob(video: HTMLVideoElement): Promise<Blob> {
  if (video.videoWidth < 1 || video.videoHeight < 1) {
    return Promise.reject(new Error("The camera preview is empty."));
  }
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext("2d");
  if (!context) {
    return Promise.reject(new Error("The camera photo could not be processed."));
  }
  // Match the front-camera preview so the saved crop has the orientation the
  // user approved instead of unexpectedly flipping after confirmation.
  context.translate(video.videoWidth, 0);
  context.scale(-1, 1);
  context.drawImage(video, 0, 0, video.videoWidth, video.videoHeight);
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("The camera photo could not be processed."));
      },
      "image/jpeg",
      0.92,
    );
  });
}

function AccountAvatar({
  account,
  className,
}: {
  account: ReturnType<typeof useAuth>["account"];
  className: string;
}) {
  return (
    <span className={className} aria-hidden="true">
      {account?.avatarUrl ? (
        <img src={account.avatarUrl} alt="" />
      ) : account ? (
        account.displayName.slice(0, 1).toUpperCase()
      ) : (
        <CircleUserRound strokeWidth={1.75} />
      )}
    </span>
  );
}

function AccountDialog({
  closeRef,
  required,
  onClose,
}: {
  closeRef: RefObject<HTMLButtonElement>;
  required: boolean;
  onClose: () => void;
}) {
  const { locale } = useI18n();
  const copy = ACCOUNT_COPY[locale];
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [captchaCycle, setCaptchaCycle] = useState(0);
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [authMode, setAuthMode] = useState<"sign-in" | "register">("sign-in");
  const [displayName, setDisplayName] = useState(
    auth.account?.displayName ?? "",
  );
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [avatarCropSource, setAvatarCropSource] = useState<{
    url: string;
    returnFocus: HTMLElement | null;
  } | null>(null);
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const chooseAvatarButtonRef = useRef<HTMLButtonElement>(null);
  const cameraButtonRef = useRef<HTMLButtonElement>(null);
  const cameraVideoRef = useRef<HTMLVideoElement>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    setDisplayName(auth.account?.displayName ?? "");
  }, [auth.account?.displayName]);

  const stopCamera = useCallback(() => {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    setCameraStream(null);
    setCameraReady(false);
  }, []);

  useEffect(() => {
    if (!avatarCropSource) return undefined;
    const sourceUrl = avatarCropSource.url;
    return () => URL.revokeObjectURL(sourceUrl);
  }, [avatarCropSource]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    };
  }, []);

  useEffect(() => {
    const video = cameraVideoRef.current;
    if (!video || !cameraStream) return;
    video.srcObject = cameraStream;
    try {
      const playback = video.play();
      void playback?.catch(() => undefined);
    } catch {
      // Some embedded webviews begin playback from the autoplay attributes
      // without exposing a usable play() promise.
    }
  }, [cameraStream]);

  const run = async (action: () => Promise<void>) => {
    setPending(true);
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Account request failed.",
      );
    } finally {
      setPending(false);
    }
  };

  const chooseAvatar = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError(copy.invalidPhoto);
      return;
    }
    if (file.size > MAX_AVATAR_FILE_BYTES) {
      setError(copy.photoTooLarge);
      return;
    }
    setError(null);
    setAvatarCropSource({
      url: URL.createObjectURL(file),
      returnFocus: chooseAvatarButtonRef.current,
    });
  };

  const startCamera = async () => {
    if (!window.isSecureContext && !isDesktopRuntime()) {
      setError(copy.cameraRequiresHttps);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(copy.cameraUnavailable);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      stopCamera();
      cameraStreamRef.current = stream;
      setCameraStream(stream);
    } catch (reason) {
      const errorName = reason instanceof DOMException ? reason.name : "";
      if (["NotAllowedError", "PermissionDeniedError", "SecurityError"].includes(errorName)) {
        setError(copy.cameraDenied);
      } else if (["NotFoundError", "DevicesNotFoundError"].includes(errorName)) {
        setError(copy.cameraMissing);
      } else if (["NotReadableError", "TrackStartError", "AbortError"].includes(errorName)) {
        setError(copy.cameraBusy);
      } else if (
        ["OverconstrainedError", "ConstraintNotSatisfiedError"].includes(errorName)
      ) {
        setError(copy.cameraConstraint);
      } else {
        setError(copy.cameraUnavailable);
      }
    } finally {
      if (mountedRef.current) setPending(false);
    }
  };

  const captureAvatar = async () => {
    const video = cameraVideoRef.current;
    if (!video || !cameraReady || video.videoWidth < 1 || video.videoHeight < 1) {
      setError(copy.cameraNotReady);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const frame = await cameraFrameBlob(video);
      stopCamera();
      setAvatarCropSource({
        url: URL.createObjectURL(frame),
        returnFocus: cameraButtonRef.current,
      });
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : copy.cropFailed,
      );
    } finally {
      if (mountedRef.current) setPending(false);
    }
  };

  const closeAvatarCrop = useCallback(() => {
    const returnFocus = avatarCropSource?.returnFocus ?? null;
    setAvatarCropSource(null);
    window.requestAnimationFrame(() => returnFocus?.focus());
  }, [avatarCropSource]);

  const saveCroppedAvatar = async (avatar: string) => {
    setPending(true);
    setError(null);
    try {
      await auth.updateAvatar(avatar);
      closeAvatarCrop();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : copy.cropFailed,
      );
      throw reason;
    } finally {
      if (mountedRef.current) setPending(false);
    }
  };
  const avatarCropCopy: AvatarCropCopy = {
    title: copy.cropTitle,
    instructions: copy.cropInstructions,
    cropArea: copy.cropArea,
    zoom: copy.cropZoom,
    preview: copy.cropPreview,
    cancel: copy.cropCancel,
    confirm: copy.cropConfirm,
    close: copy.cropClose,
    processingFailed: copy.cropFailed,
  };

  const registrationPasswordIsValid = () => {
    if (password.length < 8) {
      setError(copy.passwordTooShort);
      return false;
    }
    if (password !== passwordConfirmation) {
      setError(copy.passwordMismatch);
      return false;
    }
    return true;
  };

  return (
    <section
      className="account-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-dialog-title"
    >
      <header>
        <div className="account-dialog-title">
          <CircleUserRound aria-hidden="true" strokeWidth={1.75} />
          <h2 id="account-dialog-title">
            {!auth.configured
              ? copy.localTitle
              : auth.account
                ? copy.title
                : authMode === "register"
                  ? copy.registerTitle
                  : copy.signInTitle}
          </h2>
        </div>
        {!required ? (
          <button
            ref={closeRef}
            type="button"
            className="account-dialog-close"
            aria-label={copy.close}
            onClick={onClose}
          >
            <X aria-hidden="true" strokeWidth={1.9} />
          </button>
        ) : null}
      </header>

      {!auth.configured ? (
        <p className="account-dialog-copy">{copy.localBody}</p>
      ) : auth.account ? (
        <div className="account-profile-wrap">
          <div className="account-profile">
            <AccountAvatar
              account={auth.account}
              className="account-avatar"
            />
            <div>
              <strong>{auth.account.displayName}</strong>
              <span>{auth.account.email}</span>
            </div>
            <button
              type="button"
              className="btn account-sign-out"
              disabled={pending}
              onClick={() => void run(auth.signOut)}
            >
              {copy.signOut}
            </button>
          </div>
          <section className="account-avatar-editor">
            <strong>{copy.profilePhoto}</strong>
            <div className="account-avatar-actions">
              <input
                ref={avatarInputRef}
                className="account-avatar-input"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(event) => void chooseAvatar(event)}
              />
              <button
                ref={chooseAvatarButtonRef}
                type="button"
                className="btn"
                disabled={pending}
                onClick={() => avatarInputRef.current?.click()}
              >
                <ImagePlus aria-hidden="true" strokeWidth={1.8} />
                {copy.choosePhoto}
              </button>
              <button
                ref={cameraButtonRef}
                type="button"
                className="btn"
                disabled={pending || Boolean(cameraStream)}
                onClick={() => void startCamera()}
              >
                <Camera aria-hidden="true" strokeWidth={1.8} />
                {copy.useCamera}
              </button>
            </div>
          </section>
          {cameraStream ? (
            <section className="account-camera-panel">
              <video
                ref={cameraVideoRef}
                autoPlay
                muted
                playsInline
                onCanPlay={() => setCameraReady(true)}
              />
              <div>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={pending || !cameraReady}
                  onClick={() => void captureAvatar()}
                >
                  <Camera aria-hidden="true" strokeWidth={1.8} />
                  {copy.takePhoto}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={pending}
                  onClick={stopCamera}
                >
                  {copy.cancelCamera}
                </button>
              </div>
            </section>
          ) : null}
          <form
            className="account-username-form"
            onSubmit={(event) => {
              event.preventDefault();
              void run(() => auth.updateDisplayName(displayName));
            }}
          >
            <label htmlFor="account-username">{copy.username}</label>
            <div>
              <input
                id="account-username"
                type="text"
                required
                maxLength={48}
                autoComplete="nickname"
                value={displayName}
                placeholder={copy.usernamePlaceholder}
                disabled={pending}
                onChange={(event) => setDisplayName(event.target.value)}
              />
              <button
                type="submit"
                className="btn btn-primary account-save-username"
                aria-label={copy.saveUsername}
                title={copy.saveUsername}
                disabled={
                  pending ||
                  !displayName.trim() ||
                  displayName.trim() === auth.account.displayName
                }
              >
                <Save aria-hidden="true" strokeWidth={1.9} />
              </button>
            </div>
          </form>
          {avatarCropSource ? (
            <AvatarCropDialog
              sourceUrl={avatarCropSource.url}
              copy={avatarCropCopy}
              pending={pending}
              onCancel={closeAvatarCrop}
              onConfirm={saveCroppedAvatar}
              onSourceError={(message) => {
                setError(message);
                closeAvatarCrop();
              }}
            />
          ) : null}
        </div>
      ) : (
        <>
          <form
            className="account-email-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (authMode === "sign-in") {
                if (captchaProtectionConfigured && !captchaToken) {
                  setError(copy.completeCaptcha);
                  return;
                }
                void run(async () => {
                  try {
                    if (captchaToken) {
                      await auth.signInWithPassword(
                        email,
                        password,
                        captchaToken,
                      );
                    } else {
                      await auth.signInWithPassword(email, password);
                    }
                  } finally {
                    if (captchaProtectionConfigured) {
                      setCaptchaToken(null);
                      setCaptchaCycle((current) => current + 1);
                    }
                  }
                });
                return;
              }
              if (!registrationPasswordIsValid()) return;
              if (!codeSent || !code.trim()) {
                setError(copy.codeRequired);
                return;
              }
              void run(() =>
                auth.verifyRegistrationCode(email, code, password)
              );
            }}
          >
            <label>
              <span>{copy.email}</span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                placeholder={copy.emailPlaceholder}
                disabled={pending || (authMode === "register" && codeSent)}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label>
              <span>{copy.password}</span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete={
                  authMode === "register" ? "new-password" : "current-password"
                }
                value={password}
                placeholder={copy.passwordPlaceholder}
                disabled={pending}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {authMode === "register" ? (
              <>
                <label>
                  <span>{copy.confirmPassword}</span>
                  <input
                    type="password"
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={passwordConfirmation}
                    placeholder={copy.confirmPasswordPlaceholder}
                    disabled={pending}
                    onChange={(event) =>
                      setPasswordConfirmation(event.target.value)
                    }
                  />
                </label>
                <div className="account-code-field">
                  <label htmlFor="account-registration-code">
                    <span>{copy.code}</span>
                  </label>
                  <div className="account-code-row">
                    <input
                      id="account-registration-code"
                      type="text"
                      required
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      minLength={6}
                      maxLength={12}
                      value={code}
                      placeholder={copy.codePlaceholder}
                      disabled={pending}
                      onChange={(event) =>
                        setCode(event.target.value.replace(/\s/g, ""))
                      }
                    />
                    <button
                      type="button"
                      className="btn account-send-code"
                      disabled={pending || !email.trim()}
                    onClick={() => {
                      if (!registrationPasswordIsValid()) return;
                      if (captchaProtectionConfigured && !captchaToken) {
                        setError(copy.completeCaptcha);
                        return;
                      }
                      void run(async () => {
                          try {
                            if (captchaToken) {
                              await auth.sendRegistrationCode(
                                email,
                                captchaToken,
                              );
                            } else {
                              await auth.sendRegistrationCode(email);
                            }
                            setCodeSent(true);
                          } finally {
                            if (captchaProtectionConfigured) {
                              setCaptchaToken(null);
                              setCaptchaCycle((current) => current + 1);
                            }
                          }
                        });
                      }}
                    >
                      {codeSent ? copy.resendCode : copy.sendCode}
                    </button>
                  </div>
                </div>
              </>
            ) : null}
            {captchaProtectionConfigured ? (
              <AuthCaptcha
                key={captchaCycle}
                siteKey={turnstileSiteKey}
                onTokenChange={setCaptchaToken}
              />
            ) : null}
            <button type="submit" className="btn btn-primary" disabled={pending}>
              <MailCheck aria-hidden="true" strokeWidth={1.8} />
              {authMode === "register" ? copy.createAccount : copy.signIn}
            </button>
          </form>
          <button
            type="button"
            className="account-auth-mode"
            disabled={pending}
            onClick={() => {
              setAuthMode((current) =>
                current === "sign-in" ? "register" : "sign-in",
              );
              setCode("");
              setCodeSent(false);
              setCaptchaToken(null);
              setCaptchaCycle((current) => current + 1);
              setPassword("");
              setPasswordConfirmation("");
              setError(null);
            }}
          >
            {authMode === "sign-in"
              ? copy.registerNow
              : copy.backToSignIn}
          </button>
          {auth.googleEnabled || auth.appleEnabled ? (
            <div className="account-social-actions">
              {auth.googleEnabled ? (
                <button
                  type="button"
                  className="btn"
                  disabled={pending}
                  onClick={() =>
                    void run(() => auth.signInWithProvider("google"))
                  }
                >
                  <LogIn aria-hidden="true" strokeWidth={1.8} />
                  {copy.google}
                </button>
              ) : null}
              {auth.appleEnabled ? (
                <button
                  type="button"
                  className="btn"
                  disabled={pending}
                  onClick={() =>
                    void run(() => auth.signInWithProvider("apple"))
                  }
                >
                  <Apple aria-hidden="true" strokeWidth={1.8} />
                  {copy.apple}
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      )}
      <ArchivedExperimentManager
        ownerId={auth.account?.id ?? "local"}
        locale={locale}
      />
      {error ? (
        <p className="account-dialog-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function AppShellContent() {
  const location = useLocation();
  const desktopRuntime = isDesktopRuntime();
  const runtimeAccess = useDesktopRuntimeAccess();
  const auth = useAuth();
  const updater = useAppUpdaterState();
  const { locale, t } = useI18n();
  const accountCopy = ACCOUNT_COPY[locale];
  const [launcherSettingsOpen, setLauncherSettingsOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [exitPrompt, setExitPrompt] = useState<ExitPromptState | null>(null);
  const launcherSettingsButtonRef = useRef<HTMLButtonElement>(null);
  const launcherSettingsCloseRef = useRef<HTMLButtonElement>(null);
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  const accountCloseRef = useRef<HTMLButtonElement>(null);
  const desktopWindowRef = useRef<DesktopWindowHandle | null>(null);
  const currentPathRef = useRef(location.pathname);
  const exitPromptRef = useRef<ExitPromptState | null>(null);
  const exitCheckInFlightRef = useRef(false);
  const exitApprovedRef = useRef(false);
  const launcherMode = desktopRuntime && location.pathname === "/desktop/setup";
  const experimentWizardMode = location.pathname === "/jobs/new";
  const runtimeIsBusy = runtimeAccess.status === "checking" ||
    runtimeAccess.status === "starting";
  const launcherRuntimeChecking =
    runtimeAccess.isChecking ||
    runtimeIsBusy;
  const launcherRuntimeChecked =
    runtimeAccess.status === "ready" &&
    !runtimeAccess.isChecking;
  const runtimeNavDescription = runtimeAccess.status === "checking"
    ? t("runtimeGate.navChecking")
    : runtimeAccess.status === "starting"
      ? t("runtimeGate.navStarting")
      : t("runtimeGate.navLocked");
  const accountRequired =
    import.meta.env.MODE !== "test"
    && auth.configured
    && !auth.loading
    && !auth.account;
  const accountDialogRequired = accountRequired && !launcherMode;
  const accountDialogOpen = accountOpen || accountDialogRequired;
  const openExternalNavigation = useCallback((
    event: MouseEvent<HTMLAnchorElement>,
    url: string,
  ) => {
    if (!desktopRuntime) return;
    event.preventDefault();
    void import("@tauri-apps/plugin-opener")
      .then(({ openUrl }) => openUrl(url))
      .catch(() => undefined);
  }, [desktopRuntime]);

  useEffect(() => {
    // The launcher owns a strict two-stage flow: environment first, browser
    // authentication only after the user selects the sole sign-in action at
    // 100%. The workspace gate below therefore runs only after navigation away
    // from the launcher.
    if (!desktopRuntime || launcherMode) return;
    if (
      updater.status === "checking" ||
      updater.status === "downloading" ||
      updater.status === "installing"
    ) {
      setDesktopStartupGateState("checking", {
        accountId: auth.account?.id ?? null,
      });
      return;
    }
    if (updater.status === "available") {
      setDesktopStartupGateState("blocked", {
        accountId: auth.account?.id ?? null,
        error: `DroneDream ${updater.availableVersion ?? "update"} must be installed before entering the tuning workspace.`,
      });
      return;
    }
    if (
      runtimeAccess.isChecking ||
      runtimeAccess.status === "checking" ||
      runtimeAccess.status === "starting"
    ) {
      setDesktopStartupGateState("checking", {
        accountId: auth.account?.id ?? null,
      });
      return;
    }
    if (runtimeAccess.status !== "ready") {
      setDesktopStartupGateState("blocked", {
        accountId: auth.account?.id ?? null,
        error: "The local runtime has not passed its startup checks.",
      });
      return;
    }
    if (!auth.configured) {
      if (import.meta.env.DEV || import.meta.env.MODE === "test") {
        approveDesktopStartupGateWithoutCloudAuth();
      } else {
        setDesktopStartupGateState("blocked", {
          error: "Account authentication is not configured in this desktop build.",
        });
      }
      return;
    }
    if (auth.loading) {
      setDesktopStartupGateState("checking");
      return;
    }
    if (!auth.account) {
      setDesktopStartupGateState("accountRequired");
      return;
    }
    void verifyDesktopStartupGate(
      auth.account.id,
      () => apiClient.verifyAuthenticatedSession(),
    );
  }, [
    auth.account,
    auth.configured,
    auth.loading,
    desktopRuntime,
    launcherMode,
    runtimeAccess.isChecking,
    runtimeAccess.lastFullCheckAt,
    runtimeAccess.status,
    updater.availableVersion,
    updater.status,
  ]);

  const closeSettings = useCallback(() => {
    setLauncherSettingsOpen(false);
    // The trigger is inert while the modal is open. Restore focus on the next
    // frame, after the dialog effect has removed inert from the app shell.
    requestAnimationFrame(() => launcherSettingsButtonRef.current?.focus());
  }, []);

  const closeAccount = useCallback(() => {
    if (accountRequired) return;
    setAccountOpen(false);
    requestAnimationFrame(() => accountButtonRef.current?.focus());
  }, [accountRequired]);

  useEffect(() => {
    if (launcherMode) return;
    const openAccountDialog = () => {
      setLauncherSettingsOpen(false);
      setAccountOpen(true);
    };
    window.addEventListener(OPEN_ACCOUNT_DIALOG_EVENT, openAccountDialog);
    return () =>
      window.removeEventListener(OPEN_ACCOUNT_DIALOG_EVENT, openAccountDialog);
  }, [launcherMode]);

  const returnFromExitPrompt = useCallback(() => {
    exitPromptRef.current = null;
    setExitPrompt(null);
  }, []);

  const confirmExit = useCallback(async () => {
    const desktopWindow = desktopWindowRef.current;
    if (!desktopWindow || exitApprovedRef.current) return;
    persistExperimentDraftsForExit();
    exitApprovedRef.current = true;
    const activeJobs = exitPromptRef.current?.activeJobs ?? [];
    await stopKnownActiveJobsBeforeExit(activeJobs);
    await stopDesktopRuntimeBeforeExit();
    try {
      await desktopWindow.destroy();
    } catch {
      exitApprovedRef.current = false;
    }
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
      const draftPreserved = hasDraft
        ? persistExperimentDraftsForExit()
        : true;
      let activeJobCount = 0;
      let activeJobs: Pick<Job, "id" | "control_version">[] = [];
      let activeJobsUnknown = false;
      if (path !== "/desktop/setup") {
        try {
          const activeJobResult = await findActiveJobsBeforeExit();
          activeJobCount = activeJobResult.count;
          activeJobs = activeJobResult.jobs;
        } catch {
          activeJobsUnknown = true;
        }
      }

      const state = {
        hasDraft,
        draftPreserved,
        activeJobCount,
        activeJobs,
        activeJobsUnknown,
      };
      const mustConfirm = hasDraft || activeJobCount > 0 || activeJobsUnknown;
      if (mustConfirm) {
        if (!cancelled) {
          exitPromptRef.current = state;
          setExitPrompt(state);
        }
      } else {
        exitApprovedRef.current = true;
        await stopDesktopRuntimeBeforeExit();
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

  useEffect(() => {
    if (!accountDialogOpen) return;
    const previousOverflow = document.body.style.overflow;
    const inertTargets = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".launcher-chrome, .launcher-main, .app-sidebar, .app-header, .app-main, .app-footer, .skip-link",
      ),
    );
    const previousInertStates = inertTargets.map((target) => target.inert);
    document.body.style.overflow = "hidden";
    inertTargets.forEach((target) => {
      target.inert = true;
    });
    const focusFrame = requestAnimationFrame(() => {
      const dialog = document.querySelector<HTMLElement>(".account-dialog");
      const firstInput = dialog?.querySelector<HTMLElement>(
        "input:not(:disabled), button:not(:disabled)",
      );
      (accountCloseRef.current ?? firstInput)?.focus();
    });
    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !accountDialogRequired) {
        closeAccount();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = document.querySelector<HTMLElement>(".account-dialog");
      if (!dialog) return;
      const focusable = [
        ...dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), '
            + 'textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      ].filter((element) => !element.hasAttribute("hidden"));
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
  }, [accountDialogOpen, accountDialogRequired, closeAccount]);

  const exitGuard = exitPrompt ? (
    <ExitGuardDialog
      state={exitPrompt}
      onReturn={returnFromExitPrompt}
      onConfirmExit={confirmExit}
    />
  ) : null;
  const accountDialog = accountDialogOpen ? (
    <div
      className="account-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target !== event.currentTarget || accountDialogRequired) return;
        closeAccount();
      }}
    >
      <AccountDialog
        closeRef={accountCloseRef}
        required={accountDialogRequired}
        onClose={closeAccount}
      />
    </div>
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
            <BrandLockup variant="compact" />
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
              <Settings aria-hidden="true" strokeWidth={1.85} />
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
        {desktopRuntime ? (
          <Link to="/assistant" className="app-title" aria-label="DroneDream">
            <BrandLockup variant="compact" />
          </Link>
        ) : (
          <a href="/" className="app-title" aria-label="DroneDream">
            <BrandLockup variant="compact" />
          </a>
        )}
        <nav className="app-nav" aria-label={t("app.primaryNav")}>
          <span id="runtime-nav-description" className="sr-only">
            {runtimeNavDescription}
          </span>
          {NAV_ITEMS.map((item) => {
            const ItemIcon = item.icon;
            const destination = desktopRuntime && item.desktopTo
              ? item.desktopTo
              : item.to;
            const runtimeLocked = Boolean(
              desktopRuntime &&
              item.requiresRuntime &&
              !runtimeAccess.canUseRuntime,
            );
            const itemContent = (
              <>
                <span className="app-nav-entry">
                  <ItemIcon aria-hidden="true" strokeWidth={1.75} />
                  <span>{item.labelKey ? t(item.labelKey) : item.label}</span>
                </span>
                {runtimeLocked ? (
                  <span className="nav-runtime-badge" aria-hidden="true">
                    {runtimeIsBusy
                      ? runtimeAccess.status === "starting"
                        ? t("runtimeGate.startingShort")
                        : t("runtimeGate.checkingShort")
                      : `🔒 ${t("runtimeGate.requiredShort")}`}
                  </span>
                ) : null}
              </>
            );

            const externalUrl = item.externalUrl;
            if (externalUrl) {
              return (
                <a
                  key={item.to}
                  href={externalUrl}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(event) => openExternalNavigation(event, externalUrl)}
                >
                  {itemContent}
                </a>
              );
            }

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
                {itemContent}
              </NavLink>
            );
          })}
        </nav>
        <ExperimentWorkspaceSidebar
          ownerId={auth.account?.id ?? "local"}
          locale={locale}
        />
        <div className="app-sidebar-footer">
          <button
            ref={accountButtonRef}
            type="button"
            className="app-account-button"
            aria-label={accountCopy.account}
            aria-haspopup="dialog"
            aria-expanded={accountDialogOpen}
            onClick={() => {
              setLauncherSettingsOpen(false);
              setAccountOpen(true);
            }}
          >
            <AccountAvatar
              account={auth.account}
              className="app-account-avatar"
            />
            <span className="app-account-copy">
              <strong>
                {auth.account?.displayName ?? accountCopy.localUser}
              </strong>
              <small>
                {auth.account
                  ? accountCopy.cloudWorkspace
                  : accountCopy.localWorkspace}
              </small>
            </span>
            <MoreHorizontal aria-hidden="true" strokeWidth={1.8} />
          </button>
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
              <Settings aria-hidden="true" strokeWidth={1.85} />
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
        {accountDialog}
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
