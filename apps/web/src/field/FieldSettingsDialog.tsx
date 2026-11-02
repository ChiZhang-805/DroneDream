import {
  ArrowRight,
  Bell,
  Bot,
  BrainCircuit,
  ChevronRight,
  MapPinned,
  MonitorCog,
  Plane,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useState, type RefObject } from "react";

import { BrandLockup } from "../components/BrandLockup";
import { CustomModelSettingsPanel } from "../components/CustomModelSettingsPanel";
import { SettingsUpdateCenter } from "../components/SettingsUpdateCenter";
import {
  EditionSettingsPanel,
  EditionSettingsSurface,
  type SettingsSurfaceTab,
  type SettingsSurfaceTabId,
} from "../components/EditionSettingsSurface";
import {
  SETTINGS_LOCALES,
  SettingsLanguageRegionIcon,
  SettingsToggle,
} from "../components/SettingsPrimitives";
import { isDesktopRuntime, startRuntimeUpgrade } from "../desktop/bridge";
import { useModelAccess } from "../features/settings/ModelAccessContext";
import { localeSafeError, type InterfaceLocale } from "../i18n/I18nProvider";
import type { FieldLocale } from "./catalog";

const ECE498BH_COURSE_URL =
  "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html";

type NotificationPreferenceKey =
  | "master"
  | "experiment"
  | "assistant"
  | "updates"
  | "approval"
  | "allowance"
  | "security"
  | "runtime";
type NotificationPreferences = Record<NotificationPreferenceKey, boolean>;
type MemoryScopeKey =
  | "chat"
  | "experiment"
  | "vehicle"
  | "constraints"
  | "safety"
  | "workflow"
  | "reports";
type FieldMemoryDomain = "tuning" | "missions" | "simulation" | "crossEdition";
type FieldMemoryDefaults = Readonly<{
  vehicle: string;
  map: string;
  safety: string;
  units: string;
  report: string;
}>;

const DEFAULT_NOTIFICATIONS: NotificationPreferences = {
  master: true,
  experiment: true,
  assistant: true,
  updates: false,
  approval: true,
  allowance: true,
  security: true,
  runtime: true,
};

const DEFAULT_MEMORY_SCOPES: Record<MemoryScopeKey, boolean> = {
  chat: true,
  experiment: true,
  vehicle: true,
  constraints: true,
  safety: true,
  workflow: true,
  reports: true,
};

const FIELD_MEMORY_DOMAINS: readonly FieldMemoryDomain[] = [
  "tuning",
  "missions",
  "simulation",
  "crossEdition",
];

const DEFAULT_FIELD_MEMORY_DEFAULTS: FieldMemoryDefaults = {
  vehicle: "My Drone",
  map: "School Map",
  safety: "strict",
  units: "metric",
  report: "evidence",
};

