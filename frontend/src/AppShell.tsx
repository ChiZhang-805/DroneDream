import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ChangeEvent, MouseEvent, MutableRefObject, RefObject } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Apple,
  ArrowRight,
  Bell,
  BotMessageSquare,
  BrainCircuit,
  Camera,
  ChevronRight,
  CircleUserRound,
  Download,
  FlaskConical,
  Gift,
  GraduationCap,
  Gauge,
  History,
  ImagePlus,
  LayoutDashboard,
  LogIn,
  LogOut,
  MailCheck,
  MapPinned,
  Menu,
  Moon,
  MonitorCog,
  Navigation2,
  RadioTower,
  RefreshCcw,
  Save,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TicketCheck,
  Trophy,
  Sun,
  Trash2,
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
import { AssistantModelPicker } from "./components/AssistantModelPicker";
import { CustomModelSettingsPanel } from "./components/CustomModelSettingsPanel";
import { SettingsUpdateCenter } from "./components/SettingsUpdateCenter";
import {
  EditionSettingsPanel,
  EditionSettingsSurface,
  type SettingsSurfaceTab,
  type SettingsSurfaceTabId,
} from "./components/EditionSettingsSurface";
import {
  SETTINGS_LOCALES,
  SettingsLanguageRegionIcon,
  SettingsToggle,
} from "./components/SettingsPrimitives";
import { UniversalModeSwitch } from "./components/UniversalModeSwitch";
import {
  EDITION_BRAND_TOKENS,
  type BrandEditionId,
} from "./brand/edition-brand.generated";
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
  approveDesktopStartupGateForAccount,
  approveDesktopStartupGateWithoutCloudAuth,
  setDesktopStartupGateState,
} from "./desktop/startupGate";
import {
  AppUpdaterProvider,
  useAppUpdaterState,
} from "./desktop/updaterContext";
import {
  OPEN_APP_SETTINGS_EVENT,
  type AppSettingsTarget,
} from "./appSettings";
import { AuthCaptcha } from "./features/auth/AuthCaptcha";
import { AuthProvider, useAuth } from "./features/auth/AuthContext";
import {
  cancelDesktopBrowserSignIn,
  completeDesktopBrowserSignIn,
} from "./features/auth/desktopBrowserSignIn";
import { OPEN_ACCOUNT_DIALOG_EVENT } from "./features/auth/events";
import {
  useAdminAccess,
} from "./features/admin/AdminAccessContext";
import { AdminAccessProvider } from "./features/admin/AdminAccessProvider";
import {
  captchaProtectionConfigured,
  turnstileSiteKey,
} from "./features/auth/supabaseClient";
import { useModelAccess } from "./features/settings/ModelAccessContext";
import { ModelAccessProvider } from "./features/settings/ModelAccessProvider";
import {
  DEFAULT_MANAGED_MODEL_CATALOG,
  completeManagedModelCatalog,
  getManagedModelCatalog,
  getManagedModelUsage,
  remainingAllowanceRatio,
  managedModelAvailableForAssistant,
  redeemManagedAllowanceResetCard,
  type ManagedAllowanceResetCard,
  type ManagedModelCatalogEntry,
  type ManagedModelUsageDay,
  type ManagedModelUsageSnapshot,
} from "./features/settings/cloudModelAccess";
import {
  hasExperimentDraft,
  persistExperimentDraftsForExit,
} from "./features/experiment/draftStorage";
import {
  loadUniversalMode,
  parseUniversalMode,
  persistUniversalMode,
  UNIVERSAL_WORKSPACE_IDS,
  type UniversalWorkspaceId,
} from "./features/distribution/universalMode";
import { publicDemoConsole } from "./features/demo/publicDemo";
import { getOrganizationAccess } from "./features/organization/organizationConsole";
import {
  activeAssistantTenantContext,
  hydrateAssistantWorkspaceIndex,
  setActiveAssistantTenantContext,
} from "./features/experiment/workspaceRegistry";
import { getAssistantWorkspaceIndex } from "./features/experiment/assistantOrchestration";
import { localeSafeError, useI18n } from "./i18n/I18nProvider";
import type { InterfaceLocale, TranslationKey } from "./i18n/I18nProvider";
import type {
  Job,
  JobStatus,
  StarterExperienceTemplateKey,
  UserDefaultTrackType,
} from "./types/api";
import {
  deleteConsolePreferencesAndMemory,
  loadConsoleMemoryConsent,
  loadConsolePreferences,
  MODEL_HARNESS_MEMORY_NAMESPACES,
  saveConsoleMemoryConsent,
  saveConsolePreferences,
  type ConsoleMemoryScope,
  type ConsolePreferenceRecord,
  type ModelHarnessMemoryNamespace,
} from "./features/settings/consolePreferences";
import { ECE498BH_COURSE_URL } from "./externalLinks";
import { EditionThemeProvider, useEditionTheme } from "./theme/EditionThemeProvider";
import {
  BUILD_EDITION,
  EDITION_IS_FIXED,
  initialWorkspaceMode,
} from "./edition";

type NavigationItem = {
  to: string;
  labelKey?: TranslationKey;
  label?: string;
  end?: boolean;
  desktopTo?: string;
  requiresRuntime?: boolean;
  externalUrl?: string;
  icon: LucideIcon;
  sectionKey?: TranslationKey;
};

const CORE_NAV_ITEMS: NavigationItem[] = [
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
    to: "/scenarios",
    labelKey: "app.fixedScenarios",
    icon: MapPinned,
  },
];

const ASSISTANT_NAV_ITEM = CORE_NAV_ITEMS[0];
const DASHBOARD_NAV_ITEM = CORE_NAV_ITEMS[1];
const HISTORY_NAV_ITEM = CORE_NAV_ITEMS[2];
const SCENARIOS_NAV_ITEM = CORE_NAV_ITEMS[3];
const AUTONOMY_NAV_ITEM: NavigationItem = {
  to: "/autonomy",
  labelKey: "app.autonomyLab",
  icon: Navigation2,
};

const SIM_NAV_ITEMS: NavigationItem[] = [
  { ...ASSISTANT_NAV_ITEM, sectionKey: "app.navSectionAutonomy" },
  AUTONOMY_NAV_ITEM,
  {
    to: "/jobs/new",
    labelKey: "app.experimentBuilder",
    icon: SlidersHorizontal,
    sectionKey: "app.navSectionExperiment",
  },
  { ...DASHBOARD_NAV_ITEM, sectionKey: "app.navSectionWorkspace" },
  SCENARIOS_NAV_ITEM,
  HISTORY_NAV_ITEM,
];

const LAB_WORKSPACE_NAV_ITEMS: NavigationItem[] = [
  {
    to: "/lab",
    labelKey: "app.labWorkspace",
    end: true,
    icon: FlaskConical,
  },
  {
    to: "/lab/hardware",
    labelKey: "app.hardwareLab",
    icon: RadioTower,
  },
];

const LAB_NAV_ITEMS: NavigationItem[] = [
  { ...ASSISTANT_NAV_ITEM, sectionKey: "app.navSectionAutonomy" },
  AUTONOMY_NAV_ITEM,
  {
    to: "/jobs/new",
    labelKey: "app.experimentBuilder",
    icon: SlidersHorizontal,
    sectionKey: "app.navSectionExperiment",
  },
  LAB_WORKSPACE_NAV_ITEMS[0],
  LAB_WORKSPACE_NAV_ITEMS[1],
  { to: "/lab/validation", labelKey: "app.labValidation", icon: ShieldCheck },
  { ...HISTORY_NAV_ITEM, sectionKey: "app.navSectionRecords" },
];

const FIELD_NAV_ITEMS: NavigationItem[] = [
  { ...ASSISTANT_NAV_ITEM, sectionKey: "app.navSectionAutonomy" },
  AUTONOMY_NAV_ITEM,
  {
    to: "/field/device",
    labelKey: "app.fieldDeviceSetup",
    end: true,
    icon: RadioTower,
    sectionKey: "app.navSectionOperations",
  },
  {
    to: "/field/tuning",
    labelKey: "app.fieldTuning",
    end: true,
    icon: SlidersHorizontal,
  },
  {
    to: "/field/operations",
    labelKey: "app.fieldSafety",
    end: true,
    icon: ShieldCheck,
  },
  { ...HISTORY_NAV_ITEM, sectionKey: "app.navSectionRecords" },
];

const AUTONOMY_NAV_ITEMS: NavigationItem[] = BUILD_EDITION === "autonomy"
  ? [
      {
        to: "/autonomy",
        labelKey: "app.conversation",
        end: true,
        icon: BotMessageSquare,
        sectionKey: "app.navSectionAutonomy",
      },
      {
        to: "/autonomy/aircraft",
        labelKey: "app.autonomyAircraft",
        icon: Navigation2,
      },
      {
        to: "/autonomy/maps",
        labelKey: "app.autonomyMaps",
        icon: MapPinned,
      },
      {
        to: "/autonomy/plugins",
        labelKey: "app.autonomyPlugins",
        icon: Sparkles,
      },
      {
        to: "/autonomy/live",
        labelKey: "app.autonomyLive",
        icon: Camera,
      },
      { ...HISTORY_NAV_ITEM, sectionKey: "app.navSectionRecords" },
    ]
  : [
      { ...ASSISTANT_NAV_ITEM, sectionKey: "app.navSectionAutonomy" },
      AUTONOMY_NAV_ITEM,
      { ...HISTORY_NAV_ITEM, sectionKey: "app.navSectionRecords" },
    ];

const MODE_NAV_ITEMS: Record<UniversalWorkspaceId, NavigationItem[]> = {
  universal: [
    { ...ASSISTANT_NAV_ITEM, sectionKey: "app.navSectionAutonomy" },
    AUTONOMY_NAV_ITEM,
    DASHBOARD_NAV_ITEM,
    HISTORY_NAV_ITEM,
    SCENARIOS_NAV_ITEM,
  ],
  sim: SIM_NAV_ITEMS,
  lab: LAB_NAV_ITEMS,
  field: FIELD_NAV_ITEMS,
  autonomy: AUTONOMY_NAV_ITEMS,
};

const MODE_LANDING_PATH: Record<UniversalWorkspaceId, string> = {
  universal: "/assistant",
  sim: "/assistant",
  lab: "/assistant",
  field: "/assistant",
  autonomy: "/autonomy",
};

const EDITION_PLATFORM_LABEL: Record<BrandEditionId, TranslationKey> = {
  universal: "app.platformUniversal",
  sim: "app.platformSim",
  lab: "app.platformLab",
  field: "app.platformField",
  autonomy: "app.platformAutonomy",
};

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
  daily_usage: Array.from({ length: 365 }, (_, index) => {
    const current = new Date(Date.UTC(2025, 7, 23 + index));
    const active = index % 9 !== 0;
    const consumed = active ? ((index * 37) % 96) + 4 : 0;
    return {
      date: current.toISOString().slice(0, 10),
      consumed_ai_credits: consumed,
      request_count: active ? (index % 6) + 1 : 0,
      input_tokens: consumed * 160,
      output_tokens: consumed * 48,
      total_tokens: consumed * 208,
    };
  }),
  allowance_reset_cards: [
    {
      id: "preview-reset-full",
      number: "DD-FULL-9Q7M",
      credits: 2_000,
      kind: "full_refill",
      expires_at: "2026-08-31T23:59:59Z",
    },
    {
      id: "preview-reset-1000",
      number: "DD-1000-4N2K",
      credits: 1_000,
      kind: "fixed_credit",
      expires_at: "2026-10-31T23:59:59Z",
    },
    {
      id: "preview-reset-5000",
      number: "DD-5000-7R8P",
      credits: 5_000,
      kind: "fixed_credit",
      expires_at: "2026-12-31T23:59:59Z",
    },
    {
      id: "preview-reset-10000",
      number: "DD-10K-3X6T",
      credits: 10_000,
      kind: "fixed_credit",
      expires_at: "2027-02-28T23:59:59Z",
    },
  ],
};

const DOCS_PREVIEW_MANAGED_MODELS: ManagedModelCatalogEntry[] =
  DEFAULT_MANAGED_MODEL_CATALOG;
const ACTIVE_JOB_CHECK_TIMEOUT_MS = 2_500;
const ACTIVE_JOB_CANCEL_TIMEOUT_MS = 2_000;
const RUNTIME_EXIT_TIMEOUT_MS = 6_000;
const ACTIVE_JOB_PAGE_SIZE = 100;
const MOBILE_NAVIGATION_QUERY = "(max-width: 520px)";

