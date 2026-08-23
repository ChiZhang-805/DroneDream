import {
  ArrowRight,
  Bell,
  BrainCircuit,
  GraduationCap,
  MapPinned,
  MonitorCog,
  Moon,
  Plane,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Workflow,
} from "lucide-react";
import { useRef, useState, type RefObject } from "react";

import { BrandLockup } from "../components/BrandLockup";
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
import { startRuntimeUpgrade } from "../desktop/bridge";
import { useAuthOrLocal } from "../features/auth/AuthContext";
import { localeSafeError, type InterfaceLocale } from "../i18n/I18nProvider";
import { useEditionTheme } from "../theme/EditionThemeProvider";
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

const COPY = {
  en: {
    title: "Settings",
    close: "Close settings",
    tabs: ["General", "Memory", "Model", "Safety"] as const,
    language: "Language",
    interface: "Interface",
    notifications: "Notifications",
    appearance: ["Dark", "Light", "System", "Customize"] as const,
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
    crossSession: "Cross-session memory",
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
    close: "关闭设置",
    tabs: ["常规", "记忆", "模型", "安全"] as const,
    language: "语言",
    interface: "界面",
    notifications: "通知",
    appearance: ["深色", "浅色", "跟随系统", "自定义"] as const,
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
    crossSession: "跨会话记忆",
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
  locale,
  onClose,
  onLocaleChange,
}: {
  closeRef: RefObject<HTMLButtonElement>;
  locale: FieldLocale;
  onClose: () => void;
  onLocaleChange: (locale: FieldLocale) => void;
}) {
  const [activeTab, setActiveTab] = useState<SettingsSurfaceTabId>("general");
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
  const [memoryScopes, setMemoryScopes] = useState(() =>
    readJson("dd.field.memory.scopes", DEFAULT_MEMORY_SCOPES)
  );
  const [runtimeUpgradeBusy, setRuntimeUpgradeBusy] = useState(false);
  const [runtimeUpgradeNotice, setRuntimeUpgradeNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);
  const customColorInputRef = useRef<HTMLInputElement>(null);
  const { account } = useAuthOrLocal();
  const editionTheme = useEditionTheme();
  const copy = COPY[interfaceLocale === "zh-CN" ? "zh-CN" : "en"];
  const tabs: readonly SettingsSurfaceTab[] = [
    { id: "general", label: copy.tabs[0] },
    { id: "memory", label: copy.tabs[1] },
    { id: "model", label: copy.tabs[2], disabled: !account },
    { id: "course", label: "ECE498BH" },
    { id: "runtime", label: copy.tabs[3] },
  ];

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
    try {
      window.localStorage.setItem("dd.field.memory.enabled", String(enabled));
    } catch {
      // The current session still reflects the user's selection.
    }
  };

  const updateMemoryScope = (key: MemoryScopeKey, enabled: boolean) => {
    setMemoryScopes((current) => {
      const next = { ...current, [key]: enabled };
      try {
        window.localStorage.setItem("dd.field.memory.scopes", JSON.stringify(next));
      } catch {
        // The current session still reflects the user's selection.
      }
      return next;
    });
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
          <div className="settings-general-card settings-interface-card">
            <div className="settings-card-heading">
              <span><SlidersHorizontal aria-hidden="true" />{copy.interface}</span>
            </div>
            <div className="settings-appearance-options" role="group" aria-label={copy.interface}>
              {([
                ["dark", Moon],
                ["light", Sun],
                ["system", MonitorCog],
                ["custom", Sparkles],
              ] as const).map(([appearance, Icon], index) => (
                <button
                  key={appearance}
                  type="button"
                  className={editionTheme.appearancePreference === appearance ? "selected" : undefined}
                  aria-pressed={editionTheme.appearancePreference === appearance}
                  onClick={() => {
                    editionTheme.setAppearance(appearance);
                    if (appearance === "custom") {
                      window.requestAnimationFrame(() => customColorInputRef.current?.click());
                    }
                  }}
                >
                  <Icon aria-hidden="true" />
                  <strong>{copy.appearance[index]}</strong>
                  <i aria-hidden="true">✓</i>
                </button>
              ))}
            </div>
            <input
              ref={customColorInputRef}
              className="settings-custom-color-input"
              type="color"
              tabIndex={-1}
              aria-label={copy.appearance[3]}
              value={editionTheme.customAccent}
              onChange={(event) => editionTheme.setCustomAccent(event.target.value)}
            />
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
          <div className="settings-memory-heading">
            <h3 id="field-settings-memory-title">{copy.memory}</h3>
            <span className={memoryEnabled ? "configured" : undefined}>
              {copy.memoryState[memoryEnabled ? 1 : 0]}
            </span>
          </div>
          <div className="settings-memory-body">
            <div className="settings-memory-switches">
              <SettingsToggle
                checked={memoryEnabled}
                className="settings-memory-master-toggle"
                label={<><BrainCircuit aria-hidden="true" />{copy.crossSession}</>}
                onChange={updateMemoryEnabled}
              />
              <div className="settings-memory-scope-grid">
                {(Object.keys(DEFAULT_MEMORY_SCOPES) as MemoryScopeKey[]).map((key, index) => {
                  const Icon = MEMORY_SCOPE_ICONS[index];
                  return (
                    <SettingsToggle
                      key={key}
                      checked={memoryScopes[key]}
                      disabled={!memoryEnabled}
                      label={<><Icon aria-hidden="true" /><span>{copy.scopes[index]}</span></>}
                      onChange={(checked) => updateMemoryScope(key, checked)}
                    />
                  );
                })}
              </div>
            </div>
            <div className="settings-memory-defaults">
              <div className="settings-memory-grid">
                <label><span>{copy.defaults[0]}</span><input value="My Drone" readOnly disabled={!memoryEnabled} /></label>
                <label><span>{copy.defaults[1]}</span><input value="School Map" readOnly disabled={!memoryEnabled} /></label>
                <label><span>{copy.defaults[2]}</span><select defaultValue="strict" disabled={!memoryEnabled}><option value="strict">{locale === "zh-CN" ? "严格" : "Strict"}</option></select></label>
                <label><span>{copy.defaults[3]}</span><select defaultValue="metric" disabled={!memoryEnabled}><option value="metric">{locale === "zh-CN" ? "公制" : "Metric"}</option></select></label>
                <label><span>{copy.defaults[4]}</span><select defaultValue="evidence" disabled={!memoryEnabled}><option value="evidence">{locale === "zh-CN" ? "证据包" : "Evidence"}</option></select></label>
              </div>
            </div>
          </div>
        </section>
      </EditionSettingsPanel>

      <EditionSettingsPanel active={activeTab === "model"} id="model">
        <section className="settings-model-panel" aria-label={copy.tabs[2]} />
      </EditionSettingsPanel>

      <EditionSettingsPanel active={activeTab === "course"} id="course">
        <section className="settings-course-panel" aria-labelledby="field-settings-course-title">
          <div className="settings-course-overview">
            <div className="settings-course-mark" aria-hidden="true"><GraduationCap /></div>
            <div>
              <h3 id="field-settings-course-title">ECE498BH</h3>
              <p>{copy.courseOverview}</p>
            </div>
            <a href={ECE498BH_COURSE_URL} target="_blank" rel="noreferrer">
              {copy.openCourse}<ArrowRight aria-hidden="true" />
            </a>
          </div>
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