const COPY = {
  en: {
    title: "Settings",
    quickTitle: "Settings",
    close: "Close settings",
    back: "Back to app",
    tabs: ["General", "Memory", "Models", "Runtime"] as const,
    language: "Language",
    notifications: "Notifications",
    notificationLabels: [
      "Allow notifications",
      "Experiment and task completed",
      "AI response completed",
      "Product updates",
      "Approval required",
      "Allowance or card expiring",
      "Security and sign-in",
      "Device or runtime status",
    ] as const,
    memory: "Memory",
    memoryState: ["Memory off", "Memory on"] as const,
    accountMemory: "Account memory",
    editionMemory: "FIELD memory",
    crossSession: "Cross-session memory",
    modelEntry: "Models",
    runtimeEntry: "Runtime",
    desktopRuntime: "Desktop Runtime",
    browserRuntime: "Desktop only",
    scopes: [
      "Chat preferences",
      "Experiment defaults",
      "Device and vehicle",
      "Metrics and constraints",
      "Safety and approvals",
      "Workflow and tools",
      "Reports and delivery",
    ] as const,
    defaults: [
      "Default vehicle",
      "Default map",
      "Default safety profile",
      "Default units",
      "Default report format",
    ] as const,
    memoryModules: ["Memory settings", "Read and write access", "Personal defaults"] as const,
    domains: ["Tuning", "Missions", "Simulation", "Cross-edition"] as const,
    access: ["Read", "Write"] as const,
    saveMemoryModules: ["Save memory settings", "Save read and write access", "Save personal defaults"] as const,
    courseOverview:
      "The course connects model reasoning, controls, and aerospace engineering tools with reviewable UAV workflows.",
    openCourse: "Open course",
    courseActions: ["Read manual", "Explore product"] as const,
    safetyTitle: "Field safety boundary",
    executionProfile: "Execution profile",
    vehiclePacks: "Validated Vehicle Packs",
    quorum: "Three-layer quorum",
    authority: "Hardware authority",
    missing: "Missing",
    denied: "Denied",
    runtimeUpgradeStarted: "Runtime Base upgrade started. Keep DroneDream open.",
    runtimeUpgradeUnavailable: "Runtime Base upgrade is unavailable in this build.",
  },
  "zh-CN": {
    title: "设置",
    quickTitle: "设置",
    close: "关闭设置",
    back: "返回应用",
    tabs: ["常规", "记忆", "模型", "Runtime"] as const,
    language: "语言",
    notifications: "通知",
    notificationLabels: [
      "允许通知",
      "实验与任务完成",
      "AI 回复完成",
      "产品更新",
      "需要审批",
      "额度或重置卡即将到期",
      "安全与登录提醒",
      "设备或运行环境状态",
    ] as const,
    memory: "记忆",
    memoryState: ["记忆已关闭", "记忆已开启"] as const,
    accountMemory: "账户记忆",
    editionMemory: "FIELD 记忆",
    crossSession: "跨会话记忆",
    modelEntry: "模型",
    runtimeEntry: "Runtime",
    desktopRuntime: "桌面 Runtime",
    browserRuntime: "仅桌面端",
    scopes: [
      "对话偏好",
      "实验默认值",
      "设备与机型",
      "指标与约束",
      "安全与审批",
      "工作流与工具",
      "报告与交付",
    ] as const,
    defaults: ["默认机型", "默认地图", "默认安全配置", "默认单位制", "默认报告格式"] as const,
    memoryModules: ["记忆设置", "读写权限", "个人默认值"] as const,
    domains: ["调优", "任务", "仿真", "跨版本"] as const,
    access: ["读取", "写入"] as const,
    saveMemoryModules: ["保存记忆设置", "保存读写权限", "保存个人默认值"] as const,
    courseOverview: "课程把模型推理、控制与航空航天工程工具连接为可复核的无人机工作流。",
    openCourse: "打开课程",
    courseActions: ["阅读说明书", "查看产品"] as const,
    safetyTitle: "现场安全边界",
    executionProfile: "执行配置",
    vehiclePacks: "已验证机型包",
    quorum: "三层仲裁",
    authority: "硬件权限",
    missing: "缺失",
    denied: "拒绝",
    runtimeUpgradeStarted: "Runtime Base 升级已启动，请保持 DroneDream 打开。",
    runtimeUpgradeUnavailable: "当前版本暂时无法启动 Runtime Base 升级。",
  },
} as const;

const MEMORY_SCOPE_ICONS = [
  BrainCircuit,
  Sparkles,
  Plane,
  SlidersHorizontal,
  ShieldCheck,
  Workflow,
  MapPinned,
] as const;

function readJson<T extends Record<string, boolean>>(key: string, fallback: T): T {
  try {
    const value = window.localStorage.getItem(key);
    return value ? { ...fallback, ...JSON.parse(value) as Partial<T> } : fallback;
  } catch {
    return fallback;
  }
}

function readStringArray<T extends string>(key: string, fallback: readonly T[]): T[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "null") as unknown;
    return Array.isArray(value)
      ? value.filter((entry): entry is T => typeof entry === "string" && fallback.includes(entry as T))
      : [...fallback];
  } catch {
    return [...fallback];
  }
}

function readFieldMemoryDefaults(): FieldMemoryDefaults {
  try {
    const value = JSON.parse(window.localStorage.getItem("dd.field.memory.defaults") ?? "null") as Partial<FieldMemoryDefaults> | null;
    return value ? { ...DEFAULT_FIELD_MEMORY_DEFAULTS, ...value } : DEFAULT_FIELD_MEMORY_DEFAULTS;
  } catch {
    return DEFAULT_FIELD_MEMORY_DEFAULTS;
  }
}