function subscribeToMobileNavigation(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => undefined;
  const query = window.matchMedia(MOBILE_NAVIGATION_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function mobileNavigationSnapshot(): boolean {
  return typeof window !== "undefined"
    && Boolean(window.matchMedia?.(MOBILE_NAVIGATION_QUERY).matches);
}
const MAX_ACTIVE_JOB_PAGES_PER_STATUS = 10;

interface ExperiencePreferenceDraft {
  account_memory_enabled: boolean;
  memory_enabled: boolean;
  read_namespaces: ModelHarnessMemoryNamespace[];
  write_namespaces: ModelHarnessMemoryNamespace[];
  memory_scopes: Record<ConsoleMemoryScope, boolean>;
  default_template_key: StarterExperienceTemplateKey | null;
  default_vehicle: string | null;
  default_track_type: UserDefaultTrackType | null;
  default_altitude_m: number | null;
  default_objective: string | null;
  default_safety_profile: string | null;
  default_units: string | null;
  default_report_format: string | null;
}

const EMPTY_EXPERIENCE_PREFERENCE_DRAFT: ExperiencePreferenceDraft = {
  account_memory_enabled: false,
  memory_enabled: false,
  read_namespaces: [...MODEL_HARNESS_MEMORY_NAMESPACES],
  write_namespaces: [...MODEL_HARNESS_MEMORY_NAMESPACES],
  memory_scopes: {
    chat_preferences: true,
    experiment_defaults: true,
    device_vehicle: true,
    metrics_constraints: true,
    safety_approvals: true,
    workflow_tools: true,
    reports_delivery: true,
    collaboration_organization: true,
    files_artifacts: true,
  },
  default_template_key: null,
  default_vehicle: null,
  default_track_type: null,
  default_altitude_m: null,
  default_objective: null,
  default_safety_profile: null,
  default_units: null,
  default_report_format: null,
};
const EXPERIENCE_PREFERENCE_LOAD_FAILED = "experience-preference-load-failed";

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

const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = {
  master: true,
  experiment: true,
  assistant: true,
  updates: false,
  approval: true,
  allowance: true,
  security: true,
  runtime: true,
};

type SettingsCopy = Readonly<{
  title: string;
  tabs: readonly [string, string, string, string];
  language: string;
  interface: string;
  notifications: string;
  appearance: readonly [string, string, string, string];
  notificationLabels: readonly [string, string, string, string, string, string, string, string];
  memoryTitle: string;
  memoryEnabled: readonly [string, string];
  crossSession: string;
  memoryScopes: readonly [
    string,
    string,
    string,
    string,
    string,
    string,
    string,
    string,
    string,
  ];
  memoryDefaults: readonly [string, string, string, string, string];
  courseOpen: string;
  courseActions: readonly [string, string];
  courseEditions: readonly [string, string, string, string];
}>;

const SETTINGS_COPY: Readonly<Record<InterfaceLocale, SettingsCopy>> = {
  en: {
    title: "Settings",
    tabs: ["General", "Memory", "Model", "Runtime"],
    language: "Language",
    interface: "Interface",
    notifications: "Notifications",
    appearance: ["Dark", "Light", "System", "Customize"],
    notificationLabels: ["Allow notifications", "Experiment and task completed", "AI response completed", "Product updates", "Approval required", "Allowance or card expiring", "Security and sign-in", "Device or runtime status"],
    memoryTitle: "Memory",
    memoryEnabled: ["Memory off", "Memory on"],
    crossSession: "Cross-session memory",
    memoryScopes: ["Chat preferences", "Experiment defaults", "Device and vehicle", "Metrics and constraints", "Safety and approvals", "Workflow and tools", "Reports and delivery", "Organization collaboration", "Files and artifacts"],
    memoryDefaults: ["Default vehicle", "Default objective", "Default safety profile", "Default units", "Default report format"],
    courseOpen: "Open course",
    courseActions: ["Read manual", "Explore product"],
    courseEditions: ["Unified UAV workflow across all five editions.", "Reproducible PX4 and Gazebo experiments.", "Calibration and Sim-to-Real validation.", "Real-device tuning with safety and rollback."],
  },
  "zh-CN": {
    title: "设置",
    tabs: ["常规", "记忆", "模型", "运行环境"],
    language: "语言",
    interface: "界面",
    notifications: "通知",
    appearance: ["深色", "浅色", "跟随系统", "自定义"],
    notificationLabels: ["允许通知", "实验与任务完成", "AI 回复完成", "产品更新", "需要审批", "额度或重置卡即将到期", "安全与登录提醒", "设备或运行环境状态"],
    memoryTitle: "记忆",
    memoryEnabled: ["记忆已关闭", "记忆已开启"],
    crossSession: "跨会话记忆",
    memoryScopes: ["对话偏好", "实验默认值", "设备与机型", "指标与约束", "安全与审批", "工作流与工具", "报告与交付", "组织协作", "文件与产物"],
    memoryDefaults: ["默认机型", "默认优化目标", "默认安全配置", "默认单位制", "默认报告格式"],
    courseOpen: "打开课程",
    courseActions: ["阅读说明书", "查看产品"],
    courseEditions: ["贯通五款软件的统一无人机工作流。", "可重复的 PX4 与 Gazebo 仿真实验。", "标定与仿真到真机验证。", "具备安全边界与回滚的真机调优。"],
  },
};

const AUTONOMY_COURSE_COPY: Readonly<Record<InterfaceLocale, string>> = {
  en: "Natural-language mission planning and supervised execution.",
  "zh-CN": "自然语言任务规划与受监督执行。",
};

const MEMORY_DOMAIN_LABELS: Readonly<
  Record<InterfaceLocale, Readonly<Record<ModelHarnessMemoryNamespace, string>>>
> = {
  en: {
    "account.shared": "Shared",
    "optimization.control_tuning": "Tuning",
    "autonomy.mission": "Missions",
    "asset.qualification": "Assets",
    "experiment.simulation": "Simulation",
    "workflow.cross_edition": "Cross-edition",
    "validation.hardware": "Hardware",
    "calibration.system": "Calibration",
    "transfer.sim_to_real": "Sim → real",
    "transfer.real_to_sim": "Real → sim",
    "operations.field": "Field",
  },
  "zh-CN": {
    "account.shared": "账户共享",
    "optimization.control_tuning": "控制调优",
    "autonomy.mission": "自主任务",
    "asset.qualification": "资产认证",
    "experiment.simulation": "仿真实验",
    "workflow.cross_edition": "跨软件流程",
    "validation.hardware": "硬件验证",
    "calibration.system": "系统校准",
    "transfer.sim_to_real": "仿真→真机",
    "transfer.real_to_sim": "真机→仿真",
    "operations.field": "外场运行",
  },
};

function AllowanceCardIcon({
  card,
}: {
  card: ManagedAllowanceResetCard;
}) {
  const Icon = card.kind === "full_refill"
    ? RefreshCcw
    : card.credits >= 10_000
      ? Trophy
      : card.credits >= 5_000
        ? TicketCheck
        : Gift;
  return (
    <span
      className={`settings-reset-card-icon settings-reset-card-icon-${card.kind === "full_refill" ? "full" : card.credits}`}
      aria-hidden="true"
    >
      <Icon />
    </span>
  );
}

function AllowanceUsageHistory({
  days,
  locale,
}: {
  days: ManagedModelUsageDay[];
  locale: "en" | "zh-CN";
}) {
  const [range, setRange] = useState<7 | 30 | 365>(7);
  const copy = locale === "zh-CN"
    ? {
        title: "用量记录",
        description: "按实际完成的模型调用统计",
        sevenDays: "7 天",
        thirtyDays: "30 天",
        oneYear: "一年",
        credits: "额度",
        tokens: "Tokens",
        requests: "调用",
        empty: "该时段暂无用量",
        chart: "模型用量图",
      }
    : {
        title: "Usage history",
        description: "Completed model calls only",
        sevenDays: "7 days",
        thirtyDays: "30 days",
        oneYear: "1 year",
        credits: "Credits",
        tokens: "Tokens",
        requests: "Requests",
        empty: "No usage in this period",
        chart: "Model usage chart",
      };
  const visibleDays = days.slice(-range);
  const number = new Intl.NumberFormat(locale);
  const date = new Intl.DateTimeFormat(locale, range === 365
    ? { year: "numeric", month: "2-digit", day: "2-digit" }
    : { month: "2-digit", day: "2-digit" });
  const maxCredits = Math.max(0, ...visibleDays.map((day) => day.consumed_ai_credits));
  const tooltip = (day: ManagedModelUsageDay) => [
    date.format(new Date(`${day.date}T00:00:00Z`)),
    `${copy.credits}: ${number.format(day.consumed_ai_credits)}`,
    `${copy.tokens}: ${number.format(day.total_tokens)}`,
    `${copy.requests}: ${number.format(day.request_count)}`,
  ].join(" · ");
  const hasUsage = visibleDays.some((day) => day.consumed_ai_credits > 0);

  return (
    <section className="settings-allowance-history">
      <header>
        <div><h4>{copy.title}</h4><p>{copy.description}</p></div>
        <div className="settings-allowance-range" role="tablist" aria-label={copy.title}>
          {([[7, copy.sevenDays], [30, copy.thirtyDays], [365, copy.oneYear]] as const)
            .map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={range === value}
                tabIndex={range === value ? 0 : -1}
                className={range === value ? "is-selected" : undefined}
                onClick={() => setRange(value)}
                onKeyDown={(event) => {
                  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                  const tabs = Array.from(
                    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [],
                  );
                  if (tabs.length === 0) return;
                  const currentIndex = tabs.indexOf(event.currentTarget);
                  const nextIndex = event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? tabs.length - 1
                      : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
                  event.preventDefault();
                  const nextValue = Number(tabs[nextIndex]?.dataset.range) as 7 | 30 | 365;
                  setRange(nextValue);
                  tabs[nextIndex]?.focus();
                }}
                data-range={value}
              >{label}</button>
            ))}
        </div>
      </header>
      {visibleDays.length === 0 ? (
        <p className="settings-allowance-empty">{copy.empty}</p>
      ) : range === 365 ? (
        <div className="settings-allowance-heatmap" role="img" aria-label={copy.chart} data-testid="settings-allowance-chart">
          {visibleDays.map((day) => {
            const intensity = maxCredits <= 0
              ? 0
              : Math.max(1, Math.min(4, Math.ceil((day.consumed_ai_credits / maxCredits) * 4)));
            return <i key={day.date} data-intensity={intensity} title={tooltip(day)} aria-hidden="true" />;
          })}
        </div>
      ) : (
        <div className={`settings-allowance-bars${range === 30 ? " is-30" : ""}`} role="img" aria-label={copy.chart} data-testid="settings-allowance-chart">
          {visibleDays.map((day) => (
            <span key={day.date} title={tooltip(day)} aria-hidden="true">
              <i style={{ height: maxCredits > 0 ? `${Math.max(2, (day.consumed_ai_credits / maxCredits) * 100)}%` : "2px" }} />
              <small>{date.format(new Date(`${day.date}T00:00:00Z`))}</small>
            </span>
          ))}
        </div>
      )}
      {!hasUsage && visibleDays.length > 0 ? <p className="settings-allowance-empty">{copy.empty}</p> : null}
    </section>
  );
}

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
      <AdminAccessProvider>
        <DesktopRuntimeAccessProvider>
          <AppUpdaterProvider>
            <AccountScopedModelAccessProvider />
          </AppUpdaterProvider>
        </DesktopRuntimeAccessProvider>
      </AdminAccessProvider>
    </AuthProvider>
  );
}

