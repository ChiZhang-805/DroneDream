import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ChangeEvent, MouseEvent, ReactNode, RefObject } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Apple,
  ArrowRight,
  Bell,
  BotMessageSquare,
  Box,
  BrainCircuit,
  Camera,
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
  MailCheck,
  MapPinned,
  Menu,
  Moon,
  MonitorCog,
  MoreHorizontal,
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
import {
  EditionSettingsPanel,
  EditionSettingsSurface,
  type SettingsSurfaceTab,
  type SettingsSurfaceTabId,
} from "./components/EditionSettingsSurface";
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
import { OPEN_APP_SETTINGS_EVENT } from "./appSettings";
import { AuthCaptcha } from "./features/auth/AuthCaptcha";
import { AuthProvider, useAuth } from "./features/auth/AuthContext";
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
import {
  modelProviderLabel,
  type ModelProvider,
} from "./features/settings/ModelAccessContext";
import { ModelAccessProvider } from "./features/settings/ModelAccessProvider";
import {
  CloudModelAccessError,
  DEFAULT_MANAGED_MODEL_CATALOG,
  completeManagedModelCatalog,
  getManagedModelCatalog,
  getManagedModelUsage,
  managedModelAvailableForAssistant,
  redeemManagedAllowanceResetCard,
  type ManagedAllowanceResetCard,
  type ManagedModelCatalogEntry,
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
import { useI18n } from "./i18n/I18nProvider";
import type { InterfaceLocale, TranslationKey } from "./i18n/I18nProvider";
import type {
  Job,
  JobStatus,
  StarterExperienceTemplateKey,
  UserDefaultTrackType,
} from "./types/api";
import {
  deleteConsolePreferencesAndMemory,
  loadConsolePreferences,
  saveConsolePreferences,
  type ConsoleMemoryScope,
  type ConsolePreferenceRecord,
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
  {
    to: "/vehicle-studio",
    labelKey: "app.vehicleStudio",
    icon: Box,
  },
];

const ASSISTANT_NAV_ITEM = CORE_NAV_ITEMS[0];
const DASHBOARD_NAV_ITEM = CORE_NAV_ITEMS[1];
const HISTORY_NAV_ITEM = CORE_NAV_ITEMS[2];
const SCENARIOS_NAV_ITEM = CORE_NAV_ITEMS[3];
const VEHICLE_STUDIO_NAV_ITEM = CORE_NAV_ITEMS[4];

const SIM_NAV_ITEMS: NavigationItem[] = [
  ASSISTANT_NAV_ITEM,
  { to: "/jobs/new", labelKey: "app.experimentBuilder", icon: SlidersHorizontal },
  DASHBOARD_NAV_ITEM,
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
  ASSISTANT_NAV_ITEM,
  { to: "/jobs/new", labelKey: "app.experimentBuilder", icon: SlidersHorizontal },
  LAB_WORKSPACE_NAV_ITEMS[0],
  LAB_WORKSPACE_NAV_ITEMS[1],
  { to: "/lab/validation", labelKey: "app.labValidation", icon: ShieldCheck },
  HISTORY_NAV_ITEM,
];

const FIELD_NAV_ITEMS: NavigationItem[] = [
  ASSISTANT_NAV_ITEM,
  {
    to: "/field/device",
    labelKey: "app.fieldDeviceSetup",
    end: true,
    icon: RadioTower,
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
  HISTORY_NAV_ITEM,
];

const MODE_NAV_ITEMS: Record<UniversalWorkspaceId, NavigationItem[]> = {
  universal: [
    ASSISTANT_NAV_ITEM,
    VEHICLE_STUDIO_NAV_ITEM,
    DASHBOARD_NAV_ITEM,
    HISTORY_NAV_ITEM,
    SCENARIOS_NAV_ITEM,
  ],
  sim: SIM_NAV_ITEMS,
  lab: LAB_NAV_ITEMS,
  field: FIELD_NAV_ITEMS,
};

const MODE_LANDING_PATH: Record<UniversalWorkspaceId, string> = {
  universal: "/assistant",
  sim: "/assistant",
  lab: "/assistant",
  field: "/assistant",
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
  memory_enabled: boolean;
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
  memory_enabled: false,
  memory_scopes: {
    chat_preferences: true,
    experiment_defaults: true,
    device_vehicle: true,
    metrics_constraints: true,
    safety_approvals: true,
    workflow_tools: true,
    reports_delivery: true,
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

const SETTINGS_LOCALES = [
  { id: "en", label: "English", region: "west" },
  { id: "zh-CN", label: "简体中文", region: "east" },
  { id: "zh-TW", label: "繁體中文", region: "east" },
  { id: "es", label: "Español", region: "west" },
  { id: "ja", label: "日本語", region: "east" },
  { id: "ko", label: "한국어", region: "east" },
] as const;

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
  memoryScopes: readonly [string, string, string, string, string, string, string];
  memoryDefaults: readonly [string, string, string, string, string];
  courseOverview: string;
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
    memoryScopes: ["Chat preferences", "Experiment defaults", "Device and vehicle", "Metrics and constraints", "Safety and approvals", "Workflow and tools", "Reports and delivery"],
    memoryDefaults: ["Default vehicle", "Default objective", "Default safety profile", "Default units", "Default report format"],
    courseOverview: "The course joins LLM reasoning with controls and aerospace engineering tools; DroneDream turns that foundation into practical UAV workflows that can be planned, executed, reviewed, and verified.",
    courseOpen: "Open course",
    courseActions: ["Read manual", "Explore product"],
    courseEditions: ["Shape vehicle models, design repeatable simulations, coordinate laboratory and field validation, and keep every decision connected to traceable engineering evidence. The integrated workspace carries requirements, parameters, reviews, reports, and delivery records through one coherent UAV workflow.", "Build reproducible PX4 and Gazebo studies with bounded scenarios, parameter domains, budgets, objectives, and safety constraints. Compare candidates against common metrics, preserve holdout evidence, explain failures, and turn each simulation result into a reviewable experiment record.", "Connect simulation evidence with captured hardware data through calibration, mismatch diagnosis, controlled trials, and safety gates. Track Sim-to-Real and Real-to-Sim updates, qualify each change, record approvals, and preserve the evidence required for dependable validation.", "Prepare real-device tuning with compatibility checks, operator approvals, telemetry boundaries, parameter snapshots, abort rules, and reliable rollback plans. Every field task remains reviewable before execution and produces an auditable record for safe follow-up decisions."],
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
    memoryScopes: ["对话偏好", "实验默认值", "设备与机型", "指标与约束", "安全与审批", "工作流与工具", "报告与交付"],
    memoryDefaults: ["默认机型", "默认优化目标", "默认安全配置", "默认单位制", "默认报告格式"],
    courseOverview: "课程把大模型推理与控制、航空航天工程工具紧密结合，DroneDream 将这些基础能力落实为可规划、可执行、可复核、可验收的无人机工程工作流。",
    courseOpen: "打开课程",
    courseActions: ["阅读说明书", "查看产品"],
    courseEditions: ["在统一工作区中完成无人机机型建模、可重复仿真实验、实验室验证和现场交付。需求、参数、审批、报告与版本记录始终关联，并把每次判断沉淀为可追踪、可复核、可验收的完整无人机工程证据链。", "围绕 PX4 与 Gazebo 设计可重复的飞行研究，明确场景、参数边界、试验预算、优化目标和安全约束。统一比较候选方案与留出证据，解释失败原因，并把每次仿真结果保存为可继续审查的结构化实验记录。", "贯通仿真证据与真实硬件采集数据，完成标定、差异诊断、受控试验和安全门检查。持续记录 Sim-to-Real 与 Real-to-Sim 更新、审批和资格验证，让每次模型变化都有可靠依据并可以回溯。", "通过兼容性检查、操作员审批、遥测边界、参数快照、中止规则和可靠回滚方案准备真机调优。所有现场任务在执行前都可复核，执行后形成可审计记录，为下一轮安全决策提供完整依据。"],
  },
  "zh-TW": {
    title: "設定",
    tabs: ["一般", "記憶", "模型", "執行環境"],
    language: "語言",
    interface: "介面",
    notifications: "通知",
    appearance: ["深色", "淺色", "跟隨系統", "自訂"],
    notificationLabels: ["允許通知", "實驗與任務完成", "AI 回覆完成", "產品更新", "需要審批", "額度或重置卡即將到期", "安全與登入提醒", "裝置或執行環境狀態"],
    memoryTitle: "記憶",
    memoryEnabled: ["記憶已關閉", "記憶已開啟"],
    crossSession: "跨工作階段記憶",
    memoryScopes: ["對話偏好", "實驗預設值", "裝置與機型", "指標與限制", "安全與審批", "工作流程與工具", "報告與交付"],
    memoryDefaults: ["預設機型", "預設最佳化目標", "預設安全設定", "預設單位制", "預設報告格式"],
    courseOverview: "課程結合大型語言模型推理、控制與航太工程工具，DroneDream 將這些能力落實為可規劃、可執行、可複核、可驗收的無人機工程流程。",
    courseOpen: "開啟課程",
    courseActions: ["閱讀說明書", "查看產品"],
    courseEditions: ["在統一工作區完成無人機機型建模、可重複模擬、實驗室驗證與現場交付。需求、參數、審批、報告及版本記錄持續關聯，讓每次工程判斷都成為可追蹤、可複核、可驗收的完整證據鏈。", "圍繞 PX4 與 Gazebo 建立可重複飛行研究，明確場景、參數邊界、預算、目標與安全限制。統一比較候選與留出證據、解釋失敗原因，並把每次模擬保存為可延續審查的結構化實驗記錄。", "串聯模擬證據與真實硬體採集資料，完成校準、差異診斷、受控試驗及安全門檢查。持續記錄 Sim-to-Real、Real-to-Sim 更新、審批與資格驗證，使每次模型變化都有可靠依據。", "透過相容性檢查、操作員審批、遙測邊界、參數快照、中止規則和可靠回復方案準備實機調校。所有現場任務執行前皆可複核，完成後形成可稽核記錄以支援安全決策。"],
  },
  es: {
    title: "Ajustes",
    tabs: ["General", "Memoria", "Modelos", "Entorno"],
    language: "Idioma",
    interface: "Interfaz",
    notifications: "Notificaciones",
    appearance: ["Oscuro", "Claro", "Sistema", "Personalizar"],
    notificationLabels: ["Permitir notificaciones", "Experimento o tarea completada", "Respuesta de IA completada", "Actualizaciones del producto", "Aprobación requerida", "Créditos o tarjeta por vencer", "Seguridad e inicio de sesión", "Estado del dispositivo o entorno"],
    memoryTitle: "Memoria",
    memoryEnabled: ["Memoria desactivada", "Memoria activada"],
    crossSession: "Memoria entre sesiones",
    memoryScopes: ["Preferencias de chat", "Valores del experimento", "Dispositivo y vehículo", "Métricas y límites", "Seguridad y aprobaciones", "Flujo y herramientas", "Informes y entrega"],
    memoryDefaults: ["Vehículo predeterminado", "Objetivo predeterminado", "Perfil de seguridad", "Unidades predeterminadas", "Formato del informe"],
    courseOverview: "El curso une razonamiento con modelos, control y herramientas de ingeniería aeroespacial; DroneDream lo convierte en flujos UAV prácticos, planificables, revisables y verificables.",
    courseOpen: "Abrir curso",
    courseActions: ["Leer manual", "Ver producto"],
    courseEditions: ["Modela vehículos, diseña simulaciones repetibles y coordina validaciones de laboratorio y campo en un solo espacio. Requisitos, parámetros, revisiones, informes y versiones permanecen unidos para crear una evidencia técnica trazable, verificable y lista para entregar.", "Construye estudios PX4 y Gazebo reproducibles con escenarios, límites, presupuestos, objetivos y restricciones definidos. Compara candidatos con métricas comunes, conserva pruebas independientes, explica fallos y convierte cada resultado en un experimento estructurado y revisable.", "Conecta evidencia simulada con datos del hardware mediante calibración, diagnóstico, ensayos controlados y puertas de seguridad. Registra cambios Sim-to-Real y Real-to-Sim, aprobaciones y calificación para que cada actualización tenga fundamento y trazabilidad.", "Prepara ajustes de dispositivos reales con compatibilidad, aprobación del operador, límites de telemetría, instantáneas, reglas de aborto y reversión fiable. Cada tarea se revisa antes de ejecutar y genera un registro auditable para decisiones posteriores seguras."],
  },
  ja: {
    title: "設定",
    tabs: ["一般", "メモリ", "モデル", "実行環境"],
    language: "言語",
    interface: "表示",
    notifications: "通知",
    appearance: ["ダーク", "ライト", "システム", "カスタム"],
    notificationLabels: ["通知を許可", "実験・タスク完了", "AI 応答完了", "製品アップデート", "承認が必要", "利用枠・カード期限", "セキュリティとログイン", "デバイス・実行環境の状態"],
    memoryTitle: "メモリ",
    memoryEnabled: ["メモリ オフ", "メモリ オン"],
    crossSession: "セッション間メモリ",
    memoryScopes: ["チャット設定", "実験の既定値", "デバイスと機体", "指標と制約", "安全と承認", "ワークフローとツール", "レポートと納品"],
    memoryDefaults: ["既定の機体", "既定の最適化目標", "既定の安全設定", "既定の単位", "既定のレポート形式"],
    courseOverview: "本講義はモデル推論、制御、航空宇宙工学ツールを結び、DroneDream で計画・実行・レビュー・検証できる実践的な UAV 工程へ展開します。",
    courseOpen: "講義を開く",
    courseActions: ["説明書を読む", "製品を見る"],
    courseEditions: ["機体モデル、再現可能なシミュレーション、ラボ検証、現場での納品を一つの作業空間で統合します。要件、パラメータ、承認、レポート、版履歴を結び、すべての判断を追跡・レビュー・検証できる工学証拠として残します。", "PX4 と Gazebo を用いて、シナリオ、パラメータ範囲、予算、目的、安全制約を明確にした再現可能な研究を設計します。候補と独立証拠を共通指標で比較し、失敗を説明し、結果を構造化された実験記録として保存します。", "シミュレーション証拠と実機データを、校正、差異診断、制御試験、安全ゲートで接続します。Sim-to-Real と Real-to-Sim の更新、承認、適格性確認を継続して記録し、各モデル変更の根拠と履歴を保ちます。", "互換性確認、操作者承認、テレメトリ境界、パラメータスナップショット、中止条件、確実な復元計画で実機調整を準備します。現場タスクは実行前にレビューでき、完了後は安全な判断に使える監査記録を残します。"],
  },
  ko: {
    title: "설정",
    tabs: ["일반", "메모리", "모델", "실행 환경"],
    language: "언어",
    interface: "화면",
    notifications: "알림",
    appearance: ["다크", "라이트", "시스템", "사용자 지정"],
    notificationLabels: ["알림 허용", "실험 및 작업 완료", "AI 응답 완료", "제품 업데이트", "승인 필요", "할당량 또는 카드 만료", "보안 및 로그인", "장치 또는 런타임 상태"],
    memoryTitle: "메모리",
    memoryEnabled: ["메모리 꺼짐", "메모리 켜짐"],
    crossSession: "세션 간 메모리",
    memoryScopes: ["대화 기본 설정", "실험 기본값", "장치 및 기체", "지표 및 제약", "안전 및 승인", "워크플로 및 도구", "보고서 및 전달"],
    memoryDefaults: ["기본 기체", "기본 최적화 목표", "기본 안전 설정", "기본 단위", "기본 보고서 형식"],
    courseOverview: "이 과정은 모델 추론, 제어, 항공우주 공학 도구를 결합하고 DroneDream에서 계획·실행·검토·검증 가능한 실용적인 UAV 작업 흐름으로 구현합니다.",
    courseOpen: "강의 열기",
    courseActions: ["설명서 보기", "제품 보기"],
    courseEditions: ["기체 모델링, 반복 가능한 시뮬레이션, 실험실 검증, 현장 전달을 하나의 작업 공간에서 연결합니다. 요구 사항, 매개변수, 승인, 보고서와 버전 기록을 유지하여 모든 판단을 추적·검토·검증할 수 있는 엔지니어링 증거로 만듭니다.", "PX4와 Gazebo에서 시나리오, 매개변수 범위, 예산, 목표와 안전 제약을 명확히 한 반복 연구를 설계합니다. 공통 지표로 후보와 독립 증거를 비교하고 실패를 설명하며 결과를 구조화된 실험 기록으로 보존합니다.", "시뮬레이션 증거와 실제 하드웨어 데이터를 보정, 차이 진단, 통제 시험과 안전 게이트로 연결합니다. Sim-to-Real 및 Real-to-Sim 변경, 승인과 자격 검증을 기록하여 모든 모델 업데이트의 근거와 이력을 유지합니다.", "호환성 확인, 운영자 승인, 텔레메트리 경계, 매개변수 스냅샷, 중단 규칙과 신뢰할 롤백 계획으로 실제 기체 튜닝을 준비합니다. 모든 현장 작업은 실행 전 검토되고 완료 후 안전한 후속 결정을 위한 감사 기록을 남깁니다."],
  },
};

function SettingsToggle({
  checked,
  className,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  className?: string;
  disabled?: boolean;
  label: ReactNode;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={`settings-toggle-row${className ? ` ${className}` : ""}`}>
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <i aria-hidden="true" />
    </label>
  );
}

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
  edition,
  onClose,
  onOpenExternal,
}: {
  access: DesktopRuntimeAccess;
  closeRef: RefObject<HTMLButtonElement>;
  edition: BrandEditionId;
  onClose: () => void;
  onOpenExternal: (event: MouseEvent<HTMLAnchorElement>, url: string) => void;
}) {
  const { locale, interfaceLocale, setLocale, t } = useI18n();
  const settingsCopy = SETTINGS_COPY[interfaceLocale];
  const editionTheme = useEditionTheme();
  const setAppearancePreference = editionTheme.setAppearance;
  const setCustomAccentPreference = editionTheme.setCustomAccent;
  const auth = useAuth();
  const {
    settings: modelAccess,
    profiles: modelProfiles,
    activeProfileId,
    selectProfile,
    addProfile,
    removeActiveProfile,
    selectAccessMode,
    selectManagedModel,
    selectProvider,
    updateSettings,
  } = useModelAccess();
  const docsPreview = import.meta.env.DEV
    && new URLSearchParams(window.location.search).has("docsPreview");
  const legacyDesktopPreferences = !auth.account && !docsPreview && isDesktopRuntime();
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
    useState<ExperiencePreferenceDraft>(EMPTY_EXPERIENCE_PREFERENCE_DRAFT);
  const [experiencePreferenceState, setExperiencePreferenceState] =
    useState<"blocked" | "loading" | "ready" | "saving" | "saved" | "error">(
      auth.account || docsPreview || legacyDesktopPreferences ? "loading" : "blocked",
    );
  const [experiencePreferenceMessage, setExperiencePreferenceMessage] =
    useState<string | null>(null);
  const [confirmExperiencePreferenceDelete, setConfirmExperiencePreferenceDelete] =
    useState(false);
  const preferenceHydratedRef = useRef(false);
  const initialPreferencePresentationRef = useRef({
    interfaceLocale,
    appearanceMode: editionTheme.appearancePreference,
    customAccent: editionTheme.customAccent,
  });
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
    if (!preferenceBoundary && !docsPreview && !legacyDesktopPreferences) {
      setExperiencePreferenceState("blocked");
      setExperiencePreferenceMessage(null);
      setConfirmExperiencePreferenceDelete(false);
      return undefined;
    }
    let active = true;
    setExperiencePreferenceState("loading");
    setExperiencePreferenceMessage(null);
    const load = docsPreview
      ? Promise.resolve(null)
      : preferenceBoundary
        ? loadConsolePreferences(preferenceBoundary)
        : apiClient.getUserExperiencePreferences().then((preferences): ConsolePreferenceRecord => ({
            interface_locale: initialPreferencePresentationRef.current.interfaceLocale,
            appearance_mode: initialPreferencePresentationRef.current.appearanceMode,
            custom_accent: initialPreferencePresentationRef.current.customAccent,
            notifications: DEFAULT_NOTIFICATION_PREFERENCES,
            memory_enabled: preferences.memory_enabled,
            memory_scopes: {
              ...EMPTY_EXPERIENCE_PREFERENCE_DRAFT.memory_scopes,
              chat_preferences: preferences.memory_enabled,
              experiment_defaults: preferences.memory_enabled,
            },
            defaults: {
              template: preferences.default_template_key,
              vehicle: null,
              track: preferences.default_track_type,
              altitude_m: preferences.default_altitude_m,
              objective: null,
              safety_profile: null,
              units: null,
              report_format: null,
            },
          }));
    void load
      .then((preferences) => {
        if (!active) return;
        if (preferences) {
          const defaults = preferences.defaults ?? {};
          setExperiencePreferenceDraft({
            ...EMPTY_EXPERIENCE_PREFERENCE_DRAFT,
            memory_enabled: preferences.memory_enabled,
            memory_scopes: {
              ...EMPTY_EXPERIENCE_PREFERENCE_DRAFT.memory_scopes,
              ...preferences.memory_scopes,
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
          setNotificationPreferences({
            ...DEFAULT_NOTIFICATION_PREFERENCES,
            ...preferences.notifications,
          });
          setLocale(preferences.interface_locale);
          setAppearancePreference(preferences.appearance_mode);
          setCustomAccentPreference(preferences.custom_accent);
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
    legacyDesktopPreferences,
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
      return undefined;
    }
    const pendingSave = window.setTimeout(() => {
      void saveConsolePreferences(preferenceBoundary, consolePreferenceRecord())
        .catch(() => setExperiencePreferenceMessage(t("settings.memory.saveFailed")));
    }, 450);
    return () => window.clearTimeout(pendingSave);
  }, [
    consolePreferenceRecord,
    docsPreview,
    experiencePreferenceState,
    preferenceBoundary,
    t,
  ]);
  const saveExperiencePreferences = async () => {
    if (
      (!preferenceBoundary && !docsPreview && !legacyDesktopPreferences) ||
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
        await saveConsolePreferences(preferenceBoundary, consolePreferenceRecord());
      } else if (legacyDesktopPreferences) {
        await apiClient.updateUserExperiencePreferences({
          memory_enabled: experiencePreferenceDraft.memory_enabled,
          locale: interfaceLocale === "zh-CN" ? "zh-CN" : "en",
          default_template_key: experiencePreferenceDraft.default_template_key,
          default_track_type: experiencePreferenceDraft.default_track_type,
          default_altitude_m: experiencePreferenceDraft.default_altitude_m,
        });
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
      (!preferenceBoundary && !docsPreview && !legacyDesktopPreferences) ||
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
        : legacyDesktopPreferences
          ? (await apiClient.deleteUserExperiencePreferences()).deleted_memory_count
          : 0;
      preferenceHydratedRef.current = false;
      setExperiencePreferenceDraft(EMPTY_EXPERIENCE_PREFERENCE_DRAFT);
      setConfirmExperiencePreferenceDelete(false);
      setExperiencePreferenceState("ready");
      setExperiencePreferenceMessage(
        t("settings.memory.deleted", {
          count: deletedCount,
        }),
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
    ? Math.min(
        100,
        Math.max(
          0,
          managedUsage.plan.included_ai_credits > 0
            ? managedUsage.usage.remaining_ai_credits
              / managedUsage.plan.included_ai_credits
              * 100
            : 0,
        ),
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
    "zh-TW": {
      cards: "額度重設卡",
      ready: "準備使用",
      full: "全額恢復",
      fullCard: "全額恢復卡",
      empty: "暫無可用額度卡",
      expires: "有效期至",
      use: "使用重設卡",
      using: "使用中…",
      confirm: "確認兌換",
      cancel: "取消",
      refresh: "重新整理用量",
    },
    es: {
      cards: "Tarjetas de recarga",
      ready: "Lista para usar",
      full: "Recarga completa",
      fullCard: "Tarjeta de recarga completa",
      empty: "No hay tarjetas disponibles",
      expires: "Vence",
      use: "Usar tarjeta",
      using: "Aplicando…",
      confirm: "Confirmar",
      cancel: "Cancelar",
      refresh: "Actualizar uso",
    },
    ja: {
      cards: "リセットカード",
      ready: "使用準備完了",
      full: "全額回復",
      fullCard: "全額回復カード",
      empty: "利用可能なカードなし",
      expires: "有効期限",
      use: "カードを使用",
      using: "使用中…",
      confirm: "確認",
      cancel: "キャンセル",
      refresh: "使用量を更新",
    },
    ko: {
      cards: "충전 카드",
      ready: "사용 가능",
      full: "전체 충전",
      fullCard: "전체 충전 카드",
      empty: "사용 가능한 카드 없음",
      expires: "만료",
      use: "카드 사용",
      using: "사용 중…",
      confirm: "확인",
      cancel: "취소",
      refresh: "사용량 새로고침",
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
      setAllowanceResetMessage(
        error instanceof CloudModelAccessError
          ? error.message
          : locale === "zh-CN" ? "重置卡暂时无法使用。" : "The reset card could not be redeemed.",
      );
    }
  };
  const [activeSettingsTab, setActiveSettingsTab] =
    useState<SettingsSurfaceTabId>("general");
  const settingsTabs: readonly SettingsSurfaceTab[] = [
    { id: "general", label: settingsCopy.tabs[0] },
    { id: "memory", label: settingsCopy.tabs[1] },
    { id: "model", label: settingsCopy.tabs[2] },
    { id: "course", label: "ECE498BH" },
    ...(access.desktopRuntime
      ? [{ id: "runtime", label: settingsCopy.tabs[3] } as const]
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
      consumerProfile={edition === "field" ? "field-lightweight" : edition}
    >
      <EditionSettingsPanel active={activeSettingsTab === "general"} id="general">
        <section className="settings-general-panel">
          <div className="settings-general-card settings-language-card">
            <div className="settings-card-heading">
              <span><LanguageRegionIcon region="west" />{settingsCopy.language}</span>
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
                  <LanguageRegionIcon region={option.region} />
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
            <div>
              <h3 id="settings-course-title">ECE498BH</h3>
              <p>{settingsCopy.courseOverview}</p>
            </div>
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
          <div className="settings-course-editions" aria-label={locale === "zh-CN" ? "DroneDream 四款软件" : "DroneDream editions"}>
            {([
              ["universal", settingsCopy.courseEditions[0]],
              ["sim", settingsCopy.courseEditions[1]],
              ["lab", settingsCopy.courseEditions[2]],
              ["field", settingsCopy.courseEditions[3]],
            ] as const).map(([courseEdition, description]) => (
              <article key={courseEdition}>
                <BrandLockup edition={courseEdition} />
                <p>{description}</p>
                <Link
                  className="settings-course-edition-link"
                  to={courseEdition === "universal" ? "/manual/" : "/product/"}
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
            <h3 id="settings-memory-title">{settingsCopy.memoryTitle}</h3>
          </div>
          <span className={experiencePreferenceDraft.memory_enabled ? "configured" : undefined}>
            {settingsCopy.memoryEnabled[experiencePreferenceDraft.memory_enabled ? 1 : 0]}
          </span>
        </div>
        <div className="settings-memory-body">
          <div className="settings-memory-switches">
            <SettingsToggle
              checked={experiencePreferenceDraft.memory_enabled}
              className="settings-memory-master-toggle"
              disabled={experiencePreferenceControlsDisabled}
              label={<><BrainCircuit aria-hidden="true" /><span>{settingsCopy.crossSession}</span></>}
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
              ] as const).map(([scope, ScopeIcon, label]) => (
                <SettingsToggle
                  key={scope}
                  checked={experiencePreferenceDraft.memory_scopes[scope]}
                  disabled={experiencePreferenceControlsDisabled || !experiencePreferenceDraft.memory_enabled}
                  label={<><ScopeIcon aria-hidden="true" /><span>{label}</span></>}
                  onChange={(checked) => setExperiencePreferenceDraft((current) => ({
                    ...current,
                    memory_scopes: { ...current.memory_scopes, [scope]: checked },
                  }))}
                />
              ))}
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
                  <span>{locale === "zh-CN" ? "剩余额度" : "Remaining allowance"}</span>
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
                        className="settings-reset-card-trigger"
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
                  <option value="kimi">Kimi</option>
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
          </>
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
  edition,
  onClose,
}: {
  closeRef: RefObject<HTMLButtonElement>;
  required: boolean;
  edition: BrandEditionId;
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
      void Promise.all(
        (["universal", "sim", "lab", "field"] as const).map((edition) =>
          getAssistantWorkspaceIndex(edition, ownerId, organizationId)
        ),
      ).then((indexes) => {
        if (!active) return;
        hydrateAssistantWorkspaceIndex(ownerId, indexes.flat());
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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [externalNavigationError, setExternalNavigationError] = useState<string | null>(null);
  const [exitPrompt, setExitPrompt] = useState<ExitPromptState | null>(null);
  const launcherSettingsButtonRef = useRef<HTMLButtonElement>(null);
  const launcherSettingsCloseRef = useRef<HTMLButtonElement>(null);
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  const accountCloseRef = useRef<HTMLButtonElement>(null);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileMenuPanelRef = useRef<HTMLDivElement>(null);
  const desktopWindowRef = useRef<DesktopWindowHandle | null>(null);
  const currentPathRef = useRef(location.pathname);
  const exitPromptRef = useRef<ExitPromptState | null>(null);
  const exitCheckInFlightRef = useRef(false);
  const exitApprovedRef = useRef(false);
  const launcherMode = desktopRuntime && location.pathname === "/desktop/setup";
  const experimentWizardMode = location.pathname === "/jobs/new";
  const activeThemeEdition: BrandEditionId = EDITION_IS_FIXED
    ? BUILD_EDITION
    : launcherMode || location.pathname === "/vehicle-studio"
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
  const accountDialogRequired = accountRequired && !launcherMode;
  const accountDialogOpen = accountOpen || accountDialogRequired;
  const mobileMenuExpanded = mobileNavigationEnabled && mobileMenuOpen;
  const sidebarUpdateVisible = desktopRuntime && [
    "available",
    "downloading",
    "installing",
    "engineUpdateDeferred",
    "reconcilingEngine",
    "engineError",
    "runtimeBaseRequired",
  ].includes(updater.status);
  const sidebarUpdateBusy = [
    "downloading",
    "installing",
    "reconcilingEngine",
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
        : FIELD_NAV_ITEMS.filter((item) => item.to !== "/vehicle-studio")
    : MODE_NAV_ITEMS[universalMode];
  const sidebarUpdateLabel = updater.status === "available"
    ? updater.error
      ? t("updater.sidebarDeferred")
      : t("updater.sidebarAvailable")
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
      updater.status === "reconcilingEngine"
    ) {
      setDesktopStartupGateState("checking", {
        accountId: auth.account?.id ?? null,
      });
      return;
    }
    if (
      updater.status === "available" ||
      updater.status === "engineError" ||
      updater.status === "runtimeBaseRequired"
    ) {
      setDesktopStartupGateState("blocked", {
        accountId: auth.account?.id ?? null,
        error: updater.error ??
          `DroneDream ${updater.availableVersion ?? "update"} must be installed before entering the tuning workspace.`,
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
    approveDesktopStartupGateForAccount(auth.account.id);
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
    updater.error,
    updater.status,
  ]);

  const closeSettings = useCallback(() => {
    setLauncherSettingsOpen(false);
    // The trigger is inert while the modal is open. Restore focus on the next
    // frame, after the dialog effect has removed inert from the app shell.
    requestAnimationFrame(() => {
      if (mobileNavigationEnabled) mobileMenuButtonRef.current?.focus();
      else launcherSettingsButtonRef.current?.focus();
    });
  }, [mobileNavigationEnabled]);

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
        edition={activeThemeEdition}
        onClose={closeAccount}
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
              edition={activeThemeEdition}
              onClose={closeSettings}
              onOpenExternal={openExternalNavigation}
            />
          </div>
        ) : null}
        {exitGuard}
        <main id="main-content" className="launcher-main" tabIndex={-1}>
          <Outlet key={activeThemeEdition} />
        </main>
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
            if (externalUrl) {
              return (
                <a
                  key={item.to}
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
              );
            }

            return (
              <NavLink
                key={item.to}
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
            <button
              ref={accountButtonRef}
              type="button"
              className="app-account-button"
              aria-label={accountCopy.account}
              aria-haspopup="dialog"
              aria-expanded={accountDialogOpen}
              onClick={() => {
                setMobileMenuOpen(false);
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
            ) : (
              <button
                type="button"
                className="app-account-trailing-button app-account-more-button"
                aria-label={t("app.accountOptions")}
                title={t("app.accountOptions")}
                aria-haspopup="dialog"
                aria-expanded={accountDialogOpen}
                onClick={() => {
                  setMobileMenuOpen(false);
                  setLauncherSettingsOpen(false);
                  setAccountOpen(true);
                }}
              >
                <MoreHorizontal aria-hidden="true" strokeWidth={1.8} />
              </button>
            )}
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
            {EDITION_BRAND_TOKENS[activeThemeEdition].productName} — {t("app.platform")}
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
              edition={activeThemeEdition}
              onClose={closeSettings}
              onOpenExternal={openExternalNavigation}
            />
          </div>
        ) : null}
        {accountDialog}
        {exitGuard}
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
        <footer className="app-footer">
          <div className="app-footer-content">
            <span>{t("app.author")}: Chi Zhang</span>
            <span>{t("app.contact")}: cz005623@gmail.com</span>
          </div>
        </footer>
      </div>
      </div>
    </EditionThemeProvider>
  );
}