function readInterfaceLocale(fallback: FieldLocale): InterfaceLocale {
  try {
    const value = window.localStorage.getItem("drone-dream:locale");
    if (SETTINGS_LOCALES.some((locale) => locale.id === value)) {
      return value as InterfaceLocale;
    }
  } catch {
    // The first-run settings remain usable when persistence is unavailable.
  }
  return fallback;
}

function configuredRuntimeReleaseManifestUrl(): string | null {
  const configured = import.meta.env.VITE_RUNTIME_RELEASE_MANIFEST_URL?.trim();
  if (!configured) return null;
  try {
    const url = new URL(configured);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

export function FieldSettingsDialog({
  closeRef,
  initialTab = "general",
  locale,
  onClose,
  onLocaleChange,
  onOpenWorkspace,
  presentation = "workspace",
}: {
  closeRef: RefObject<HTMLButtonElement>;
  initialTab?: SettingsSurfaceTabId;
  locale: FieldLocale;
  onClose: () => void;
  onLocaleChange: (locale: FieldLocale) => void;
  onOpenWorkspace?: (tab: SettingsSurfaceTabId) => void;
  presentation?: "quick" | "workspace";
}) {
  const [activeTab, setActiveTab] = useState<SettingsSurfaceTabId>(initialTab);
  const [interfaceLocale, setInterfaceLocale] = useState<InterfaceLocale>(() =>
    readInterfaceLocale(locale)
  );
  const [notifications, setNotifications] = useState<NotificationPreferences>(() =>
    readJson("dd.notification-preferences.v1", DEFAULT_NOTIFICATIONS)
  );
  const [memoryEnabled, setMemoryEnabled] = useState(() => {
    try {
      return window.localStorage.getItem("dd.field.memory.enabled") !== "false";
    } catch {
      return true;
    }
  });
  const [accountMemoryEnabled, setAccountMemoryEnabled] = useState(() => {
    try {
      return window.localStorage.getItem("dd.field.account-memory.enabled") !== "false";
    } catch {
      return true;
    }
  });
  const [memoryScopes, setMemoryScopes] = useState(() =>
    readJson("dd.field.memory.scopes", DEFAULT_MEMORY_SCOPES)
  );
  const [readMemoryDomains, setReadMemoryDomains] = useState<FieldMemoryDomain[]>(() =>
    readStringArray("dd.field.memory.read-domains", FIELD_MEMORY_DOMAINS)
  );
  const [writeMemoryDomains, setWriteMemoryDomains] = useState<FieldMemoryDomain[]>(() =>
    readStringArray("dd.field.memory.write-domains", FIELD_MEMORY_DOMAINS)
  );
  const [memoryDefaults, setMemoryDefaults] = useState<FieldMemoryDefaults>(readFieldMemoryDefaults);
  const [memorySaveMessage, setMemorySaveMessage] = useState<string | null>(null);
  const [runtimeUpgradeBusy, setRuntimeUpgradeBusy] = useState(false);
  const [runtimeUpgradeNotice, setRuntimeUpgradeNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);
  const modelAccess = useModelAccess();
  const copy = COPY[interfaceLocale === "zh-CN" ? "zh-CN" : "en"];
  const modelSummary = modelAccess.settings.accessMode === "platform"
    ? modelAccess.settings.managedModel
    : modelAccess.settings.displayName || modelAccess.settings.model;
  const tabs: readonly SettingsSurfaceTab[] = [
    { id: "general", label: copy.tabs[0] },
    { id: "memory", label: copy.tabs[1] },
    { id: "model", label: copy.tabs[2] },
    { id: "course", label: "ECE498BH" },
    { id: "runtime", label: copy.tabs[3] },
  ];

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  const selectLocale = (next: InterfaceLocale) => {
    setInterfaceLocale(next);
    try {
      window.localStorage.setItem("drone-dream:locale", next);
    } catch {
      // Keep the language selection for this session when storage is unavailable.
    }
    onLocaleChange(next === "zh-CN" ? "zh-CN" : "en");
  };

  const updateNotification = (key: NotificationPreferenceKey, checked: boolean) => {
    setNotifications((current) => {
      const next = key === "master"
        ? Object.fromEntries(
            Object.keys(current).map((preference) => [preference, checked]),
          ) as NotificationPreferences
        : { ...current, [key]: checked };
      try {
        window.localStorage.setItem("dd.notification-preferences.v1", JSON.stringify(next));
      } catch {
        // The current session still reflects the user's selection.
      }
      return next;
    });
  };

  const updateMemoryEnabled = (enabled: boolean) => {
    setMemoryEnabled(enabled);
    if (presentation === "quick") {
      try { window.localStorage.setItem("dd.field.memory.enabled", String(enabled)); }
      catch { /* The current quick-settings session still reflects the selection. */ }
    }
  };

  const updateAccountMemoryEnabled = (enabled: boolean) => {
    setAccountMemoryEnabled(enabled);
    if (presentation === "quick") {
      try { window.localStorage.setItem("dd.field.account-memory.enabled", String(enabled)); }
      catch { /* The current quick-settings session still reflects the selection. */ }
    }
  };

  const updateMemoryScope = (key: MemoryScopeKey, enabled: boolean) => {
    setMemoryScopes((current) => ({ ...current, [key]: enabled }));
  };

  const toggleMemoryDomain = (
    domain: FieldMemoryDomain,
    access: "read" | "write",
    enabled: boolean,
  ) => {
    const update = access === "read" ? setReadMemoryDomains : setWriteMemoryDomains;
    update((current) => enabled
      ? [...new Set([...current, domain])]
      : current.filter((entry) => entry !== domain));
  };

  const saveFieldMemoryModule = (module: "behavior" | "domains" | "defaults") => {
    try {
      if (module === "behavior") {
        window.localStorage.setItem("dd.field.account-memory.enabled", String(accountMemoryEnabled));
        window.localStorage.setItem("dd.field.memory.enabled", String(memoryEnabled));
        window.localStorage.setItem("dd.field.memory.scopes", JSON.stringify(memoryScopes));
      } else if (module === "domains") {
        window.localStorage.setItem("dd.field.memory.read-domains", JSON.stringify(readMemoryDomains));
        window.localStorage.setItem("dd.field.memory.write-domains", JSON.stringify(writeMemoryDomains));
      } else {
        window.localStorage.setItem("dd.field.memory.defaults", JSON.stringify(memoryDefaults));
      }
      setMemorySaveMessage(interfaceLocale === "zh-CN" ? "已保存此模块。" : "This section has been saved.");
    } catch {
      setMemorySaveMessage(interfaceLocale === "zh-CN" ? "保存失败，请重试。" : "Save failed. Try again.");
    }
  };

  const beginRuntimeBaseUpgrade = async () => {
    if (runtimeUpgradeBusy) return;
    const releaseManifestUrl = configuredRuntimeReleaseManifestUrl();
    if (!releaseManifestUrl) {
      setRuntimeUpgradeNotice({ tone: "error", text: copy.runtimeUpgradeUnavailable });
      return;
    }

    setRuntimeUpgradeBusy(true);
    setRuntimeUpgradeNotice(null);
    try {
      await startRuntimeUpgrade({ releaseManifestUrl });
      setRuntimeUpgradeNotice({ tone: "success", text: copy.runtimeUpgradeStarted });
    } catch (error) {
      setRuntimeUpgradeNotice({
        tone: "error",
        text: localeSafeError(error, interfaceLocale, {
          zh: "Runtime Base 升级未能启动。",
          en: "The Runtime Base upgrade could not start.",
        }),
      });
    } finally {
      setRuntimeUpgradeBusy(false);
    }
  };

  if (presentation === "quick") {
    return (
      <section
        className="quick-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="field-quick-settings-title"
        data-brand-edition="field"
        data-settings-consumer="field"
        data-presentation-only="true"
        data-grants-hardware-authority="false"
      >
        <header className="quick-settings-heading">
          <h2 id="field-quick-settings-title">{copy.quickTitle}</h2>
          <button
            ref={closeRef}
            type="button"
            className="launcher-settings-close"
            aria-label={copy.close}
            title={copy.close}
            onClick={onClose}
          >
            <X aria-hidden="true" />
          </button>
        </header>
        <div className="quick-settings-grid">
          <div className="quick-settings-item quick-settings-language">
            <span>{copy.language}</span>
            <div role="group" aria-label={copy.language}>
              {SETTINGS_LOCALES.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={interfaceLocale === option.id ? "selected" : undefined}
                  aria-pressed={interfaceLocale === option.id}
                  onClick={() => selectLocale(option.id)}
                >
                  <SettingsLanguageRegionIcon region={option.region} />
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="quick-settings-item quick-settings-memory">
            <SettingsToggle
              checked={accountMemoryEnabled}
              label={<><BrainCircuit aria-hidden="true" /><span>{copy.accountMemory}</span></>}
              onChange={updateAccountMemoryEnabled}
            />
            <SettingsToggle
              checked={memoryEnabled}
              disabled={!accountMemoryEnabled}
              label={<><Sparkles aria-hidden="true" /><span>{copy.editionMemory}</span></>}
              onChange={updateMemoryEnabled}
            />
          </div>
          <button
            type="button"
            className="quick-settings-item quick-settings-runtime field-quick-settings-model"
            onClick={() => onOpenWorkspace?.("model")}
          >
            <Bot aria-hidden="true" />
            <span>{copy.modelEntry}</span>
            <strong>{modelSummary || copy.modelEntry}</strong>
            <ChevronRight aria-hidden="true" />
          </button>
          <div
            className="quick-settings-item quick-settings-runtime"
            aria-label={`${copy.runtimeEntry}: ${isDesktopRuntime() ? copy.desktopRuntime : copy.browserRuntime}`}
          >
            <MonitorCog aria-hidden="true" />
            <span>{copy.runtimeEntry}</span>
            <strong>{isDesktopRuntime() ? copy.desktopRuntime : copy.browserRuntime}</strong>
          </div>
        </div>
      </section>
    );
  }

  return (
    <EditionSettingsSurface
      activeTab={activeTab}
      closeLabel={copy.close}
      closeRef={closeRef}
      edition="field"
      onClose={onClose}
      onTabChange={setActiveTab}
      tabs={tabs}
      title={copy.title}
      consumerProfile="field"
      presentation="workspace"
      backLabel={copy.back}
      headerAction={activeTab === "course" ? (
        <a
          className="settings-course-header-action"
          href={ECE498BH_COURSE_URL}
          target="_blank"
          rel="noreferrer"
        >
          {copy.openCourse}<ArrowRight aria-hidden="true" />
        </a>
      ) : null}
    >
      <EditionSettingsPanel active={activeTab === "general"} id="general">
        <section className="settings-general-panel">
          <div className="settings-general-card settings-language-card">
            <div className="settings-card-heading">
              <span><SettingsLanguageRegionIcon region="west" />{copy.language}</span>
            </div>
            <fieldset className="launcher-language-options" aria-label={copy.language}>
              {SETTINGS_LOCALES.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={interfaceLocale === option.id ? "selected" : undefined}
                  aria-label={option.label}
                  aria-pressed={interfaceLocale === option.id}
                  onClick={() => selectLocale(option.id)}
                >
                  <SettingsLanguageRegionIcon region={option.region} />
                  <strong>{option.label}</strong>
                  <i aria-hidden="true">✓</i>
                </button>
              ))}
            </fieldset>
          </div>
          <div className="settings-general-card settings-notification-card">
            <div className="settings-card-heading">
              <span><Bell aria-hidden="true" />{copy.notifications}</span>
            </div>
            {(Object.keys(DEFAULT_NOTIFICATIONS) as NotificationPreferenceKey[]).map((key, index) => (
              <SettingsToggle
                key={key}
                checked={notifications[key]}
                disabled={key !== "master" && !notifications.master}
                label={copy.notificationLabels[index]}
                onChange={(checked) => updateNotification(key, checked)}
              />
            ))}
          </div>
        </section>
      </EditionSettingsPanel>

      <EditionSettingsPanel active={activeTab === "memory"} id="memory">
        <section className="settings-memory-panel" aria-labelledby="field-settings-memory-title">
          <h3 id="field-settings-memory-title" className="sr-only">{copy.memory}</h3>
          <div className="settings-memory-body">
            <section className="settings-memory-module settings-memory-behavior-module">
              <header className="settings-memory-module-heading">
                <h4>{copy.memoryModules[0]}</h4>
                <button
                  type="button"
                  className="settings-memory-module-save"
                  aria-label={copy.saveMemoryModules[0]}
                  title={copy.saveMemoryModules[0]}
                  onClick={() => saveFieldMemoryModule("behavior")}
                ><Save aria-hidden="true" /></button>
              </header>
              <div className="settings-memory-switches">
              <SettingsToggle
                checked={accountMemoryEnabled}
                className="settings-memory-master-toggle"
                label={<><BrainCircuit aria-hidden="true" />{copy.accountMemory}</>}
                onChange={updateAccountMemoryEnabled}
              />
              <SettingsToggle
                checked={memoryEnabled}
                disabled={!accountMemoryEnabled}
                className="settings-memory-master-toggle"
                label={<><Sparkles aria-hidden="true" />{copy.editionMemory}</>}
                onChange={updateMemoryEnabled}
              />
              <div className="settings-memory-scope-grid">
                {(Object.keys(DEFAULT_MEMORY_SCOPES) as MemoryScopeKey[]).map((key, index) => {
                  const Icon = MEMORY_SCOPE_ICONS[index];
                  return (
                    <SettingsToggle
                      key={key}
                      checked={memoryScopes[key]}
                      disabled={!accountMemoryEnabled || !memoryEnabled}
                      label={<><Icon aria-hidden="true" /><span>{copy.scopes[index]}</span></>}
                      onChange={(checked) => updateMemoryScope(key, checked)}
                    />
                  );
                })}
              </div>
              </div>
            </section>
            <section className="settings-memory-module settings-memory-domains-module">
              <header className="settings-memory-module-heading">
                <h4>{copy.memoryModules[1]}</h4>
                <button
                  type="button"
                  className="settings-memory-module-save"
                  aria-label={copy.saveMemoryModules[1]}
                  title={copy.saveMemoryModules[1]}
                  onClick={() => saveFieldMemoryModule("domains")}
                ><Save aria-hidden="true" /></button>
              </header>
              <div className="settings-memory-scope-grid settings-memory-domain-grid">
                {FIELD_MEMORY_DOMAINS.map((domain, index) => (
                  <div className="settings-memory-domain-consent" key={domain}>
                    <span>{copy.domains[index]}</span>
                    <SettingsToggle
                      checked={readMemoryDomains.includes(domain)}
                      disabled={!accountMemoryEnabled || !memoryEnabled}
                      label={copy.access[0]}
                      onChange={(checked) => toggleMemoryDomain(domain, "read", checked)}
                    />
                    <SettingsToggle
                      checked={writeMemoryDomains.includes(domain)}
                      disabled={!accountMemoryEnabled || !memoryEnabled}
                      label={copy.access[1]}
                      onChange={(checked) => toggleMemoryDomain(domain, "write", checked)}
                    />
                  </div>
                ))}
              </div>
            </section>
            <section className="settings-memory-module settings-memory-defaults-module">
              <header className="settings-memory-module-heading">
                <h4>{copy.memoryModules[2]}</h4>
                <button
                  type="button"
                  className="settings-memory-module-save"
                  aria-label={copy.saveMemoryModules[2]}
                  title={copy.saveMemoryModules[2]}
                  onClick={() => saveFieldMemoryModule("defaults")}
                ><Save aria-hidden="true" /></button>
              </header>
              <div className="settings-memory-defaults">
              <div className="settings-memory-grid">
                <label><span>{copy.defaults[0]}</span><input value={memoryDefaults.vehicle} disabled={!accountMemoryEnabled || !memoryEnabled} onChange={(event) => setMemoryDefaults((current) => ({ ...current, vehicle: event.target.value }))} /></label>
                <label><span>{copy.defaults[1]}</span><input value={memoryDefaults.map} disabled={!accountMemoryEnabled || !memoryEnabled} onChange={(event) => setMemoryDefaults((current) => ({ ...current, map: event.target.value }))} /></label>
                <label><span>{copy.defaults[2]}</span><select value={memoryDefaults.safety} disabled={!accountMemoryEnabled || !memoryEnabled} onChange={(event) => setMemoryDefaults((current) => ({ ...current, safety: event.target.value }))}><option value="strict">{locale === "zh-CN" ? "严格" : "Strict"}</option><option value="standard">{locale === "zh-CN" ? "标准" : "Standard"}</option></select></label>
                <label><span>{copy.defaults[3]}</span><select value={memoryDefaults.units} disabled={!accountMemoryEnabled || !memoryEnabled} onChange={(event) => setMemoryDefaults((current) => ({ ...current, units: event.target.value }))}><option value="metric">{locale === "zh-CN" ? "公制" : "Metric"}</option><option value="imperial">{locale === "zh-CN" ? "英制" : "Imperial"}</option></select></label>
                <label><span>{copy.defaults[4]}</span><select value={memoryDefaults.report} disabled={!accountMemoryEnabled || !memoryEnabled} onChange={(event) => setMemoryDefaults((current) => ({ ...current, report: event.target.value }))}><option value="evidence">{locale === "zh-CN" ? "证据包" : "Evidence"}</option><option value="summary">{locale === "zh-CN" ? "摘要" : "Summary"}</option></select></label>
              </div>
              </div>
            </section>
          </div>
          {memorySaveMessage ? <p className="settings-memory-message" role="status">{memorySaveMessage}</p> : null}
        </section>
      </EditionSettingsPanel>

      <EditionSettingsPanel active={activeTab === "model"} id="model">
        <section className="settings-model-panel" aria-label={copy.tabs[2]}>
          <CustomModelSettingsPanel locale={interfaceLocale} edition="field" />
        </section>
      </EditionSettingsPanel>

      <EditionSettingsPanel active={activeTab === "course"} id="course">
        <section className="settings-course-panel" aria-labelledby="settings-workspace-active-title">
          <div className="settings-course-editions">
            {(["universal", "sim", "lab", "field", "autonomy"] as const).map((edition, index) => (
              <article key={edition}>
                <BrandLockup edition={edition} />
                <p>{copy.courseOverview}</p>
                <a
                  className="settings-course-edition-link"
                  href={edition === "universal" ? "https://getdronedream.com/manual/" : "https://getdronedream.com/product/"}
                  target="_blank"
                  rel="noreferrer"
                >
                  {copy.courseActions[index === 0 ? 0 : 1]}<ArrowRight aria-hidden="true" />
                </a>
              </article>
            ))}
          </div>
        </section>
      </EditionSettingsPanel>

      <EditionSettingsPanel active={activeTab === "runtime"} id="runtime">
        <section className="settings-runtime-panel" aria-labelledby="field-settings-safety-title">
          <div className="settings-runtime-heading">
            <h3 id="field-settings-safety-title">{copy.safetyTitle}</h3>
          </div>
          <dl className="field-settings-safety" data-authority="false">
            <div><dt>{copy.executionProfile}</dt><dd>field-lightweight</dd></div>
            <div><dt>{copy.vehiclePacks}</dt><dd>0</dd></div>
            <div><dt>{copy.quorum}</dt><dd>{copy.missing}</dd></div>
            <div><dt>{copy.authority}</dt><dd><ShieldCheck aria-hidden="true" />{copy.denied}</dd></div>
          </dl>
          <SettingsUpdateCenter
            onOpenRuntimeBase={beginRuntimeBaseUpgrade}
            runtimeBaseActionDisabled={runtimeUpgradeBusy}
          />
          {runtimeUpgradeNotice ? (
            <p
              className={`field-runtime-upgrade-notice ${runtimeUpgradeNotice.tone}`}
              role={runtimeUpgradeNotice.tone === "error" ? "alert" : "status"}
            >
              {runtimeUpgradeNotice.text}
            </p>
          ) : null}
        </section>
      </EditionSettingsPanel>
    </EditionSettingsSurface>
  );
}