function AccountScopedModelAccessProvider() {
  const auth = useAuth();
  return (
    <ModelAccessProvider accountScope={auth.account?.id ?? null}>
      <AppShellContent />
    </ModelAccessProvider>
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
  edition,
  initialPreferenceDraft,
  initialTab,
  onClose,
  onOpenAllSettings,
  onOpenExternal,
  presentation = "workspace",
  preferenceSaveQueueRef,
}: {
  access: DesktopRuntimeAccess;
  closeRef: RefObject<HTMLButtonElement>;
  edition: BrandEditionId;
  initialPreferenceDraft?: ExperiencePreferenceDraft | null;
  initialTab: SettingsSurfaceTabId;
  onClose: () => void;
  onOpenAllSettings?: (
    tab?: SettingsSurfaceTabId,
    draft?: ExperiencePreferenceDraft,
  ) => void;
  onOpenExternal: (event: MouseEvent<HTMLAnchorElement>, url: string) => void;
  presentation?: "quick" | "workspace";
  preferenceSaveQueueRef: MutableRefObject<Promise<boolean>>;
}) {
  const { locale, interfaceLocale, setLocale, t } = useI18n();
  const navigate = useNavigate();
  const settingsCopy = SETTINGS_COPY[interfaceLocale];
  const editionTheme = useEditionTheme();
  const setAppearancePreference = editionTheme.setAppearance;
  const setCustomAccentPreference = editionTheme.setCustomAccent;
  const auth = useAuth();
  const {
    settings: modelAccess,
    selectAccessMode,
    selectManagedModel,
  } = useModelAccess();
  const docsPreview = import.meta.env.DEV
    && new URLSearchParams(window.location.search).has("docsPreview");
  const localDesktopPreferences = !auth.account && !docsPreview && isDesktopRuntime();
  const [managedUsage, setManagedUsage] =
    useState<ManagedModelUsageSnapshot | null>(
      docsPreview ? DOCS_PREVIEW_MANAGED_USAGE : null,
    );
  const [managedUsageState, setManagedUsageState] =
    useState<"idle" | "loading" | "ready" | "error">(
      docsPreview ? "ready" : "idle",
    );
  const [managedUsageError, setManagedUsageError] = useState<string | null>(null);
  const [managedModels, setManagedModels] = useState<ManagedModelCatalogEntry[]>(
    docsPreview ? DOCS_PREVIEW_MANAGED_MODELS : DEFAULT_MANAGED_MODEL_CATALOG,
  );
  const [selectedAllowanceResetCardId, setSelectedAllowanceResetCardId] =
    useState("");
  const [allowanceResetMenuOpen, setAllowanceResetMenuOpen] = useState(false);
  const [allowanceResetState, setAllowanceResetState] =
    useState<"idle" | "redeeming" | "success" | "error">("idle");
  const [allowanceResetConfirmationOpen, setAllowanceResetConfirmationOpen] = useState(false);
  const [allowanceResetMessage, setAllowanceResetMessage] = useState<string | null>(null);
  const customColorInputRef = useRef<HTMLInputElement>(null);
  const [experiencePreferenceDraft, setExperiencePreferenceDraft] =
    useState<ExperiencePreferenceDraft>(
      initialPreferenceDraft ?? EMPTY_EXPERIENCE_PREFERENCE_DRAFT,
    );
  const [experiencePreferenceState, setExperiencePreferenceState] =
    useState<"blocked" | "loading" | "ready" | "saving" | "saved" | "error">(
      initialPreferenceDraft
        ? "ready"
        : auth.account || docsPreview || localDesktopPreferences
          ? "loading"
          : "blocked",
    );
  const [experiencePreferenceMessage, setExperiencePreferenceMessage] =
    useState<string | null>(null);
  const [confirmExperiencePreferenceDelete, setConfirmExperiencePreferenceDelete] =
    useState(false);
  const preferenceHydratedRef = useRef(false);
  const preferenceSaveTimerRef = useRef<number | null>(null);
  const preferenceSaveRequestRef = useRef<(() => Promise<boolean>) | null>(null);
  const preferenceComponentMountedRef = useRef(true);
  const [notificationPreferences, setNotificationPreferences] =
    useState<NotificationPreferences>(() => {
      try {
        const stored = window.localStorage.getItem("dd.notification-preferences.v1");
        return stored
          ? { ...DEFAULT_NOTIFICATION_PREFERENCES, ...JSON.parse(stored) as Partial<NotificationPreferences> }
          : DEFAULT_NOTIFICATION_PREFERENCES;
      } catch {
        return DEFAULT_NOTIFICATION_PREFERENCES;
      }
    });
  const preferenceBoundary = useMemo(() => {
    if (!auth.account || docsPreview) return null;
    const tenant = activeAssistantTenantContext(auth.account.id);
    return {
      userId: auth.account.id,
      tenantId: tenant.tenantId,
      organizationId: tenant.organizationId,
      workspaceId: `console-${edition}`,
      edition,
    };
  }, [auth.account, docsPreview, edition]);
  const consolePreferenceRecord = useCallback((): ConsolePreferenceRecord => ({
    interface_locale: interfaceLocale,
    appearance_mode: editionTheme.appearancePreference,
    custom_accent: editionTheme.customAccent,
    notifications: notificationPreferences,
    memory_enabled: experiencePreferenceDraft.memory_enabled,
    memory_scopes: experiencePreferenceDraft.memory_scopes,
    defaults: {
      template: experiencePreferenceDraft.default_template_key,
      vehicle: experiencePreferenceDraft.default_vehicle,
      track: experiencePreferenceDraft.default_track_type,
      altitude_m: experiencePreferenceDraft.default_altitude_m,
      objective: experiencePreferenceDraft.default_objective,
      safety_profile: experiencePreferenceDraft.default_safety_profile,
      units: experiencePreferenceDraft.default_units,
      report_format: experiencePreferenceDraft.default_report_format,
    },
  }), [
    editionTheme.appearancePreference,
    editionTheme.customAccent,
    experiencePreferenceDraft,
    interfaceLocale,
    notificationPreferences,
  ]);
  const consoleMemoryConsentRecord = useCallback(() => ({
    memory_enabled: experiencePreferenceDraft.account_memory_enabled,
    read_namespaces: experiencePreferenceDraft.read_namespaces,
    write_namespaces: experiencePreferenceDraft.write_namespaces,
    memory_scopes: experiencePreferenceDraft.memory_scopes,
  }), [experiencePreferenceDraft]);
  const updateNotificationPreference = (
    key: NotificationPreferenceKey,
    checked: boolean,
  ) => {
    setNotificationPreferences((current) => {
      const next = key === "master"
        ? Object.fromEntries(
            Object.keys(current).map((preference) => [preference, checked]),
          ) as NotificationPreferences
        : { ...current, [key]: checked };
      window.localStorage.setItem("dd.notification-preferences.v1", JSON.stringify(next));
      return next;
    });
  };
  const openSubscriptionPage = useCallback((
    event: MouseEvent<HTMLAnchorElement>,
  ) => {
    if (!isDesktopRuntime()) return;
    event.preventDefault();
    void import("@tauri-apps/plugin-opener")
      .then(({ openUrl }) =>
        openUrl("https://getdronedream.com/pricing/")
      )
      .catch(() => undefined);
  }, []);
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
      setManagedUsageError(localeSafeError(error, locale, {
        zh: "模型用量暂不可用。",
        en: t("settings.model.usageUnavailable"),
      }));
    }
  }, [auth.account, docsPreview, locale, modelAccess.accessMode, t]);
  useEffect(() => {
    void refreshManagedUsage();
  }, [refreshManagedUsage]);
  useEffect(() => {
    if (modelAccess.accessMode !== "platform") return;
    if (docsPreview) {
      setManagedModels(DOCS_PREVIEW_MANAGED_MODELS);
      return;
    }
    if (!auth.account) return;
    let active = true;
    void getManagedModelCatalog()
      .then((catalog) => {
        if (!active) return;
        setManagedModels(completeManagedModelCatalog(catalog.models));
      })
      .catch(() => {
        if (!active) return;
        setManagedModels(DEFAULT_MANAGED_MODEL_CATALOG);
      });
    return () => {
      active = false;
    };
  }, [auth.account, docsPreview, modelAccess.accessMode, t]);
  useEffect(() => {
    const availableModels = managedModels.filter(managedModelAvailableForAssistant);
    if (availableModels.length === 0) return;
    if (!availableModels.some((model) =>
      model.provider === modelAccess.managedProvider
        && model.model === modelAccess.managedModel
    )) {
      selectManagedModel(availableModels[0].provider, availableModels[0].model);
    }
  }, [
    managedModels,
    modelAccess.managedModel,
    modelAccess.managedProvider,
    selectManagedModel,
  ]);
  useEffect(() => {
    preferenceHydratedRef.current = false;
    if (initialPreferenceDraft) {
      setExperiencePreferenceDraft(initialPreferenceDraft);
      setExperiencePreferenceState("ready");
      setExperiencePreferenceMessage(null);
      setConfirmExperiencePreferenceDelete(false);
      preferenceHydratedRef.current = true;
      return undefined;
    }
    if (!preferenceBoundary && !docsPreview && !localDesktopPreferences) {
      setExperiencePreferenceState("blocked");
      setExperiencePreferenceMessage(null);
      setConfirmExperiencePreferenceDelete(false);
      return undefined;
    }
    let active = true;
    setExperiencePreferenceState("loading");
    setExperiencePreferenceMessage(null);
    const load = docsPreview || localDesktopPreferences
      ? Promise.resolve([null, null] as const)
      : preferenceBoundary
        ? Promise.all([
          loadConsolePreferences(preferenceBoundary),
          loadConsoleMemoryConsent(preferenceBoundary),
        ])
        : Promise.resolve([null, null] as const);
    void load
      .then(([preferences, consent]) => {
        if (!active) return;
        if (preferences || consent) {
          const defaults = preferences?.defaults ?? {};
          setExperiencePreferenceDraft({
            ...EMPTY_EXPERIENCE_PREFERENCE_DRAFT,
            account_memory_enabled: consent?.memory_enabled ?? false,
            memory_enabled: preferences?.memory_enabled ?? false,
            read_namespaces: consent?.read_namespaces ?? [
              ...MODEL_HARNESS_MEMORY_NAMESPACES,
            ],
            write_namespaces: consent?.write_namespaces ?? [
              ...MODEL_HARNESS_MEMORY_NAMESPACES,
            ],
            memory_scopes: {
              ...EMPTY_EXPERIENCE_PREFERENCE_DRAFT.memory_scopes,
              ...(preferences?.memory_scopes ?? {}),
            },
            default_template_key: (defaults.template ?? null) as StarterExperienceTemplateKey | null,
            default_vehicle: typeof defaults.vehicle === "string" ? defaults.vehicle : null,
            default_track_type: (defaults.track ?? null) as UserDefaultTrackType | null,
            default_altitude_m: typeof defaults.altitude_m === "number" ? defaults.altitude_m : null,
            default_objective: typeof defaults.objective === "string" ? defaults.objective : null,
            default_safety_profile: typeof defaults.safety_profile === "string" ? defaults.safety_profile : null,
            default_units: typeof defaults.units === "string" ? defaults.units : null,
            default_report_format: typeof defaults.report_format === "string" ? defaults.report_format : null,
          });
          if (preferences) {
            setNotificationPreferences({
              ...DEFAULT_NOTIFICATION_PREFERENCES,
              ...preferences.notifications,
            });
            setLocale(preferences.interface_locale);
            setAppearancePreference(preferences.appearance_mode);
            setCustomAccentPreference(preferences.custom_accent);
          }
        }
        preferenceHydratedRef.current = true;
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
  }, [
    docsPreview,
    initialPreferenceDraft,
    localDesktopPreferences,
    preferenceBoundary,
    setAppearancePreference,
    setCustomAccentPreference,
    setLocale,
  ]);
  useEffect(() => {
    if (
      docsPreview ||
      !preferenceBoundary ||
      !preferenceHydratedRef.current ||
      experiencePreferenceState === "blocked" ||
      experiencePreferenceState === "loading" ||
      experiencePreferenceState === "saving"
    ) {
      if (preferenceSaveTimerRef.current !== null) {
        window.clearTimeout(preferenceSaveTimerRef.current);
        preferenceSaveTimerRef.current = null;
      }
      preferenceSaveRequestRef.current = null;
      return undefined;
    }
    const saveCurrentPreferences = async () => {
      try {
        await Promise.all([
          saveConsolePreferences(preferenceBoundary, consolePreferenceRecord()),
          saveConsoleMemoryConsent(preferenceBoundary, consoleMemoryConsentRecord()),
        ]);
        return true;
      } catch {
        if (preferenceComponentMountedRef.current) {
          setExperiencePreferenceMessage(t("settings.memory.saveFailed"));
        }
        return false;
      }
    };
    preferenceSaveRequestRef.current = saveCurrentPreferences;
    if (preferenceSaveTimerRef.current !== null) {
      window.clearTimeout(preferenceSaveTimerRef.current);
    }
    preferenceSaveTimerRef.current = window.setTimeout(() => {
      preferenceSaveTimerRef.current = null;
      const request = preferenceSaveRequestRef.current;
      preferenceSaveRequestRef.current = null;
      if (request) {
        preferenceSaveQueueRef.current = preferenceSaveQueueRef.current.then(request);
      }
    }, 450);
    return undefined;
  }, [
    consolePreferenceRecord,
    consoleMemoryConsentRecord,
    docsPreview,
    experiencePreferenceState,
    preferenceBoundary,
    preferenceSaveQueueRef,
    t,
  ]);
  const flushPendingPreferenceSave = async () => {
    if (preferenceSaveTimerRef.current !== null) {
      window.clearTimeout(preferenceSaveTimerRef.current);
      preferenceSaveTimerRef.current = null;
    }
    const pendingSave = preferenceSaveRequestRef.current;
    preferenceSaveRequestRef.current = null;
    if (pendingSave) {
      preferenceSaveQueueRef.current = preferenceSaveQueueRef.current.then(pendingSave);
    }
    return preferenceSaveQueueRef.current;
  };
  const flushPendingPreferenceSaveForNavigation = async () => {
    const save = flushPendingPreferenceSave();
    await Promise.race([
      save.then(() => undefined),
      new Promise<void>((resolve) => window.setTimeout(resolve, 200)),
    ]);
  };
  useEffect(() => {
    preferenceComponentMountedRef.current = true;
    return () => {
      preferenceComponentMountedRef.current = false;
      if (preferenceSaveTimerRef.current !== null) {
        window.clearTimeout(preferenceSaveTimerRef.current);
        preferenceSaveTimerRef.current = null;
      }
      const pendingSave = preferenceSaveRequestRef.current;
      preferenceSaveRequestRef.current = null;
      if (pendingSave) {
        preferenceSaveQueueRef.current = preferenceSaveQueueRef.current.then(pendingSave);
      }
    };
  }, [preferenceSaveQueueRef]);
  const saveExperiencePreferences = async () => {
    if (
      (!preferenceBoundary && !docsPreview && !localDesktopPreferences) ||
      experiencePreferenceState === "blocked" ||
      experiencePreferenceState === "loading" ||
      experiencePreferenceState === "saving"
    ) {
      return;
    }
    setExperiencePreferenceState("saving");
    setExperiencePreferenceMessage(null);
    try {
      if (preferenceBoundary) {
        await Promise.all([
          saveConsolePreferences(preferenceBoundary, consolePreferenceRecord()),
          saveConsoleMemoryConsent(preferenceBoundary, consoleMemoryConsentRecord()),
        ]);
      } else if (localDesktopPreferences) {
        // Pre-login settings remain usable, but account-scoped Memory is never
        // sent to the Runtime without an authenticated account boundary.
      }
      preferenceHydratedRef.current = true;
      setExperiencePreferenceState("saved");
      setExperiencePreferenceMessage(t("settings.memory.saved"));
    } catch {
      setExperiencePreferenceState("error");
      setExperiencePreferenceMessage(t("settings.memory.saveFailed"));
    }
  };
  const deleteExperiencePreferences = async () => {
    if (
      (!preferenceBoundary && !docsPreview && !localDesktopPreferences) ||
      experiencePreferenceState === "blocked" ||
      experiencePreferenceState === "loading" ||
      experiencePreferenceState === "saving"
    ) {
      return;
    }
    setExperiencePreferenceState("saving");
    setExperiencePreferenceMessage(null);
    try {
      const deletedCount = preferenceBoundary
        ? await deleteConsolePreferencesAndMemory(preferenceBoundary)
        : localDesktopPreferences
          ? 0
          : 0;
      preferenceHydratedRef.current = false;
      setExperiencePreferenceDraft(EMPTY_EXPERIENCE_PREFERENCE_DRAFT);
      setConfirmExperiencePreferenceDelete(false);
      setExperiencePreferenceState("ready");
      setExperiencePreferenceMessage(
        preferenceBoundary
          ? t("settings.memory.deleted", { count: deletedCount })
          : locale === "zh-CN"
            ? "已删除本地个人默认值；未删除账户记忆。"
            : "Personal defaults deleted; 0 memory rows erased.",
      );
    } catch {
      setExperiencePreferenceState("error");
      setExperiencePreferenceMessage(t("settings.memory.deleteFailed"));
    }
  };
  const numberFormatter = new Intl.NumberFormat(interfaceLocale);
  const experiencePreferenceControlsDisabled =
    experiencePreferenceState === "blocked" ||
    experiencePreferenceState === "loading" ||
    experiencePreferenceState === "saving";
  const remainingCreditRatio = managedUsage
    ? remainingAllowanceRatio(
        managedUsage.usage.remaining_ai_credits,
        managedUsage.plan.included_ai_credits,
      )
    : 0;
  const allowanceResetCards = managedUsage?.allowance_reset_cards;
  const allowanceResetCardFormatter = new Intl.DateTimeFormat(
    interfaceLocale,
    { dateStyle: "medium", timeStyle: "short" },
  );
  const allowanceResetCopy = {
    en: {
      cards: "Allowance reset cards",
      ready: "Ready to use",
      full: "Full refill",
      fullCard: "Full refill card",
      empty: "No cards available",
      expires: "Expires",
      use: "Use card",
      using: "Using…",
      confirm: "Confirm",
      cancel: "Cancel",
      refresh: "Refresh usage",
    },
    "zh-CN": {
      cards: "额度重置卡",
      ready: "准备使用",
      full: "全额恢复",
      fullCard: "全额恢复卡",
      empty: "暂无可用额度卡",
      expires: "有效期至",
      use: "使用重置卡",
      using: "使用中…",
      confirm: "确认兑换",
      cancel: "取消",
      refresh: "刷新用量",
    },
  }[interfaceLocale];
  useEffect(() => {
    if (!allowanceResetCards || allowanceResetCards.length === 0) {
      setSelectedAllowanceResetCardId("");
      return;
    }
    if (!allowanceResetCards.some((card) => card.id === selectedAllowanceResetCardId)) {
      setSelectedAllowanceResetCardId(allowanceResetCards[0]?.id ?? "");
    }
  }, [allowanceResetCards, selectedAllowanceResetCardId]);
  const redeemAllowanceResetCard = async () => {
    if (!selectedAllowanceResetCardId || allowanceResetState === "redeeming") return;
    if (!allowanceResetConfirmationOpen) {
      setAllowanceResetConfirmationOpen(true);
      return;
    }
    setAllowanceResetState("redeeming");
    setAllowanceResetMessage(null);
    try {
      if (docsPreview) {
        const selectedCard = DOCS_PREVIEW_MANAGED_USAGE.allowance_reset_cards?.find(
          (card) => card.id === selectedAllowanceResetCardId,
        );
        setManagedUsage((current) => current ? {
          ...current,
          usage: {
            ...current.usage,
            consumed_ai_credits: selectedCard?.kind === "full_refill"
              ? 0
              : Math.max(0, current.usage.consumed_ai_credits - (selectedCard?.credits ?? 0)),
            remaining_ai_credits: selectedCard?.kind === "full_refill"
              ? current.plan.included_ai_credits
              : Math.min(
                  current.plan.included_ai_credits,
                  current.usage.remaining_ai_credits + (selectedCard?.credits ?? 0),
                ),
          },
          allowance_reset_cards: current.allowance_reset_cards?.filter(
            (card) => card.id !== selectedAllowanceResetCardId,
          ),
        } : current);
        if (!selectedCard) throw new Error("RESET_CARD_NOT_FOUND");
      } else {
        setManagedUsage(await redeemManagedAllowanceResetCard(selectedAllowanceResetCardId));
      }
      setAllowanceResetState("success");
      setAllowanceResetConfirmationOpen(false);
      setAllowanceResetMessage(
        locale === "zh-CN" ? "额度卡已成功兑换。" : "The allowance card was redeemed.",
      );
    } catch (error) {
      setAllowanceResetState("error");
      setAllowanceResetMessage(localeSafeError(error, locale, {
        zh: "重置卡暂时无法使用。",
        en: "The reset card could not be redeemed.",
      }));
    }
  };
  const [activeSettingsTab, setActiveSettingsTab] =
    useState<SettingsSurfaceTabId>(initialTab);
  const settingsTabs: readonly SettingsSurfaceTab[] = [
    { id: "general", label: settingsCopy.tabs[0] },
    { id: "memory", label: settingsCopy.tabs[1] },
    {
      id: "model",
      label: interfaceLocale === "zh-CN" ? "模型与额度" : "Models & allowance",
      disabled: !auth.account,
    },
    { id: "course", label: "ECE498BH" },
    ...(access.desktopRuntime
      ? [{
          id: "runtime",
          label: interfaceLocale === "zh-CN" ? "Runtime 与更新" : "Runtime & updates",
        } as const]
      : []),
  ];
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

  if (presentation === "quick") {
    const quickCopy = interfaceLocale === "zh-CN"
      ? {
          title: "设置",
          language: "语言",
          appearance: "外观",
          accountMemory: "账户记忆",
          editionMemory: "本软件记忆",
          model: "默认平台模型",
          runtime: "Runtime 与更新",
          allSettings: "全部设置",
          dark: "深色",
          light: "浅色",
          system: "跟随系统",
          custom: "自定义",
        }
      : {
          title: "Settings",
          language: "Language",
          appearance: "Appearance",
          accountMemory: "Account memory",
          editionMemory: "This edition's memory",
          model: "Default platform model",
          runtime: "Runtime & updates",
          allSettings: "All settings",
          dark: "Dark",
          light: "Light",
          system: "System",
          custom: "Custom",
        };
    const availableModels = managedModels.filter(managedModelAvailableForAssistant);
    const selectedModel = `${modelAccess.managedProvider}:${modelAccess.managedModel}`;

    return (
      <section
        className="quick-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="quick-settings-title"
        data-brand-edition={edition}
      >
        <header className="quick-settings-heading">
          <h2 id="quick-settings-title">{quickCopy.title}</h2>
          <button
            ref={closeRef}
            type="button"
            className="launcher-settings-close"
            aria-label={t("app.closeSettings")}
            title={t("app.closeSettings")}
            onClick={onClose}
          >
            <X aria-hidden="true" />
          </button>
        </header>
        <div className="quick-settings-grid">
          <div className="quick-settings-item quick-settings-language">
            <span>{quickCopy.language}</span>
            <div role="group" aria-label={t("app.interfaceLanguage")}>
              {SETTINGS_LOCALES.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={interfaceLocale === option.id ? "selected" : undefined}
                  aria-pressed={interfaceLocale === option.id}
                  onClick={() => setLocale(option.id)}
                >
                  <SettingsLanguageRegionIcon region={option.region} />
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
          </div>
          <label className="quick-settings-item" htmlFor="quick-settings-appearance">
            <span>{quickCopy.appearance}</span>
            <select
              id="quick-settings-appearance"
              value={editionTheme.appearancePreference}
              onChange={(event) => {
                const value = event.target.value as typeof editionTheme.appearancePreference;
                editionTheme.setAppearance(value);
                if (value === "custom") {
                  window.requestAnimationFrame(() => customColorInputRef.current?.click());
                }
              }}
            >
              <option value="dark">{quickCopy.dark}</option>
              <option value="light">{quickCopy.light}</option>
              <option value="system">{quickCopy.system}</option>
              <option value="custom">{quickCopy.custom}</option>
            </select>
            <input
              ref={customColorInputRef}
              className="settings-custom-color-input"
              type="color"
              tabIndex={-1}
              aria-label={interfaceLocale === "zh-CN" ? "选择自定义主题色" : "Choose a custom theme color"}
              value={editionTheme.customAccent}
              onChange={(event) => editionTheme.setCustomAccent(event.target.value)}
            />
          </label>
          {auth.account || docsPreview ? (
            <>
              <div className="quick-settings-item quick-settings-memory">
                <SettingsToggle
                  checked={experiencePreferenceDraft.account_memory_enabled}
                  disabled={experiencePreferenceControlsDisabled}
                  label={<><BrainCircuit aria-hidden="true" /><span>{quickCopy.accountMemory}</span></>}
                  onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                    ...current,
                    account_memory_enabled: checked,
                  }))}
                />
                <SettingsToggle
                  checked={experiencePreferenceDraft.memory_enabled}
                  disabled={experiencePreferenceControlsDisabled || !experiencePreferenceDraft.account_memory_enabled}
                  label={<><Sparkles aria-hidden="true" /><span>{quickCopy.editionMemory}</span></>}
                  onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                    ...current,
                    memory_enabled: checked,
                  }))}
                />
              </div>
              <div className="quick-settings-item quick-settings-model">
                <span>{quickCopy.model}</span>
                <AssistantModelPicker
                  ariaLabel={quickCopy.model}
                  chooseModelLabel={quickCopy.model}
                  defaultGroupLabel={interfaceLocale === "zh-CN" ? "平台模型" : "Platform models"}
                  customGroupLabel={interfaceLocale === "zh-CN" ? "自定义" : "Custom"}
                  addCustomModelLabel={interfaceLocale === "zh-CN" ? "添加模型" : "Add model"}
                  temporarilyUnavailableLabel={interfaceLocale === "zh-CN" ? "暂不可用" : "Unavailable"}
                  defaultModels={availableModels}
                  customProfiles={[]}
                  selectedDefault={availableModels.find((model) => `${model.provider}:${model.model}` === selectedModel) ?? null}
                  selectedCustomId={null}
                  disabled={availableModels.length === 0}
                  showCustomSection={false}
                  onSelectDefault={(selected) => {
                    selectAccessMode("platform");
                    selectManagedModel(selected.provider, selected.model);
                  }}
                  onSelectCustom={() => undefined}
                  onOpenSettings={() => onOpenAllSettings?.("model")}
                />
              </div>
            </>
          ) : null}
          {access.desktopRuntime ? (
            <button
              type="button"
              className="quick-settings-item quick-settings-runtime"
              onClick={async () => {
                await flushPendingPreferenceSaveForNavigation();
                onOpenAllSettings?.(
                  "runtime",
                  preferenceHydratedRef.current ? experiencePreferenceDraft : undefined,
                );
              }}
            >
              <MonitorCog aria-hidden="true" />
              <span>{quickCopy.runtime}</span>
              <strong data-health={level}>{statusLabel}</strong>
              <ChevronRight aria-hidden="true" />
            </button>
          ) : null}
        </div>
        <footer className="quick-settings-footer">
          <button
            type="button"
            className="btn btn-primary"
            onClick={async () => {
              await flushPendingPreferenceSaveForNavigation();
              onOpenAllSettings?.(
                "general",
                preferenceHydratedRef.current ? experiencePreferenceDraft : undefined,
              );
            }}
          >
            <Settings aria-hidden="true" />
            {quickCopy.allSettings}
          </button>
        </footer>
      </section>
    );
  }

  return (
    <EditionSettingsSurface
      activeTab={activeSettingsTab}
      closeLabel={t("app.closeSettings")}
      closeRef={closeRef}
      edition={edition}
      onClose={onClose}
      onTabChange={setActiveSettingsTab}
      tabs={settingsTabs}
      title={settingsCopy.title}
      consumerProfile={edition}
      presentation="workspace"
      backLabel={interfaceLocale === "zh-CN" ? "返回应用" : "Back to app"}
    >
      <EditionSettingsPanel active={activeSettingsTab === "general"} id="general">
        <section className="settings-general-panel">
          <div className="settings-general-card settings-language-card">
            <div className="settings-card-heading">
              <span><SettingsLanguageRegionIcon region="west" />{settingsCopy.language}</span>
            </div>
            <fieldset className="launcher-language-options" aria-label={t("app.interfaceLanguage")}>
              {SETTINGS_LOCALES.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={interfaceLocale === option.id ? "selected" : undefined}
                  aria-label={option.label}
                  aria-pressed={interfaceLocale === option.id}
                  onClick={() => setLocale(option.id)}
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
              <span><SlidersHorizontal aria-hidden="true" />{settingsCopy.interface}</span>
            </div>
            <div
              className="settings-appearance-options"
              role="group"
              aria-label={t("settings.general.appearance")}
            >
              <button
                type="button"
                className={editionTheme.appearancePreference === "dark" ? "selected" : undefined}
                aria-pressed={editionTheme.appearancePreference === "dark"}
                onClick={() => editionTheme.setAppearance("dark")}
              >
                <Moon aria-hidden="true" />
                <strong>{settingsCopy.appearance[0]}</strong>
                <i aria-hidden="true">✓</i>
              </button>
              <button
                type="button"
                className={editionTheme.appearancePreference === "light" ? "selected" : undefined}
                aria-pressed={editionTheme.appearancePreference === "light"}
                onClick={() => editionTheme.setAppearance("light")}
              >
                <Sun aria-hidden="true" />
                <strong>{settingsCopy.appearance[1]}</strong>
                <i aria-hidden="true">✓</i>
              </button>
              <button
                type="button"
                className={editionTheme.appearancePreference === "system" ? "selected" : undefined}
                aria-pressed={editionTheme.appearancePreference === "system"}
                onClick={() => editionTheme.setAppearance("system")}
              >
                <MonitorCog aria-hidden="true" />
                <strong>{settingsCopy.appearance[2]}</strong>
                <i aria-hidden="true">✓</i>
              </button>
              <button
                type="button"
                className={editionTheme.appearancePreference === "custom" ? "selected" : undefined}
                aria-pressed={editionTheme.appearancePreference === "custom"}
                onClick={() => {
                  editionTheme.setAppearance("custom");
                  window.requestAnimationFrame(() => customColorInputRef.current?.click());
                }}
              >
                <Sparkles aria-hidden="true" />
                <strong>{settingsCopy.appearance[3]}</strong>
                <i aria-hidden="true">✓</i>
              </button>
            </div>
            <input
              ref={customColorInputRef}
              id="settings_custom_accent"
              className="settings-custom-color-input"
              type="color"
              tabIndex={-1}
              aria-label={locale === "zh-CN" ? "选择自定义主题色" : "Choose a custom theme color"}
              value={editionTheme.customAccent}
              onChange={(event) => editionTheme.setCustomAccent(event.target.value)}
            />
          </div>
          <div className="settings-general-card settings-notification-card">
            <div className="settings-card-heading">
              <span><Bell aria-hidden="true" />{settingsCopy.notifications}</span>
            </div>
            <SettingsToggle
              checked={notificationPreferences.master}
              label={settingsCopy.notificationLabels[0]}
              onChange={(checked) => updateNotificationPreference("master", checked)}
            />
            <SettingsToggle
              checked={notificationPreferences.experiment}
              disabled={!notificationPreferences.master}
              label={settingsCopy.notificationLabels[1]}
              onChange={(checked) => updateNotificationPreference("experiment", checked)}
            />
            <SettingsToggle
              checked={notificationPreferences.assistant}
              disabled={!notificationPreferences.master}
              label={settingsCopy.notificationLabels[2]}
              onChange={(checked) => updateNotificationPreference("assistant", checked)}
            />
            <SettingsToggle
              checked={notificationPreferences.updates}
              disabled={!notificationPreferences.master}
              label={settingsCopy.notificationLabels[3]}
              onChange={(checked) => updateNotificationPreference("updates", checked)}
            />
            <SettingsToggle
              checked={notificationPreferences.approval}
              disabled={!notificationPreferences.master}
              label={settingsCopy.notificationLabels[4]}
              onChange={(checked) => updateNotificationPreference("approval", checked)}
            />
            <SettingsToggle
              checked={notificationPreferences.allowance}
              disabled={!notificationPreferences.master}
              label={settingsCopy.notificationLabels[5]}
              onChange={(checked) => updateNotificationPreference("allowance", checked)}
            />
            <SettingsToggle
              checked={notificationPreferences.security}
              disabled={!notificationPreferences.master}
              label={settingsCopy.notificationLabels[6]}
              onChange={(checked) => updateNotificationPreference("security", checked)}
            />
            <SettingsToggle
              checked={notificationPreferences.runtime}
              disabled={!notificationPreferences.master}
              label={settingsCopy.notificationLabels[7]}
              onChange={(checked) => updateNotificationPreference("runtime", checked)}
            />
          </div>
        </section>
      </EditionSettingsPanel>
      <EditionSettingsPanel active={activeSettingsTab === "course"} id="course">
        <section className="settings-course-panel" aria-labelledby="settings-course-title">
          <div className="settings-course-overview">
            <div className="settings-course-mark" aria-hidden="true">
              <GraduationCap />
            </div>
            <h3 id="settings-course-title">ECE498BH</h3>
            <a
              href={ECE498BH_COURSE_URL}
              target="_blank"
              rel="noreferrer"
              onClick={(event) => onOpenExternal(event, ECE498BH_COURSE_URL)}
            >
              {settingsCopy.courseOpen}
              <ArrowRight aria-hidden="true" />
            </a>
          </div>
          <div className="settings-course-editions" aria-label={locale === "zh-CN" ? "DroneDream 五款软件" : "DroneDream editions"}>
            {([
              ["universal", settingsCopy.courseEditions[0]],
              ["sim", settingsCopy.courseEditions[1]],
              ["lab", settingsCopy.courseEditions[2]],
              ["field", settingsCopy.courseEditions[3]],
              ["autonomy", AUTONOMY_COURSE_COPY[locale]],
            ] as const).map(([courseEdition, description]) => (
              <article key={courseEdition}>
                <BrandLockup edition={courseEdition} />
                <p>{description}</p>
                <Link
                  className="settings-course-edition-link"
                  to={courseEdition === "universal"
                    ? "/manual/"
                    : courseEdition === "autonomy"
                      ? "/autonomy"
                      : "/product/"}
                  onClick={onClose}
                >
                  {courseEdition === "universal"
                    ? settingsCopy.courseActions[0]
                    : settingsCopy.courseActions[1]}
                  <ArrowRight aria-hidden="true" />
                </Link>
              </article>
            ))}
          </div>
        </section>
      </EditionSettingsPanel>
      <EditionSettingsPanel active={activeSettingsTab === "memory"} id="memory">
        <section className="settings-memory-panel" aria-labelledby="settings-memory-title">
        <div className="settings-memory-heading">
          <div>
            <h3
              id="settings-memory-title"
              className={presentation === "workspace" ? "sr-only" : undefined}
            >
              {settingsCopy.memoryTitle}
            </h3>
          </div>
          <span className={experiencePreferenceDraft.account_memory_enabled && experiencePreferenceDraft.memory_enabled ? "configured" : undefined}>
            {settingsCopy.memoryEnabled[
              experiencePreferenceDraft.account_memory_enabled && experiencePreferenceDraft.memory_enabled ? 1 : 0
            ]}
          </span>
        </div>
        <div className="settings-memory-body">
          <div className="settings-memory-switches">
            <SettingsToggle
              checked={experiencePreferenceDraft.account_memory_enabled}
              className="settings-memory-master-toggle"
              disabled={experiencePreferenceControlsDisabled}
              label={<><BrainCircuit aria-hidden="true" /><span>{t("settings.memory.accountConsent")}</span></>}
              onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                ...current,
                account_memory_enabled: checked,
              }))}
            />
            <SettingsToggle
              checked={experiencePreferenceDraft.memory_enabled}
              className="settings-memory-master-toggle"
              disabled={experiencePreferenceControlsDisabled || !experiencePreferenceDraft.account_memory_enabled}
              label={<><BrainCircuit aria-hidden="true" /><span>{t("settings.memory.editionAccess")}</span></>}
              onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                ...current,
                memory_enabled: checked,
              }))}
            />
            <div className="settings-memory-scope-grid" aria-label={locale === "zh-CN" ? "记忆范围" : "Memory scope"}>
              {([
                ["chat_preferences", Sparkles, settingsCopy.memoryScopes[0]],
                ["experiment_defaults", SlidersHorizontal, settingsCopy.memoryScopes[1]],
                ["device_vehicle", RadioTower, settingsCopy.memoryScopes[2]],
                ["metrics_constraints", Gauge, settingsCopy.memoryScopes[3]],
                ["safety_approvals", ShieldCheck, settingsCopy.memoryScopes[4]],
                ["workflow_tools", BotMessageSquare, settingsCopy.memoryScopes[5]],
                ["reports_delivery", Save, settingsCopy.memoryScopes[6]],
                ["collaboration_organization", CircleUserRound, settingsCopy.memoryScopes[7]],
                ["files_artifacts", ImagePlus, settingsCopy.memoryScopes[8]],
              ] as const).map(([scope, ScopeIcon, label]) => (
                <SettingsToggle
                  key={scope}
                  checked={experiencePreferenceDraft.memory_scopes[scope]}
                  disabled={experiencePreferenceControlsDisabled || !experiencePreferenceDraft.account_memory_enabled || !experiencePreferenceDraft.memory_enabled}
                  label={<><ScopeIcon aria-hidden="true" /><span>{label}</span></>}
                  onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                    ...current,
                    memory_scopes: { ...current.memory_scopes, [scope]: checked },
                  }))}
                />
              ))}
            </div>
            <div className="settings-memory-scope-grid settings-memory-domain-grid" aria-label={t("settings.memory.domainConsent")}>
              {MODEL_HARNESS_MEMORY_NAMESPACES.map((namespace) => {
                const readable = experiencePreferenceDraft.read_namespaces.includes(namespace);
                const writable = experiencePreferenceDraft.write_namespaces.includes(namespace);
                return (
                  <div key={namespace} className="settings-memory-domain-consent">
                    <span title={namespace}>{MEMORY_DOMAIN_LABELS[locale][namespace]}</span>
                    <SettingsToggle
                      checked={readable}
                      disabled={experiencePreferenceControlsDisabled || !experiencePreferenceDraft.account_memory_enabled}
                      label={t("settings.memory.allowRead")}
                      onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                        ...current,
                        read_namespaces: checked
                          ? [...new Set([...current.read_namespaces, namespace])]
                          : current.read_namespaces.filter((value) => value !== namespace),
                      }))}
                    />
                    <SettingsToggle
                      checked={writable}
                      disabled={experiencePreferenceControlsDisabled || !experiencePreferenceDraft.account_memory_enabled}
                      label={t("settings.memory.allowWrite")}
                      onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                        ...current,
                        write_namespaces: checked
                          ? [...new Set([...current.write_namespaces, namespace])]
                          : current.write_namespaces.filter((value) => value !== namespace),
                      }))}
                    />
                  </div>
                );
              })}
            </div>
          </div>
          <div className="settings-memory-defaults">
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
          <label htmlFor="settings_default_vehicle">
            <span>{settingsCopy.memoryDefaults[0]}</span>
            <select
              id="settings_default_vehicle"
              value={experiencePreferenceDraft.default_vehicle ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_vehicle: event.target.value || null,
              }))}
            >
              <option value="">{t("settings.memory.noDefault")}</option>
              <option value="x500">PX4 x500</option>
              <option value="iris">PX4 Iris</option>
              <option value="custom">{locale === "zh-CN" ? "自定义机型" : "Custom vehicle"}</option>
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
          <label htmlFor="settings_default_objective">
            <span>{settingsCopy.memoryDefaults[1]}</span>
            <select
              id="settings_default_objective"
              value={experiencePreferenceDraft.default_objective ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_objective: event.target.value || null,
              }))}
            >
              <option value="">{t("settings.memory.noDefault")}</option>
              <option value="tracking">{locale === "zh-CN" ? "跟踪精度" : "Tracking accuracy"}</option>
              <option value="robustness">{locale === "zh-CN" ? "抗扰鲁棒性" : "Disturbance robustness"}</option>
              <option value="efficiency">{locale === "zh-CN" ? "能耗效率" : "Energy efficiency"}</option>
            </select>
          </label>
          <label htmlFor="settings_default_safety">
            <span>{settingsCopy.memoryDefaults[2]}</span>
            <select
              id="settings_default_safety"
              value={experiencePreferenceDraft.default_safety_profile ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_safety_profile: event.target.value || null,
              }))}
            >
              <option value="">{t("settings.memory.noDefault")}</option>
              <option value="conservative">{locale === "zh-CN" ? "保守" : "Conservative"}</option>
              <option value="standard">{locale === "zh-CN" ? "标准" : "Standard"}</option>
              <option value="lab-guarded">{locale === "zh-CN" ? "实验室受控" : "Lab guarded"}</option>
            </select>
          </label>
          <label htmlFor="settings_default_units">
            <span>{settingsCopy.memoryDefaults[3]}</span>
            <select
              id="settings_default_units"
              value={experiencePreferenceDraft.default_units ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_units: event.target.value || null,
              }))}
            >
              <option value="">{t("settings.memory.noDefault")}</option>
              <option value="metric">{locale === "zh-CN" ? "公制" : "Metric"}</option>
              <option value="imperial">{locale === "zh-CN" ? "英制" : "Imperial"}</option>
            </select>
          </label>
          <label htmlFor="settings_default_report">
            <span>{settingsCopy.memoryDefaults[4]}</span>
            <select
              id="settings_default_report"
              value={experiencePreferenceDraft.default_report_format ?? ""}
              disabled={experiencePreferenceControlsDisabled}
              onChange={(event) => setExperiencePreferenceDraft((current) => ({
                ...current,
                default_report_format: event.target.value || null,
              }))}
            >
              <option value="">{t("settings.memory.noDefault")}</option>
              <option value="pdf">PDF</option>
              <option value="html">HTML</option>
              <option value="both">{locale === "zh-CN" ? "PDF 与 HTML" : "PDF and HTML"}</option>
            </select>
          </label>
            </div>
            <div className="settings-memory-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={experiencePreferenceControlsDisabled}
            onClick={() => void saveExperiencePreferences()}
          >
            <Save aria-hidden="true" />
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
              <Trash2 aria-hidden="true" />{t("settings.memory.delete")}
            </button>
          ) : (
            <div
              className="settings-memory-delete-confirm"
              role="group"
              aria-label={locale === "zh-CN" ? "删除所有已保存的默认值和结构化记忆？" : "Delete all saved defaults and structured memory?"}
            >
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
          </div>
        </div>
        {experiencePreferenceState === "blocked" ? (
          <p className="settings-memory-message" role="status">
            {t("settings.memory.runtimeRequired")}
          </p>
        ) : null}
        {experiencePreferenceMessage && experiencePreferenceMessage !== EXPERIENCE_PREFERENCE_LOAD_FAILED ? (
          <p
            className="settings-memory-message"
            role={experiencePreferenceState === "error" ? "alert" : "status"}
          >
            {experiencePreferenceMessage}
          </p>
        ) : null}
        </section>
      </EditionSettingsPanel>
      <EditionSettingsPanel active={activeSettingsTab === "model"} id="model">
        <section
          className={`settings-model-panel${modelAccess.accessMode === "byok" ? " settings-model-panel-byok" : ""}`}
          aria-labelledby="settings-model-title"
        >
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
            <div className="settings-managed-model-row">
              <span>{locale === "zh-CN" ? "包含的模型" : "Included model"}</span>
              <AssistantModelPicker
                ariaLabel={locale === "zh-CN" ? "包含的模型" : "Included model"}
                chooseModelLabel={locale === "zh-CN" ? "选择模型" : "Choose model"}
                defaultGroupLabel={locale === "zh-CN" ? "默认" : "Default"}
                customGroupLabel={locale === "zh-CN" ? "自定义" : "Custom"}
                addCustomModelLabel={locale === "zh-CN" ? "添加自定义模型" : "Add custom model"}
                temporarilyUnavailableLabel={locale === "zh-CN" ? "暂时不可用" : "Temporarily unavailable"}
                defaultModels={managedModels}
                customProfiles={[]}
                selectedDefault={managedModels.find((model) =>
                  model.provider === modelAccess.managedProvider
                    && model.model === modelAccess.managedModel
                    && managedModelAvailableForAssistant(model)
                ) ?? null}
                selectedCustomId={null}
                disabled={!managedModels.some(managedModelAvailableForAssistant)}
                onSelectDefault={(model) => selectManagedModel(model.provider, model.model)}
                onSelectCustom={() => undefined}
                onOpenSettings={() => undefined}
                showCustomSection={false}
              />
            </div>
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
            {!auth.account && !docsPreview ? (
              <p className="settings-model-usage-message">
                {t("settings.model.signInForAllowance")}
              </p>
            ) : managedUsage ? (
              <>
                <div className="settings-model-quota-heading">
                  <span>{t("settings.model.remainingAllowance")}</span>
                  <strong>
                    {numberFormatter.format(managedUsage.usage.remaining_ai_credits)}
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
                  aria-valuenow={managedUsage.usage.remaining_ai_credits}
                >
                  <span style={{ width: `${remainingCreditRatio}%` }} />
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
                <AllowanceUsageHistory
                  days={managedUsage.daily_usage ?? []}
                  locale={locale === "zh-CN" ? "zh-CN" : "en"}
                />
                <div className="settings-model-reset-row">
                  <div className="settings-model-reset-summary">
                    <span>{allowanceResetCopy.cards}</span>
                    <strong>{allowanceResetCards?.length ?? 0}</strong>
                    <span>{allowanceResetCopy.ready}</span>
                  </div>
                  <div className="settings-model-reset-controls">
                    <div className="settings-reset-card-picker">
                      <button
                        type="button"
                        className={`settings-reset-card-trigger${selectedAllowanceResetCardId ? " has-card" : ""}`}
                        disabled={!allowanceResetCards?.length}
                        aria-expanded={allowanceResetMenuOpen}
                        aria-haspopup="listbox"
                        onClick={() => setAllowanceResetMenuOpen((open) => !open)}
                      >
                        {(() => {
                          const card = allowanceResetCards?.find((candidate) => candidate.id === selectedAllowanceResetCardId);
                          return card ? (
                            <>
                              <AllowanceCardIcon card={card} />
                              <span className="settings-reset-card-trigger-copy">
                                <strong>{card.kind === "full_refill"
                                  ? allowanceResetCopy.full
                                  : `+${numberFormatter.format(card.credits)}`}</strong>
                                <small>
                                  · {allowanceResetCopy.expires}{" "}
                                  {allowanceResetCardFormatter.format(new Date(card.expires_at))}
                                </small>
                              </span>
                              <ChevronRight className="settings-reset-card-trigger-arrow" aria-hidden="true" />
                            </>
                          ) : <span>{allowanceResetCopy.empty}</span>;
                        })()}
                      </button>
                      {allowanceResetMenuOpen && allowanceResetCards?.length ? (
                        <div className="settings-reset-card-menu" role="listbox">
                          {allowanceResetCards.map((card) => (
                            <button
                              key={card.id}
                              type="button"
                              role="option"
                              aria-selected={card.id === selectedAllowanceResetCardId}
                              onClick={() => {
                                setSelectedAllowanceResetCardId(card.id);
                                setAllowanceResetConfirmationOpen(false);
                                setAllowanceResetMenuOpen(false);
                              }}
                            >
                              <AllowanceCardIcon card={card} />
                              <span>
                                <strong>{card.kind === "full_refill"
                                  ? allowanceResetCopy.fullCard
                                  : `+${numberFormatter.format(card.credits)} ${t("settings.model.credits")}`}</strong>
                                <small>{allowanceResetCopy.expires} {allowanceResetCardFormatter.format(new Date(card.expires_at))}</small>
                              </span>
                              {card.id === selectedAllowanceResetCardId ? <i aria-hidden="true">✓</i> : null}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="settings-model-reset-actions">
                      <button
                        type="button"
                        className="btn settings-model-reset-action"
                        disabled={!selectedAllowanceResetCardId || allowanceResetState === "redeeming"}
                        onClick={() => void redeemAllowanceResetCard()}
                      >
                        {allowanceResetState === "redeeming"
                          ? allowanceResetCopy.using
                          : allowanceResetConfirmationOpen
                            ? allowanceResetCopy.confirm
                            : allowanceResetCopy.use}
                      </button>
                      {allowanceResetConfirmationOpen ? (
                        <button
                          type="button"
                          className="btn settings-model-reset-cancel"
                          onClick={() => setAllowanceResetConfirmationOpen(false)}
                        >
                          {allowanceResetCopy.cancel}
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
                {allowanceResetMessage ? (
                  <p
                    className="settings-model-reset-message"
                    role={allowanceResetState === "error" ? "alert" : "status"}
                  >
                    {allowanceResetMessage}
                  </p>
                ) : null}
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
                  {allowanceResetCopy.refresh}
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <CustomModelSettingsPanel locale={locale} edition={edition} />
        )}
        </section>
      </EditionSettingsPanel>
      {access.desktopRuntime ? (
        <EditionSettingsPanel active={activeSettingsTab === "runtime"} id="runtime">
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
                  {uniqueDetails.slice(0, 4).map((detail) => <li key={detail}>{detail}</li>)}
                  {uniqueDetails.length > 4 ? (
                    <li>{locale === "zh-CN"
                      ? `另有 ${uniqueDetails.length - 4} 项诊断信息`
                      : `${uniqueDetails.length - 4} more diagnostic items`}</li>
                  ) : null}
                </ul>
              </div>
            </details>
          ) : null}
          <SettingsUpdateCenter
            onOpenRuntimeBase={() => {
              onClose();
              navigate("/desktop/setup");
            }}
          />
          </section>
        </EditionSettingsPanel>
      ) : null}
    </EditionSettingsSurface>
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
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const returnButtonRef = useRef<HTMLButtonElement>(null);
  const paragraphKey: TranslationKey = state.hasDraft
    ? state.activeJobsUnknown
      ? "exitGuard.draftActiveUnknown"
      : state.activeJobCount > 0
        ? "exitGuard.draftActive"
        : "exitGuard.draft"
    : state.activeJobsUnknown
      ? "exitGuard.activeUnknown"
      : "exitGuard.active";

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const backdrop = backdropRef.current;
    const parent = backdrop?.parentElement;
    const siblings = parent && backdrop
      ? Array.from(parent.children)
        .filter((element): element is HTMLElement => (
          element instanceof HTMLElement && element !== backdrop
        ))
        .map((element) => ({
          element,
          inert: element.hasAttribute("inert"),
          ariaHidden: element.getAttribute("aria-hidden"),
        }))
      : [];
    for (const { element } of siblings) {
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    }

    const focusFrame = window.requestAnimationFrame(() => returnButtonRef.current?.focus());
    const keepFocusInside = (event: globalThis.KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (!dialog) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onReturn();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.closest("[inert]"));
      if (controls.length === 0) {
        event.preventDefault();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keepFocusInside, true);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", keepFocusInside, true);
      for (const { element, inert, ariaHidden } of siblings) {
        if (!inert) element.removeAttribute("inert");
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      }
      window.requestAnimationFrame(() => {
        const fallback = document.querySelector<HTMLElement>(
          '.settings-workspace-sidebar [role="tab"][aria-selected="true"], .launcher-settings-button, .account-button',
        );
        const target = previousFocus && previousFocus.isConnected && previousFocus !== document.body
          ? previousFocus
          : fallback;
        if (target && !target.closest("[inert]")) target.focus();
      });
    };
  }, [onReturn]);

  return (
    <div ref={backdropRef} className="app-exit-backdrop" role="presentation">
      <section
        ref={dialogRef}
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
          <button ref={returnButtonRef} type="button" className="btn" onClick={onReturn}>
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
    browserSignIn: "Continue securely in browser",
    browserSignInWaiting: "Waiting for browser authorization…",
    browserSignInBody:
      "Your browser verifies the account and returns only this edition's session to DroneDream.",
    browserSignInFailed: "Browser sign-in did not complete. Try again.",
    cancelBrowserSignIn: "Cancel",
    browserRuntimeRequired: "Prepare and start DroneDreamRuntime before account authorization.",
    openEnvironment: "Open Environment",
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
    cloudWorkspace: "Free",
    editProfile: "Edit profile",
    remainingAllowance: "Token",
    allowanceUnavailable: "Unavailable",
    loadingAllowance: "Loading…",
    settings: "Settings",
    signOutFailed: "Sign out failed. Try again.",
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
    browserSignIn: "在浏览器中安全登录",
    browserSignInWaiting: "正在等待浏览器授权…",
    browserSignInBody: "浏览器负责核验账号，并只把当前版本的会话安全交还给 DroneDream。",
    browserSignInFailed: "浏览器登录未完成，请重试。",
    cancelBrowserSignIn: "取消",
    browserRuntimeRequired: "请先准备并启动 DroneDreamRuntime，再进行账号授权。",
    openEnvironment: "打开运行环境",
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
    cloudWorkspace: "Free",
    editProfile: "编辑账户",
    remainingAllowance: "Token",
    allowanceUnavailable: "暂不可用",
    loadingAllowance: "读取中…",
    settings: "设置",
    signOutFailed: "退出登录失败，请重试。",
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

function normalizedPlanName(value: string | null | undefined): "Free" | "Plus" | "Pro" {
  const plan = value?.trim().toLocaleLowerCase() ?? "";
  if (plan.includes("pro")) return "Pro";
  if (plan.includes("plus")) return "Plus";
  return "Free";
}

function AccountPlanLabel({ authenticated }: { authenticated: boolean }) {
  const [plan, setPlan] = useState<"Free" | "Plus" | "Pro">("Free");

  useEffect(() => {
    if (!authenticated) {
      setPlan("Free");
      return undefined;
    }
    let active = true;
    void getManagedModelUsage()
      .then((snapshot) => {
        if (active) setPlan(normalizedPlanName(snapshot.plan.name));
      })
      .catch(() => {
        if (active) setPlan("Free");
      });
    return () => {
      active = false;
    };
  }, [authenticated]);

  return <>{plan}</>;
}

function AccountMenuPopover({
  menuRef,
  onClose,
  onOpenAllowance,
  onOpenSettings,
}: {
  menuRef: RefObject<HTMLDivElement>;
  onClose: () => void;
  onOpenAllowance: () => void;
  onOpenSettings: () => void;
}) {
  const auth = useAuth();
  const { interfaceLocale } = useI18n();
  const accountLocale = interfaceLocale === "en" ? "en" : "zh-CN";
  const copy = ACCOUNT_COPY[accountLocale];
  const [usage, setUsage] = useState<ManagedModelUsageSnapshot | null>(null);
  const [usageState, setUsageState] = useState<"loading" | "ready" | "error">("loading");
  const [signOutPending, setSignOutPending] = useState(false);
  const [signOutError, setSignOutError] = useState(false);

  useEffect(() => {
    let active = true;
    setUsageState("loading");
    void getManagedModelUsage()
      .then((snapshot) => {
        if (!active) return;
        setUsage(snapshot);
        setUsageState("ready");
      })
      .catch(() => {
        if (!active) return;
        setUsage(null);
        setUsageState("error");
      });
    return () => {
      active = false;
    };
  }, []);

  const ratio = usage
    ? remainingAllowanceRatio(
        usage.usage.remaining_ai_credits,
        usage.plan.included_ai_credits,
      )
    : 0;

  const signOut = async () => {
    setSignOutPending(true);
    setSignOutError(false);
    try {
      await auth.signOut();
      onClose();
    } catch {
      setSignOutError(true);
      setSignOutPending(false);
    }
  };

  return (
    <div ref={menuRef} className="account-menu-popover" role="menu" aria-label={copy.account}>
      <button type="button" className="account-menu-row account-menu-token" role="menuitem" onClick={onOpenAllowance}>
        <Gauge aria-hidden="true" strokeWidth={1.8} />
        <span>{copy.remainingAllowance}</span>
        <strong>
          {usageState === "loading"
            ? "…"
            : usageState === "ready" && usage
              ? `${Math.round(ratio)}%`
              : "—"}
        </strong>
      </button>
      <button type="button" className="account-menu-row" role="menuitem" onClick={onOpenSettings}>
        <Settings aria-hidden="true" strokeWidth={1.8} />
        <span>{copy.settings}</span>
      </button>
      <button type="button" className="account-menu-row" role="menuitem" disabled={signOutPending} onClick={() => void signOut()}>
        <LogOut aria-hidden="true" strokeWidth={1.8} />
        <span>{copy.signOut}</span>
      </button>
      {signOutError ? <p role="alert">{copy.signOutFailed}</p> : null}
    </div>
  );
}

export function AccountDialog({
  closeRef,
  required,
  edition,
  desktopBrowserAuthReady = false,
  onOpenDesktopSetup,
  onClose,
}: {
  closeRef: RefObject<HTMLButtonElement>;
  required: boolean;
  edition: BrandEditionId;
  desktopBrowserAuthReady?: boolean;
  onOpenDesktopSetup?: () => void;
  onClose: () => void;
}) {
  const { locale } = useI18n();
  const copy = ACCOUNT_COPY[locale];
  const auth = useAuth();
  const desktopRuntime = isDesktopRuntime();
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
  const [browserAuthWaiting, setBrowserAuthWaiting] = useState(false);
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
  const browserAuthControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    setDisplayName(auth.account?.displayName ?? "");
  }, [auth.account?.displayName]);

  const startDesktopBrowserSignIn = useCallback(async () => {
    if (!desktopRuntime || browserAuthControllerRef.current) return;
    const controller = new AbortController();
    browserAuthControllerRef.current = controller;
    setError(null);
    setBrowserAuthWaiting(true);
    try {
      await completeDesktopBrowserSignIn(locale, { signal: controller.signal });
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      if (mountedRef.current && !/cancelled/iu.test(message)) {
        setError(copy.browserSignInFailed);
      }
    } finally {
      if (browserAuthControllerRef.current === controller) {
        browserAuthControllerRef.current = null;
        if (mountedRef.current) setBrowserAuthWaiting(false);
      }
    }
  }, [copy.browserSignInFailed, desktopRuntime, locale]);

  const cancelDesktopSignIn = useCallback(async () => {
    const controller = browserAuthControllerRef.current;
    if (!desktopRuntime || !controller) return;
    await cancelDesktopBrowserSignIn(controller);
  }, [desktopRuntime]);

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
      const controller = browserAuthControllerRef.current;
      if (controller) void cancelDesktopBrowserSignIn(controller);
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
      setError(localeSafeError(reason, locale, {
        zh: "账户请求失败。",
        en: "Account request failed.",
      }));
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
      setError(localeSafeError(reason, locale, {
        zh: copy.cropFailed,
        en: copy.cropFailed,
      }));
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
      setError(localeSafeError(reason, locale, {
        zh: copy.cropFailed,
        en: copy.cropFailed,
      }));
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
            <button
              type="button"
              className="account-avatar-change-button"
              aria-label={copy.choosePhoto}
              title={copy.choosePhoto}
              disabled={pending}
              onClick={() => avatarInputRef.current?.click()}
            >
              <AccountAvatar
                account={auth.account}
                className="account-avatar"
              />
            </button>
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
      ) : desktopRuntime ? (
        <div className="account-desktop-browser-auth">
          <p>{desktopBrowserAuthReady
            ? copy.browserSignInBody
            : copy.browserRuntimeRequired}</p>
          {desktopBrowserAuthReady ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={browserAuthWaiting}
              onClick={() => void startDesktopBrowserSignIn()}
            >
              <LogIn aria-hidden="true" strokeWidth={1.85} />
              {browserAuthWaiting ? copy.browserSignInWaiting : copy.browserSignIn}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              onClick={onOpenDesktopSetup}
            >
              <MonitorCog aria-hidden="true" strokeWidth={1.85} />
              {copy.openEnvironment}
            </button>
          )}
          {desktopBrowserAuthReady && browserAuthWaiting ? (
            <button type="button" className="btn" onClick={() => void cancelDesktopSignIn()}>
              {copy.cancelBrowserSignIn}
            </button>
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
        edition={edition}
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
  const navigate = useNavigate();
  const desktopRuntime = isDesktopRuntime();
  const runtimeAccess = useDesktopRuntimeAccess();
  const auth = useAuth();
  const adminAccess = useAdminAccess();
  const updater = useAppUpdaterState();

  useEffect(() => {
    const ownerId = auth.account?.id;
    if (!ownerId) return;
    let active = true;
    const hydrateTenant = (organizationId: string | null) => {
      void Promise.allSettled(
        (["universal", "sim", "lab", "field", "autonomy"] as const).map((edition) =>
          getAssistantWorkspaceIndex(edition, ownerId, organizationId)
        ),
      ).then((results) => {
        if (!active) return;
        const indexes = results.flatMap((result) =>
          result.status === "fulfilled" ? result.value : []
        );
        hydrateAssistantWorkspaceIndex(ownerId, indexes);
      }).catch(() => {
        // The local registry remains usable while the authenticated server
        // index is offline. No workspace from another boundary is adopted.
      });
    };
    // Default to the personal tenant while the server-authoritative membership
    // resolver is loading. A stale organization cache is never displayed.
    setActiveAssistantTenantContext(ownerId, {
      tenantId: ownerId,
      organizationId: null,
    });
    if (desktopRuntime || !publicDemoConsole) return () => {
      active = false;
    };
    hydrateTenant(null);
    void getOrganizationAccess()
      .then((access) => {
        if (!active) return;
        const organizationId = access.authorized ? access.organization_id : null;
        setActiveAssistantTenantContext(ownerId, {
          tenantId: organizationId ?? ownerId,
          organizationId,
        });
        if (organizationId) hydrateTenant(organizationId);
      })
      .catch(() => {
        // The personal boundary remains active. Organization workspaces are
        // hidden until membership can be verified by the server.
      });
    return () => {
      active = false;
    };
  }, [auth.account?.id, desktopRuntime]);
  const { locale, t } = useI18n();
  const accountCopy = ACCOUNT_COPY[locale];
  const mobileNavigationEnabled = useSyncExternalStore(
    subscribeToMobileNavigation,
    mobileNavigationSnapshot,
    () => false,
  );
  const [launcherSettingsOpen, setLauncherSettingsOpen] = useState(false);
  const [settingsWorkspaceOpen, setSettingsWorkspaceOpen] = useState(false);
  const [settingsInitialTab, setSettingsInitialTab] =
    useState<SettingsSurfaceTabId>("general");
  const [settingsPreferenceHandoff, setSettingsPreferenceHandoff] =
    useState<ExperiencePreferenceDraft | null>(null);
  const [universalMode, setUniversalMode] = useState(() => {
    const requestedEdition = new URLSearchParams(location.search).get("edition");
    return initialWorkspaceMode(
      requestedEdition && UNIVERSAL_WORKSPACE_IDS.includes(
          requestedEdition as UniversalWorkspaceId,
        )
        ? parseUniversalMode(requestedEdition)
        : loadUniversalMode(),
    );
  });
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [externalNavigationError, setExternalNavigationError] = useState<string | null>(null);
  const [exitPrompt, setExitPrompt] = useState<ExitPromptState | null>(null);
  const launcherSettingsButtonRef = useRef<HTMLButtonElement>(null);
  const launcherSettingsCloseRef = useRef<HTMLButtonElement>(null);
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const accountCloseRef = useRef<HTMLButtonElement>(null);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileMenuPanelRef = useRef<HTMLDivElement>(null);
  const settingsWorkspaceOpenerRef = useRef<"account" | "settings">("settings");
  const settingsPreferenceSaveQueueRef = useRef<Promise<boolean>>(Promise.resolve(true));
  const desktopWindowRef = useRef<DesktopWindowHandle | null>(null);
  const currentPathRef = useRef(location.pathname);
  const exitPromptRef = useRef<ExitPromptState | null>(null);
  const exitCheckInFlightRef = useRef(false);
  const exitApprovedRef = useRef(false);
  const launcherMode = desktopRuntime && location.pathname === "/desktop/setup";
  const experimentWizardMode = location.pathname === "/jobs/new";
  const activeThemeEdition: BrandEditionId = EDITION_IS_FIXED
    ? BUILD_EDITION
    : launcherMode
      ? "universal"
      : universalMode;
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
  const accountDialogRequired = accountRequired
    && !desktopRuntime
    && !launcherMode;
  const accountDialogOpen = accountOpen || accountDialogRequired;
  const mobileMenuExpanded = mobileNavigationEnabled && mobileMenuOpen;
  const sidebarUpdateVisible = desktopRuntime && [
    "available",
    "downloading",
    "installing",
    "engineUpdateDeferred",
    "reconcilingEngine",
    "engineError",
    "componentAvailable",
    "installingComponents",
    "componentUpdateDeferred",
    "componentError",
    "runtimeBaseRequired",
    "error",
  ].includes(updater.status);
  const sidebarUpdateBusy = [
    "downloading",
    "installing",
    "reconcilingEngine",
    "installingComponents",
  ].includes(updater.status);

  useEffect(() => {
    if (!EDITION_IS_FIXED) persistUniversalMode(universalMode);
  }, [universalMode]);
  useEffect(() => {
    if (EDITION_IS_FIXED || location.pathname !== "/assistant") return;
    const requestedEdition = new URLSearchParams(location.search).get("edition");
    if (
      requestedEdition
      && UNIVERSAL_WORKSPACE_IDS.includes(requestedEdition as UniversalWorkspaceId)
    ) {
      setUniversalMode(parseUniversalMode(requestedEdition));
    }
  }, [location.pathname, location.search]);
  const handleUniversalModeChange = useCallback((mode: UniversalWorkspaceId) => {
    if (EDITION_IS_FIXED) return;
    setUniversalMode(mode);
    setMobileMenuOpen(false);
    navigate(MODE_LANDING_PATH[mode]);
  }, [navigate]);
  const navigationItems = EDITION_IS_FIXED
    ? BUILD_EDITION === "sim"
      ? SIM_NAV_ITEMS
      : BUILD_EDITION === "lab"
        ? LAB_NAV_ITEMS
        : BUILD_EDITION === "field"
          ? FIELD_NAV_ITEMS
          : AUTONOMY_NAV_ITEMS
    : MODE_NAV_ITEMS[universalMode];
  const sidebarUpdateLabel = updater.status === "available"
    ? updater.error
      ? t("updater.sidebarDeferred")
      : t("updater.sidebarAvailable")
    : updater.status === "componentAvailable"
      ? t("updater.sidebarComponents")
    : updater.status === "installingComponents"
      ? t("updater.components")
    : updater.status === "runtimeBaseRequired"
      ? t("updater.sidebarRuntimeBase")
      : sidebarUpdateBusy
        ? t("updater.sidebarProgress")
        : t("updater.sidebarRetry");
  const handleSidebarUpdate = useCallback(() => {
    if (updater.status === "available") {
      void updater.installAvailableUpdate();
      return;
    }
    if (updater.status === "engineUpdateDeferred") {
      void updater.reconcileEnginePack();
      return;
    }
    if (updater.status === "componentAvailable") {
      void updater.installComponentUpdates();
      return;
    }
    if (
      updater.status === "componentUpdateDeferred"
      || updater.status === "componentError"
    ) {
      void updater.checkForUpdates();
      return;
    }
    if (updater.status === "runtimeBaseRequired") {
      navigate("/desktop/setup");
      return;
    }
    if (updater.status === "engineError") {
      void updater.reconcileEnginePack();
      return;
    }
    if (updater.status === "error") {
      void updater.checkForUpdates();
    }
  }, [navigate, updater]);
  const openExternalNavigation = useCallback((
    event: MouseEvent<HTMLAnchorElement>,
    url: string,
  ) => {
    if (!desktopRuntime) return;
    event.preventDefault();
    setExternalNavigationError(null);
    void import("@tauri-apps/plugin-opener")
      .then(({ openUrl }) => openUrl(url))
      .catch(() => setExternalNavigationError(t("app.externalOpenFailed")));
  }, [desktopRuntime, t]);

  useEffect(() => {
    // The launcher owns a strict two-stage flow: environment first, browser
    // authentication only after the user selects the sole sign-in action at
    // 100%. The workspace gate below therefore runs only after navigation away
    // from the launcher.
    if (!desktopRuntime || launcherMode) return;
    if (
      updater.status === "checking" ||
      updater.status === "downloading" ||
      updater.status === "installing" ||
      updater.status === "reconcilingEngine" ||
      updater.status === "installingComponents"
    ) {
      setDesktopStartupGateState("checking", {
        accountId: auth.account?.id ?? null,
      });
      return;
    }
    if (
      (updater.status === "available" && updater.updateRequired) ||
      updater.status === "engineError" ||
      ([
        "componentAvailable",
        "componentUpdateDeferred",
        "componentError",
      ].includes(updater.status) && updater.updateRequired) ||
      updater.status === "runtimeBaseRequired"
    ) {
      setDesktopStartupGateState("blocked", {
        accountId: auth.account?.id ?? null,
        error: updater.error
          ? localeSafeError(updater.error, locale, {
              zh: "必须先完成 DroneDream 更新，才能进入工作区。",
              en: "The DroneDream update must be installed before entering the workspace.",
            })
          : locale === "zh-CN"
            ? `必须先安装 DroneDream ${updater.availableVersion ?? "更新"}，才能进入工作区。`
            : `DroneDream ${updater.availableVersion ?? "update"} must be installed before entering the workspace.`,
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
        error: locale === "zh-CN"
          ? "本地运行环境尚未通过启动检查。"
          : "The local runtime has not passed its startup checks.",
      });
      return;
    }
    if (!auth.configured) {
      if (import.meta.env.DEV || import.meta.env.MODE === "test") {
        approveDesktopStartupGateWithoutCloudAuth();
      } else {
        setDesktopStartupGateState("blocked", {
          error: locale === "zh-CN"
            ? "此桌面版本尚未配置账户认证。"
            : "Account authentication is not configured in this desktop build.",
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
    approveDesktopStartupGateForAccount(auth.account.id);
  }, [
    auth.account,
    auth.configured,
    auth.loading,
    desktopRuntime,
    launcherMode,
    locale,
    runtimeAccess.isChecking,
    runtimeAccess.lastFullCheckAt,
    runtimeAccess.status,
    updater.availableVersion,
    updater.error,
    updater.status,
    updater.updateRequired,
  ]);

  const closeSettings = useCallback(() => {
    setLauncherSettingsOpen(false);
    setSettingsInitialTab("general");
    // The trigger is inert while the modal is open. Restore focus on the next
    // frame, after the dialog effect has removed inert from the app shell.
    requestAnimationFrame(() => {
      if (mobileNavigationEnabled) mobileMenuButtonRef.current?.focus();
      else launcherSettingsButtonRef.current?.focus();
    });
  }, [mobileNavigationEnabled]);

  const openSettingsWorkspace = useCallback((
    tab: SettingsSurfaceTabId = "general",
    opener: "account" | "settings" = "settings",
    draft: ExperiencePreferenceDraft | null = null,
  ) => {
    settingsWorkspaceOpenerRef.current = opener;
    setSettingsPreferenceHandoff(draft);
    setSettingsInitialTab(tab);
    setLauncherSettingsOpen(false);
    setAccountMenuOpen(false);
    setMobileMenuOpen(false);
    setSettingsWorkspaceOpen(true);
  }, []);
  const openAllSettings = useCallback((
    tab: SettingsSurfaceTabId = "general",
    draft?: ExperiencePreferenceDraft,
  ) => {
    openSettingsWorkspace(tab, "settings", draft ?? null);
  }, [openSettingsWorkspace]);

  const closeSettingsWorkspace = useCallback(() => {
    setSettingsWorkspaceOpen(false);
    setSettingsPreferenceHandoff(null);
    setSettingsInitialTab("general");
    requestAnimationFrame(() => {
      const opener = settingsWorkspaceOpenerRef.current === "account"
        ? accountButtonRef.current
        : launcherSettingsButtonRef.current;
      (opener ?? accountButtonRef.current ?? launcherSettingsButtonRef.current)?.focus();
    });
  }, []);

  useEffect(() => {
    if (!settingsWorkspaceOpen) return undefined;
    const workspace = document.querySelector<HTMLElement>(".settings-workspace-host");
    const appShell = workspace?.parentElement;
    if (!workspace || !appShell) return undefined;
    const siblings = Array.from(appShell.children)
      .filter((element): element is HTMLElement => element instanceof HTMLElement && element !== workspace)
      .map((element) => ({
        element,
        inert: element.hasAttribute("inert"),
        ariaHidden: element.getAttribute("aria-hidden"),
      }));
    for (const { element } of siblings) {
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    }
    return () => {
      for (const { element, inert, ariaHidden } of siblings) {
        if (!inert) element.removeAttribute("inert");
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      }
    };
  }, [settingsWorkspaceOpen]);

  useEffect(() => {
    if (!accountMenuOpen) return undefined;
    const closeOnOutside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (accountButtonRef.current?.contains(target) || accountMenuRef.current?.contains(target)) return;
      setAccountMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setAccountMenuOpen(false);
      accountButtonRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [accountMenuOpen]);

  const closeAccount = useCallback(() => {
    if (accountRequired) return;
    setAccountOpen(false);
    requestAnimationFrame(() => {
      if (mobileNavigationEnabled) mobileMenuButtonRef.current?.focus();
      else accountButtonRef.current?.focus();
    });
  }, [accountRequired, mobileNavigationEnabled]);

  useEffect(() => {
    if (!mobileMenuExpanded) return;
    const closeMobileMenu = (restoreFocus: boolean) => {
      setMobileMenuOpen(false);
      if (restoreFocus) {
        requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
      }
    };
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (
        mobileMenuPanelRef.current?.contains(target)
        || mobileMenuButtonRef.current?.contains(target)
      ) return;
      closeMobileMenu(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeMobileMenu(true);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileMenuExpanded]);

  useEffect(() => {
    if (launcherMode) return;
    const openAccountDialog = () => {
      setLauncherSettingsOpen(false);
      setAccountMenuOpen(false);
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
    const openSettings = (event: Event) => {
      const requested = event instanceof CustomEvent
        ? (event.detail as { target?: AppSettingsTarget } | undefined)?.target ?? "general"
        : "general";
      openSettingsWorkspace(
        requested === "runtime" && !runtimeAccess.desktopRuntime ? "general" : requested,
      );
    };
    window.addEventListener(OPEN_APP_SETTINGS_EVENT, openSettings);
    return () => window.removeEventListener(OPEN_APP_SETTINGS_EVENT, openSettings);
  }, [openSettingsWorkspace, runtimeAccess.desktopRuntime]);

  useEffect(() => {
    if (new URLSearchParams(location.search).get("settings") === "runtime") {
      openSettingsWorkspace(runtimeAccess.desktopRuntime ? "runtime" : "general");
    }
  }, [location.search, openSettingsWorkspace, runtimeAccess.desktopRuntime]);

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
        edition={activeThemeEdition}
        desktopBrowserAuthReady={runtimeAccess.canUseRuntime}
        onOpenDesktopSetup={() => navigate("/desktop/setup")}
        onClose={closeAccount}
      />
    </div>
  ) : null;
  const settingsWorkspace = settingsWorkspaceOpen ? (
    <div className="settings-workspace-host">
      <SettingsDialog
        key={settingsInitialTab}
        access={runtimeAccess}
        closeRef={launcherSettingsCloseRef}
        edition={activeThemeEdition}
        initialPreferenceDraft={settingsPreferenceHandoff}
        initialTab={settingsInitialTab}
        onClose={closeSettingsWorkspace}
        onOpenExternal={openExternalNavigation}
        presentation="workspace"
        preferenceSaveQueueRef={settingsPreferenceSaveQueueRef}
      />
    </div>
  ) : null;

  if (launcherMode) {
    return (
      <EditionThemeProvider edition={activeThemeEdition}>
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
          <Link
            to="/desktop/setup"
            className="launcher-brand"
            aria-label={EDITION_BRAND_TOKENS[activeThemeEdition].productName}
          >
            <BrandLockup edition={activeThemeEdition} />
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
              aria-haspopup={auth.account ? "menu" : "dialog"}
              aria-expanded={launcherSettingsOpen}
              onClick={() => setLauncherSettingsOpen(true)}
            >
              <Settings aria-hidden="true" strokeWidth={1.85} />
            </button>
          </div>
        </header>
        {launcherSettingsOpen ? (
          <div
            className="launcher-settings-backdrop quick-settings-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target !== event.currentTarget) return;
              closeSettings();
            }}
          >
            <SettingsDialog
              access={runtimeAccess}
              closeRef={launcherSettingsCloseRef}
              edition={activeThemeEdition}
              initialTab={settingsInitialTab}
              onClose={closeSettings}
              onOpenAllSettings={openAllSettings}
              onOpenExternal={openExternalNavigation}
              presentation="quick"
              preferenceSaveQueueRef={settingsPreferenceSaveQueueRef}
            />
          </div>
        ) : null}
         <main id="main-content" className="launcher-main" tabIndex={-1}>
           <Outlet key={activeThemeEdition} />
         </main>
         {settingsWorkspace}
         {exitGuard}
         </div>
      </EditionThemeProvider>
    );
  }

  return (
    <EditionThemeProvider edition={activeThemeEdition}>
      <div className={`app-shell${experimentWizardMode ? " app-shell-wizard" : ""}${publicDemoConsole ? " app-shell-public-demo" : ""}`}>
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
        {!EDITION_IS_FIXED ? (
          <UniversalModeSwitch
            mode={universalMode}
            activeEdition={activeThemeEdition}
            locale={locale}
            onChange={handleUniversalModeChange}
          />
        ) : (
          <div className="app-title" aria-label={EDITION_BRAND_TOKENS[activeThemeEdition].productName}>
            <BrandLockup edition={activeThemeEdition} />
          </div>
        )}
        {mobileNavigationEnabled ? (
          <button
            ref={mobileMenuButtonRef}
            type="button"
            className="app-mobile-menu-button"
            aria-label={t(mobileMenuExpanded ? "app.closeMenu" : "app.openMenu")}
            aria-controls="app-mobile-navigation"
            aria-expanded={mobileMenuExpanded}
            onClick={() => setMobileMenuOpen((current) => !current)}
          >
            <Menu aria-hidden="true" strokeWidth={1.9} />
          </button>
        ) : null}
        <div
          ref={mobileMenuPanelRef}
          id="app-mobile-navigation"
          className={`app-mobile-menu-panel${mobileMenuExpanded ? " is-open" : ""}`}
          hidden={mobileNavigationEnabled && !mobileMenuExpanded}
        >
          <nav className="app-nav" aria-label={t("app.primaryNav")}>
          <span id="runtime-nav-description" className="sr-only">
            {runtimeNavDescription}
          </span>
          {navigationItems.map((item) => {
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
            const linkNode = externalUrl ? (
                <a
                  href={externalUrl}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(event) => {
                    setMobileMenuOpen(false);
                    openExternalNavigation(event, externalUrl);
                  }}
                >
                  {itemContent}
                </a>
              ) : (
              <NavLink
                to={destination}
                end={item.end}
                title={runtimeLocked ? runtimeNavDescription : undefined}
                aria-describedby={runtimeLocked ? "runtime-nav-description" : undefined}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) => {
                  const classes = runtimeLocked ? ["runtime-locked"] : [];
                  if (isActive) classes.push("active");
                  return classes.length > 0 ? classes.join(" ") : undefined;
                }}
              >
                {itemContent}
              </NavLink>
            );

            return (
              <Fragment key={item.to}>
                {item.sectionKey ? (
                  <span className="app-nav-section-label">
                    {t(item.sectionKey)}
                  </span>
                ) : null}
                {linkNode}
              </Fragment>
            );
          })}
          {!desktopRuntime && adminAccess.status === "allowed" ? (
            <NavLink
              to="/admin"
              onClick={() => setMobileMenuOpen(false)}
              className={({ isActive }) => isActive ? "active" : undefined}
            >
              <span className="app-nav-entry">
                <ShieldCheck aria-hidden="true" strokeWidth={1.75} />
                <span>{locale === "zh-CN" ? "管理端" : "Admin"}</span>
              </span>
            </NavLink>
          ) : null}
          </nav>
          <ExperimentWorkspaceSidebar
            ownerId={auth.account?.id ?? "local"}
            locale={locale}
            edition={activeThemeEdition}
          />
          <div className="app-sidebar-footer">
            {accountMenuOpen && auth.account ? (
              <AccountMenuPopover
                menuRef={accountMenuRef}
                onClose={() => setAccountMenuOpen(false)}
                onOpenAllowance={() => {
                  openSettingsWorkspace("model", "account");
                }}
                onOpenSettings={() => {
                  openSettingsWorkspace("general", "account");
                }}
              />
            ) : null}
            <button
              ref={accountButtonRef}
              type="button"
              className="app-account-button"
              aria-label={accountCopy.account}
              aria-haspopup={mobileNavigationEnabled ? "dialog" : "menu"}
              aria-expanded={accountMenuOpen || accountDialogOpen}
              onClick={() => {
                setMobileMenuOpen(false);
                setLauncherSettingsOpen(false);
                if (auth.account) {
                  if (mobileNavigationEnabled) {
                    setAccountMenuOpen(false);
                    setAccountOpen(true);
                  } else {
                    setAccountMenuOpen((open) => !open);
                  }
                } else {
                  setAccountOpen(true);
                }
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
                  <AccountPlanLabel authenticated={Boolean(auth.account)} />
                </small>
              </span>
            </button>
            {sidebarUpdateVisible ? (
              <button
                type="button"
                className={`app-account-trailing-button app-update-button${sidebarUpdateBusy ? " is-busy" : ""}`}
                aria-label={sidebarUpdateLabel}
                title={sidebarUpdateLabel}
                disabled={sidebarUpdateBusy}
                onClick={handleSidebarUpdate}
              >
                <Download aria-hidden="true" strokeWidth={2} />
              </button>
            ) : null}
          </div>
          {mobileNavigationEnabled ? (
            <button
              ref={launcherSettingsButtonRef}
              type="button"
              className="app-mobile-settings-entry"
              aria-label={t("app.settings")}
              aria-haspopup="dialog"
              aria-expanded={launcherSettingsOpen}
              onClick={() => {
                setMobileMenuOpen(false);
                setLauncherSettingsOpen(true);
              }}
            >
              <Settings aria-hidden="true" strokeWidth={1.75} />
              <span>{t("app.settings")}</span>
            </button>
          ) : null}
        </div>
      </aside>
      <div className={`app-body${experimentWizardMode ? " app-body-wizard" : ""}`}>
        <header className="app-header">
          <div className="app-header-title">
            {EDITION_BRAND_TOKENS[activeThemeEdition].productName} — {t(EDITION_PLATFORM_LABEL[activeThemeEdition])}
          </div>
          {!mobileNavigationEnabled ? (
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
          ) : null}
        </header>
        {launcherSettingsOpen ? (
          <div
            className="launcher-settings-backdrop quick-settings-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target !== event.currentTarget) return;
              closeSettings();
            }}
          >
            <SettingsDialog
              access={runtimeAccess}
              closeRef={launcherSettingsCloseRef}
              edition={activeThemeEdition}
              initialTab={settingsInitialTab}
              onClose={closeSettings}
              onOpenAllSettings={openAllSettings}
              onOpenExternal={openExternalNavigation}
              presentation="quick"
              preferenceSaveQueueRef={settingsPreferenceSaveQueueRef}
            />
          </div>
        ) : null}
        {accountDialog}
        {externalNavigationError ? (
          <div className="app-external-navigation-error" role="alert">
            <span>{externalNavigationError}</span>
            <button
              type="button"
              aria-label={t("app.dismiss")}
              onClick={() => setExternalNavigationError(null)}
            >
              <X aria-hidden="true" />
            </button>
          </div>
        ) : null}
        <main id="main-content" className={`app-main${experimentWizardMode ? " app-main-wizard" : ""}`} tabIndex={-1}>
          <Outlet key={activeThemeEdition} />
        </main>
      </div>
      {settingsWorkspace}
      {exitGuard}
      </div>
    </EditionThemeProvider>
  );
}
