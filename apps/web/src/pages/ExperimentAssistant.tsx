import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowUp,
  Boxes,
  Crosshair,
  Download,
  FileText,
  FileUp,
  GitFork,
  LoaderCircle,
  MapPinned,
  Mic,
  MicOff,
  Microchip,
  MonitorPlay,
  Orbit,
  PencilRuler,
  Plus,
  Route,
  SlidersHorizontal,
  Square,
  Upload,
  Wind,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";

import { apiClient, ApiClientError } from "../api/client";
import { openAppSettings } from "../appSettings";
import {
  applyAssistantTurn,
  assistantCurrentParameters,
  assistantCurrentValues,
  clearAssistantDraft,
  createEmptyAssistantDraft,
  explicitAssistantFields,
  loadAssistantDraft,
  persistAssistantDraft,
  type AssistantDraft,
} from "../features/experiment/assistantDraft";
import {
  completedAssistantResponseForArtifact,
  getAssistantWorkspace,
  latestCompletedAssistantResponse,
  orchestrateAssistantTurn,
  type AssistantRunStage,
  type AssistantWorkflowStep,
} from "../features/experiment/assistantOrchestration";
import {
  assistantTaskOptions,
  storeAutonomyHandoff,
  type AssistantTaskType,
} from "../features/experiment/assistantTaskRouter";
import { clearExperimentDraft } from "../features/experiment/draftStorage";
import { publicDemoConsole } from "../features/demo/publicDemo";
import { useOptionalAuth } from "../features/auth/AuthContext";
import {
  createExperimentWorkspaceId,
  activeAssistantTenantContext,
  listExperimentWorkspaces,
  registerExperimentWorkspace,
  removeExperimentWorkspace,
  setActiveAssistantTenantContext,
} from "../features/experiment/workspaceRegistry";
import { assistantArtifactMatchesEdition } from "../features/experiment/assistantProductPolicy";
import { useVoiceInput } from "../features/experiment/useVoiceInput";
import { useModelAccess } from "../features/settings/ModelAccessContext";
import { AssistantModelPicker } from "../components/AssistantModelPicker";
import {
  CloudModelAccessError,
  DEFAULT_MANAGED_MODEL_CATALOG,
  completeManagedModelCatalog,
  getManagedModelCatalog,
  issueManagedModelGrant,
  managedModelAvailableForAssistant,
  type ManagedModelCatalogEntry,
} from "../features/settings/cloudModelAccess";
import {
  localeSafeError,
  useI18n,
  type InterfaceLocale,
} from "../i18n/I18nProvider";
import { useEditionTheme } from "../theme/EditionThemeProvider";
import type {
  ExperimentAssistantDocumentContext,
  ExperimentAssistantTurnResponse,
} from "../types/api";
import type { BrandEditionId } from "../brand/edition-brand.generated";

const TASK_ICON_BY_TYPE: Record<AssistantTaskType, LucideIcon> = {
  control_tuning: SlidersHorizontal,
  mission_autonomy: Route,
  asset_import_qualification: Boxes,
  simulation_experiment: MonitorPlay,
  cross_edition_workflow: GitFork,
  hardware_validation: Microchip,
  calibration: Crosshair,
  sim_to_real: Upload,
  real_to_sim: Download,
  field_task: MapPinned,
};

const COPY = {
  en: {
    title: "What flight experiment should we build?",
    subtitle:
      "Describe the flight, model, constraints, and trial budget; DroneDream will turn your intent into a reviewable experiment draft.",
    manual: "Create manually",
    moreActions: "More ways to start",
    taskType: "Task workflow",
    autoTask: "Auto-detect",
    autoTaskDescription: "Let the model choose the right workflow.",
    importFiles: "Import files",
    removeFile: "Remove file",
    unsupportedFile: "Use JSON, text, Markdown, CSV, YAML, TOML, XML, or log files.",
    fileTooLarge: "Each imported file must contain 4,000 bytes or fewer.",
    tooManyFiles: "You can attach up to 4 reference files.",
    referenceContextTooLarge:
      "Imported reference content must contain 8,000 bytes or fewer in total.",
    emptyFile: "Empty reference files cannot be attached.",
    messageTooLong: "The request must stay within 12,000 characters.",
    attachmentOnlyPrompt: "Use the imported reference files to prepare this experiment.",
    attachmentLabel: "Imported reference files",
    referencePrivacy:
      "DroneDream uses reference content only in this request and does not save it in drafts or memory. Your selected model provider still receives the request.",
    placeholder: "Describe your experiment…",
    send: "Send",
    sending: "Reading your intent…",
    microphone: "Use voice input",
    stopVoice: "Stop voice input",
    requestingVoice: "Requesting microphone access…",
    listening: "Listening…",
    voiceUnsupported: "Voice input is unavailable here. You can keep typing.",
    voiceDenied: "Microphone access was not granted. You can keep typing.",
    voiceFailed: "Voice recognition stopped. You can keep typing.",
    openExperiment: "Open experiment",
    recognized: "Configured",
    needsReview: "Still to decide",
    model: "Model",
    noModel: "None",
    managedModel: "DroneDream Managed",
    managedUnavailable: "No managed conversation model is currently available.",
    modelRequired: "Use the included allowance or configure your API key in Settings.",
    requestFailed: "The model could not compile this draft turn.",
    runtimeOutdated:
      "This installed DroneDreamRuntime does not support AI experiment drafting yet. Update the Runtime before sending again.",
    runtimeUnavailable:
      "DroneDream could not reach the local Runtime. Open Settings and run Check environment, then send again.",
    tokens: "tokens",
    newConversation: "Clear conversation",
    untitledExperiment: "Untitled experiment",
    invalidArtifactLink:
      "This result does not belong to the current account, edition, or workspace.",
    confirmClear:
      "Clear this conversation and discard its current experiment draft?",
    examples: [
      {
        title: "Hover Thrust",
        body: "Using PX4 SITL and Gazebo on X500, tune MPC_THR_HOVER and the related thrust-authority parameters within the catalog safe bounds. Compare repeatable nominal and crosswind hover trials, then validate the final candidate on holdout seeds.",
      },
      {
        title: "Horizontal Tracking",
        body: "Using PX4 SITL and Gazebo on X500, tune MPC_XY_VEL_P_ACC, MPC_XY_VEL_I_ACC, MPC_XY_VEL_D_ACC, and MPC_XY_P on a circular track. Minimize RMSE and worst-case error without violating overshoot or stability constraints, then verify the final candidate on holdout trials.",
      },
      {
        title: "Altitude Tracking",
        body: "Using PX4 SITL and Gazebo on X500, tune MPC_Z_VEL_P_ACC, MPC_Z_VEL_I_ACC, MPC_Z_VEL_D_ACC, and MPC_Z_P. Evaluate climb, descent, and altitude hold in nominal and wind cases, then validate the final candidate on holdout seeds.",
      },
    ],
  },
  "zh-CN": {
    invalidArtifactLink: "此结果不属于当前账号、软件版本或工作空间。",
    title: "想创建怎样的飞行调优实验？",
    subtitle:
      "直接说出轨迹、机型、调优目标、控制参数、仿真场景和次数预算，先生成可审查草案。",
    manual: "手动创建",
    moreActions: "更多创建方式",
    taskType: "任务工作流",
    autoTask: "自动判断",
    autoTaskDescription: "让模型选择合适的工作流。",
    importFiles: "导入参考文件",
    removeFile: "移除文件",
    unsupportedFile: "请选择 JSON、文本、Markdown、CSV、YAML、TOML、XML 或日志文件。",
    fileTooLarge: "每个导入文件的内容不能超过 4,000 字节。",
    tooManyFiles: "最多可以添加 4 个参考文件。",
    referenceContextTooLarge: "导入的参考内容合计不能超过 8,000 字节。",
    emptyFile: "不能添加空白参考文件。",
    messageTooLong: "输入内容不能超过 12,000 个字符。",
    attachmentOnlyPrompt: "请根据导入的参考文件准备这次实验。",
    attachmentLabel: "导入的参考文件",
    referencePrivacy:
      "DroneDream 只在本次请求中使用参考内容，不会写入草稿或长期记忆；你选择的模型服务商仍会收到本次请求。",
    placeholder: "描述你的实验…",
    send: "发送",
    sending: "正在理解你的意图…",
    microphone: "使用语音输入",
    stopVoice: "停止语音输入",
    requestingVoice: "正在请求麦克风权限…",
    listening: "正在聆听…",
    voiceUnsupported: "当前环境不支持语音输入，你仍可继续打字。",
    voiceDenied: "未获得麦克风权限，你仍可继续打字。",
    voiceFailed: "语音识别已停止，你仍可继续打字。",
    openExperiment: "打开实验",
    recognized: "已填写",
    needsReview: "仍需确认",
    model: "模型",
    noModel: "无",
    managedModel: "DroneDream 托管模型",
    managedUnavailable: "当前没有可用的平台托管对话模型。",
    modelRequired: "请在设置中使用赠送额度，或配置自己的 API Key。",
    requestFailed: "模型未能完成这次实验草稿编译。",
    runtimeOutdated:
      "当前安装的 DroneDreamRuntime 尚不支持 AI 创建实验，请先更新 Runtime 再重新发送。",
    runtimeUnavailable:
      "当前无法连接本地 Runtime，请打开设置并主动点击“检查环境”，完成后再重新发送。",
    tokens: "tokens",
    newConversation: "清空对话",
    untitledExperiment: "未命名实验",
    confirmClear: "确定清空这段对话并丢弃当前实验草稿吗？",
    examples: [
      {
        title: "悬停推力调优",
        body: "使用 X500、PX4 SITL 和 Gazebo，在参数目录的安全边界内调优 MPC_THR_HOVER 及相关推力控制参数。比较可重复的无风与侧风悬停场景，再用保留种子验证最终候选。",
      },
      {
        title: "水平航迹跟踪",
        body: "使用 X500、PX4 SITL 和 Gazebo，在圆形航迹上调优 MPC_XY_VEL_P_ACC、MPC_XY_VEL_I_ACC、MPC_XY_VEL_D_ACC 和 MPC_XY_P。在不违反超调和稳定性约束的前提下降低 RMSE 与最坏误差，再完成保留场景验证。",
      },
      {
        title: "高度跟踪",
        body: "使用 X500、PX4 SITL 和 Gazebo，调优 MPC_Z_VEL_P_ACC、MPC_Z_VEL_I_ACC、MPC_Z_VEL_D_ACC 和 MPC_Z_P。评估爬升、下降和定高在无风与有风场景中的表现，再用保留种子验证最终候选。",
      },
    ],
  },
} as const;

type AssistantExample = Readonly<{ title: string; body: string }>;
type EditionAssistantCopy = Readonly<{
  title: string;
  openDraft: string;
  examples: readonly [AssistantExample, AssistantExample, AssistantExample];
}>;

const EDITION_ASSISTANT_COPY: Record<BrandEditionId, EditionAssistantCopy> = {
  universal: {
    title: "What should DroneDream optimize with you?",
    openDraft: "Open optimization draft",
    examples: COPY.en.examples,
  },
  sim: {
    title: COPY.en.title,
    openDraft: "Open experiment draft",
    examples: COPY.en.examples,
  },
  lab: {
    title: "What validation experiment should we build?",
    openDraft: "Open validation draft",
    examples: [
      {
        title: "Sim-to-Real Check",
        body: "Create a lab validation experiment that compares simulation evidence against captured vehicle behavior and highlights the largest mismatches.",
      },
      {
        title: "Calibration Study",
        body: "Prepare a bounded calibration study for the vehicle model, sensors, and controller response with explicit acceptance criteria.",
      },
      {
        title: "Qualification Review",
        body: "Build an independent qualification experiment with holdout evidence, reproducible receipts, and a clear pass or revise decision.",
      },
    ],
  },
  field: {
    title: "What real-device task should we prepare?",
    openDraft: "Open field trial draft",
    examples: [
      {
        title: "Stable Hover Trial",
        body: "Prepare a conservative real-device hover tuning plan with short bounded trials, strict abort limits, snapshots, and rollback checkpoints.",
      },
      {
        title: "Response Tuning",
        body: "Create a reviewable roll and pitch response tuning plan that preserves stability margins and requires operator approval before execution.",
      },
      {
        title: "Field Recovery Test",
        body: "Draft a disturbance-recovery field trial with live telemetry, an independent holdout, safety boundaries, and a rollback plan.",
      },
    ],
  },
  autonomy: {
    title: "What autonomous mission should we plan?",
    openDraft: "Open mission workspace",
    examples: [
      {
        title: "Choose Qualified Assets",
        body: "Use only an aircraft-map pair that has completed simulation qualification. Reuse the current context, ask only for missing mission details, and then prepare a reviewable 3D plan.",
      },
      {
        title: "Pickup and Return",
        body: "Prepare a pickup-and-return mission with qualified assets. Ask for the pickup place or item only if it is still missing, and check payload, battery, clearance, pickup confirmation, and the return route.",
      },
      {
        title: "Route Change Recovery",
        body: "Prepare a mission that enters a safe hold when the destination changes, preserves completed task facts, validates a replacement route, and continues only when that route is feasible.",
      },
    ],
  },
};

const EDITION_ASSISTANT_TITLES: Readonly<
  Record<InterfaceLocale, Readonly<Record<BrandEditionId, string>>>
> = {
  en: {
    universal: "What should DroneDream optimize with you?",
    sim: "What flight experiment should we build?",
    lab: "What validation experiment should we build?",
    field: "What real-device task should we prepare?",
    autonomy: "What autonomous mission should we plan?",
  },
  "zh-CN": {
    universal: "想让 DroneDream 与你设计什么？",
    sim: "想创建怎样的飞行调优实验？",
    lab: "想创建怎样的验证实验？",
    field: "想准备怎样的真机任务？",
    autonomy: "想规划怎样的自主任务？",
  },
};

const ACCEPTED_REFERENCE_EXTENSIONS = new Set([
  "csv",
  "json",
  "log",
  "md",
  "toml",
  "txt",
  "xml",
  "yaml",
  "yml",
]);
const MAX_REFERENCE_FILES = 4;
const MAX_REFERENCE_FILE_BYTES = 4_000;
const MAX_REFERENCE_CONTEXT_BYTES = 8_000;
const MAX_ASSISTANT_MESSAGE_LENGTH = 12_000;

interface AssistantReferenceFile {
  id: string;
  name: string;
  content: string;
  contentBytes: number;
  contentSha256: string;
}

function referenceFileExtension(fileName: string): string {
  const separator = fileName.lastIndexOf(".");
  return separator >= 0 ? fileName.slice(separator + 1).toLowerCase() : "";
}

async function sha256Hex(content: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(content),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function requestOnlyDocumentContext(
  files: AssistantReferenceFile[],
): ExperimentAssistantDocumentContext | null {
  if (!files.length) return null;
  return {
    schema_version: "1.0",
    purpose: "experiment_draft_reference",
    chunks: files.map((file) => ({
      schema_version: "1.0",
      document_id: `document-${file.id}`,
      chunk_id: "chunk-1",
      display_name: file.name,
      content: file.content,
      content_sha256: file.contentSha256,
      retention: "request_only",
    })),
  };
}

const FIELD_LABELS: Record<string, { en: string; "zh-CN": string }> = {
  display_name: { en: "Name", "zh-CN": "实验名称" },
  track_type: { en: "Track", "zh-CN": "轨迹" },
  circle_radius_m: { en: "Radius", "zh-CN": "半径" },
  altitude_m: { en: "Altitude", "zh-CN": "高度" },
  objective_profile: { en: "Objective", "zh-CN": "调优目标" },
  simulator_backend: { en: "Simulator", "zh-CN": "仿真后端" },
  optimizer_strategy: { en: "Optimizer", "zh-CN": "优化策略" },
  max_total_trials: { en: "Trial budget", "zh-CN": "仿真预算" },
  parameters: { en: "PX4 parameters", "zh-CN": "PX4 参数" },
};

function messageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function voiceMessage(
  key: string | null,
  copy: (typeof COPY)[keyof typeof COPY],
): string | null {
  if (!key) return null;
  if (key === "voice_not_supported") return copy.voiceUnsupported;
  if (key === "microphone_permission_denied") return copy.voiceDenied;
  return copy.voiceFailed;
}

function AssistantTemplateIcon({ index }: { index: number }) {
  const Icon = [Orbit, Wind, Workflow][index] ?? Workflow;
  return <Icon className="assistant-example-icon" aria-hidden="true" strokeWidth={1.8} />;
}

function CloudTerminalIcon() {
  return (
    <svg
      className="assistant-cloud-terminal-icon"
      viewBox="0 0 112 80"
      role="presentation"
      focusable="false"
    >
      <path
        d="M34 65h48c14.4 0 26-10.8 26-24.2 0-12.5-10.2-22.9-23.3-24.1C79.2 7.3 68.5 2 57.2 4.2 43.8 6.8 34.4 17 32.9 29.4 17.7 29.9 5.5 40.2 5.5 47.8 5.5 57.4 18.3 65 34 65Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        className="assistant-terminal-chevron"
        d="m38 39 10 8-10 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        className="assistant-terminal-underscore"
        d="M55 55h17"
        fill="none"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function acceptedFieldLabels(
  response: ExperimentAssistantTurnResponse,
  locale: "en" | "zh-CN",
): string[] {
  const fields = response.accepted_patches.map((patch) => patch.field_id);
  if (response.accepted_parameter_patches.length) fields.push("parameters");
  return [...new Set(fields)].map(
    (fieldId) => FIELD_LABELS[fieldId]?.[locale] ?? fieldId,
  );
}

function reviewLabels(
  response: ExperimentAssistantTurnResponse,
  locale: "en" | "zh-CN",
): string[] {
  return [...response.missing_field_ids, ...response.review_field_ids].map(
    (fieldId) => FIELD_LABELS[fieldId]?.[locale] ?? fieldId,
  );
}

function assistantErrorMessage(
  reason: unknown,
  copy: (typeof COPY)[keyof typeof COPY],
  locale: InterfaceLocale,
): string {
  const errorLocale = locale === "zh-CN" ? "zh-CN" : "en";
  if (reason instanceof CloudModelAccessError) return localeSafeError(reason, errorLocale, { zh: copy.requestFailed, en: copy.requestFailed });
  if (!(reason instanceof ApiClientError)) return copy.requestFailed;
  if (reason.httpStatus === 404 || reason.code === "NOT_FOUND") {
    return copy.runtimeOutdated;
  }
  if (
    reason.code === "NETWORK_ERROR" ||
    reason.code === "DESKTOP_RUNTIME_NOT_READY"
  ) {
    return copy.runtimeUnavailable;
  }
  return localeSafeError(reason, errorLocale, { zh: copy.requestFailed, en: copy.requestFailed });
}

export function ExperimentAssistant() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { interfaceLocale, locale } = useI18n();
  const editionTheme = useEditionTheme();
  const auth = useOptionalAuth();
  const ownerId = auth?.account?.id ?? "local";
  const copy = COPY[locale];
  const chinese = interfaceLocale === "zh-CN";
  const editionCopy = {
    ...(locale === "en"
      ? EDITION_ASSISTANT_COPY[editionTheme.id]
      : {
          title: copy.title,
          openDraft: copy.openExperiment,
          examples: copy.examples,
        }),
    title: EDITION_ASSISTANT_TITLES[interfaceLocale][editionTheme.id],
  };
  const requestedWorkspaceId = (() => {
    const value = searchParams.get("experiment")?.trim() ?? "";
    return /^[a-zA-Z0-9_-]{8,128}$/u.test(value) ? value : null;
  })();
  const requestedArtifactId = (() => {
    const value = searchParams.get("artifact")?.trim() ?? "";
    return /^[0-9a-f]{8}-[0-9a-f-]{27}$/iu.test(value) ? value : null;
  })();
  const initialWorkspace = useRef((() => {
    const workspaces = listExperimentWorkspaces(ownerId, editionTheme.id);
    return (requestedWorkspaceId
      ? workspaces.find((workspace) => workspace.id === requestedWorkspaceId)
      : workspaces.find(
        (workspace) => workspace.source === "assistant" && !workspace.archived,
      )) ?? null;
  })()).current;
  function openDraftPath(): string {
    if (latest?.orchestration?.intent === "mission_autonomy") {
      return "/autonomy?from=tuning-chat";
    }
    if (latest?.orchestration?.artifact_kind === "external_asset_qualification_plan") {
      return "/autonomy";
    }
    if (latest?.orchestration?.artifact_kind === "universal_vehicle_model") {
      return "/autonomy/aircraft";
    }
    if (editionTheme.id === "universal") {
      return workspaceId
        ? `/jobs/new?experiment=${encodeURIComponent(workspaceId)}`
        : "/jobs/new";
    }
    if (editionTheme.id === "field") {
      return workspaceId
        ? `/field?experiment=${encodeURIComponent(workspaceId)}`
        : "/field";
    }
    if (editionTheme.id === "lab") {
      return workspaceId
        ? `/lab?experiment=${encodeURIComponent(workspaceId)}`
        : "/lab";
    }
    return workspaceId
      ? `/jobs/new?experiment=${encodeURIComponent(workspaceId)}`
      : "/jobs/new";
  }
  const {
    settings: modelAccess,
    profiles: modelProfiles,
    activeProfileId,
    selectAccessMode,
    selectManagedModel,
    selectProfile,
  } = useModelAccess();
  const docsPreview = import.meta.env.DEV
    && new URLSearchParams(window.location.search).has("docsPreview");
  const [managedModels, setManagedModels] = useState<ManagedModelCatalogEntry[]>(
    docsPreview || !auth?.account
      ? DEFAULT_MANAGED_MODEL_CATALOG
      : completeManagedModelCatalog([]),
  );
  const [managedModelsReady, setManagedModelsReady] = useState(
    docsPreview || !auth?.account,
  );
  const assistantManagedModels = managedModels;
  const configuredModelProfiles = modelProfiles.filter((profile) =>
    profile.apiKey.trim(),
  );
  const selectedManagedModel = assistantManagedModels.find(
    (model) => model.provider === modelAccess.managedProvider
      && model.model === modelAccess.managedModel
      && managedModelAvailableForAssistant(model),
  );
  const selectedCustomProfileId = modelAccess.accessMode === "byok"
    && configuredModelProfiles.some((profile) => profile.id === activeProfileId)
      ? activeProfileId
      : null;
  const [draft, setDraft] = useState<AssistantDraft>(() =>
    initialWorkspace
      ? loadAssistantDraft(initialWorkspace.id)
      : createEmptyAssistantDraft(),
  );
  const [workspaceId, setWorkspaceId] = useState<string | null>(
    initialWorkspace?.id ?? requestedWorkspaceId,
  );
  const [composer, setComposer] = useState("");
  const [pending, setPending] = useState(false);
  const [runStage, setRunStage] = useState<AssistantRunStage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [selectedTaskType, setSelectedTaskType] = useState<AssistantTaskType | null>(() =>
    editionTheme.id === "autonomy" ? "mission_autonomy" : "control_tuning",
  );
  const [referenceFiles, setReferenceFiles] = useState<AssistantReferenceFile[]>(
    [],
  );
  const [latest, setLatest] = useState<ExperimentAssistantTurnResponse | null>(
    null,
  );
  const pendingRef = useRef(false);
  const restoredWorkspaceRef = useRef<string | null>(null);
  const actionMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (docsPreview) {
      setManagedModels(DEFAULT_MANAGED_MODEL_CATALOG);
      setManagedModelsReady(true);
      return;
    }
    if (!auth?.account) {
      setManagedModels(DEFAULT_MANAGED_MODEL_CATALOG);
      setManagedModelsReady(true);
      return;
    }
    let active = true;
    setManagedModelsReady(false);
    void getManagedModelCatalog()
      .then((catalog) => {
        if (!active) return;
        setManagedModels(completeManagedModelCatalog(catalog.models));
        setManagedModelsReady(true);
      })
      .catch(() => {
        if (!active) return;
        setManagedModels(completeManagedModelCatalog([]));
        setManagedModelsReady(true);
      });
    return () => {
      active = false;
    };
  }, [
    auth?.account,
    docsPreview,
  ]);

  useEffect(() => {
    if (
      modelAccess.accessMode === "platform"
      && assistantManagedModels.some(managedModelAvailableForAssistant)
      && !assistantManagedModels.some(
        (model) => model.provider === modelAccess.managedProvider
          && model.model === modelAccess.managedModel
          && managedModelAvailableForAssistant(model),
      )
    ) {
      const fallback = assistantManagedModels.find(managedModelAvailableForAssistant);
      if (!fallback) return;
      selectManagedModel(
        fallback.provider,
        fallback.model,
      );
    }
  }, [
    assistantManagedModels,
    modelAccess.managedModel,
    modelAccess.managedProvider,
    modelAccess.accessMode,
    selectManagedModel,
  ]);

  const appendTranscript = useCallback((transcript: string) => {
    setComposer((current) =>
      current.trim() ? `${current.trim()} ${transcript}` : transcript,
    );
  }, []);
  const voice = useVoiceInput({
    locale,
    onTranscript: appendTranscript,
    continuous: true,
    maxDurationMs: 5 * 60_000,
  });
  const messages = draft.conversation.messages;
  const taskOptions = assistantTaskOptions(editionTheme.id, interfaceLocale);
  const selectedTask = taskOptions.find(({ id }) => id === selectedTaskType) ?? null;
  const selectTask = (task: AssistantTaskType) => {
    setActionMenuOpen(false);
    if (task === "mission_autonomy" && !publicDemoConsole) {
      storeAutonomyHandoff(composer);
      navigate("/autonomy?from=tuning-chat");
      return;
    }
    setSelectedTaskType(task);
  };

  useEffect(() => {
    if (!publicDemoConsole || !auth?.account || !workspaceId) return;
    const restoreKey = `${editionTheme.id}:${workspaceId}`;
    if (restoredWorkspaceRef.current === restoreKey) return;
    restoredWorkspaceRef.current = restoreKey;
    let active = true;
    const tenantContext = activeAssistantTenantContext(ownerId);
    void getAssistantWorkspace(
      editionTheme.id,
      workspaceId,
      tenantContext.organizationId,
    )
      .then((snapshot) => {
        if (!active || !snapshot) return;
        setActiveAssistantTenantContext(ownerId, {
          tenantId: snapshot.conversation.tenant_id,
          organizationId: snapshot.conversation.organization_id,
        });
        const serverMessages = snapshot.messages.slice(-60).map((message) => ({
          id: message.message_id,
          role: message.role,
          content: message.content,
        }));
        // A turn may have started while this snapshot was in flight. In that
        // case neither the restored transcript nor its latest result is
        // allowed to overwrite the newer local turn.
        if (pendingRef.current) return;
        setDraft((current) => {
          const next = {
            ...current,
            conversation: {
              ...current.conversation,
              summary: snapshot.conversation.summary,
              messages: serverMessages,
            },
          };
          persistAssistantDraft(next, workspaceId);
          return next;
        });
        const restoredLatest = requestedArtifactId
          ? completedAssistantResponseForArtifact(snapshot, requestedArtifactId)
          : latestCompletedAssistantResponse(snapshot);
        if (requestedArtifactId && !restoredLatest) {
          setError(copy.invalidArtifactLink);
          return;
        }
        if (restoredLatest) {
          registerExperimentWorkspace({
            id: workspaceId,
            ownerId,
            tenantId: snapshot.conversation.tenant_id,
            organizationId: snapshot.conversation.organization_id,
            edition: editionTheme.id,
            name:
              restoredLatest.assistant_message?.trim()
              || copy.untitledExperiment,
            source: "assistant",
            activeStep: 1,
            completedSteps: [0],
            assistantArtifactKind: restoredLatest.orchestration?.artifact_kind ?? null,
          });
          setLatest(restoredLatest);
        }
      })
      .catch((reason) => {
        if (!active) return;
        restoredWorkspaceRef.current = null;
        setError(assistantErrorMessage(reason, copy, interfaceLocale));
      });
    return () => {
      active = false;
    };
  }, [
    auth?.account,
    copy,
    editionTheme.id,
    interfaceLocale,
    ownerId,
    requestedArtifactId,
    workspaceId,
  ]);

  useEffect(() => {
    if (!actionMenuOpen) return undefined;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !actionMenuRef.current?.contains(event.target)
      ) {
        setActionMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, [actionMenuOpen]);

  async function importReferenceFiles(
    event: ChangeEvent<HTMLInputElement>,
  ): Promise<void> {
    const selected = [...(event.target.files ?? [])];
    event.target.value = "";
    if (!selected.length) return;
    if (referenceFiles.length + selected.length > MAX_REFERENCE_FILES) {
      setError(copy.tooManyFiles);
      return;
    }
    const imported: AssistantReferenceFile[] = [];
    let totalContentBytes = referenceFiles.reduce(
      (total, file) => total + file.contentBytes,
      0,
    );
    for (const file of selected) {
      if (!ACCEPTED_REFERENCE_EXTENSIONS.has(referenceFileExtension(file.name))) {
        setError(copy.unsupportedFile);
        return;
      }
      if (file.size > MAX_REFERENCE_FILE_BYTES) {
        setError(copy.fileTooLarge);
        return;
      }
      const content = await file.text();
      const contentBytes = new TextEncoder().encode(content).byteLength;
      if (!content.trim()) {
        setError(copy.emptyFile);
        return;
      }
      if (contentBytes > MAX_REFERENCE_FILE_BYTES) {
        setError(copy.fileTooLarge);
        return;
      }
      totalContentBytes += contentBytes;
      if (totalContentBytes > MAX_REFERENCE_CONTEXT_BYTES) {
        setError(copy.referenceContextTooLarge);
        return;
      }
      imported.push({
        id: messageId(),
        name: file.name,
        content,
        contentBytes,
        contentSha256: await sha256Hex(content),
      });
    }
    setReferenceFiles((current) => [...current, ...imported]);
    setError(null);
  }

  async function submitMessage(event: FormEvent): Promise<void> {
    event.preventDefault();
    const submittedComposer = composer;
    const submittedReferenceFileIds = new Set(
      referenceFiles.map((file) => file.id),
    );
    const visibleMessage = composer.trim() || copy.attachmentOnlyPrompt;
    if (
      (!composer.trim() && !referenceFiles.length)
      || pendingRef.current
    ) {
      return;
    }
    if (!publicDemoConsole && selectedTaskType === "mission_autonomy") {
      storeAutonomyHandoff(visibleMessage);
      navigate("/autonomy?from=tuning-chat");
      return;
    }
    if (visibleMessage.length > MAX_ASSISTANT_MESSAGE_LENGTH) {
      setError(copy.messageTooLong);
      return;
    }
    const requiresModelProvider = selectedTaskType === null
      || selectedTaskType === "control_tuning";
    if (
      requiresModelProvider
      && modelAccess.accessMode === "byok"
      && !modelAccess.apiKey.trim()
    ) {
      setError(copy.modelRequired);
      openAppSettings("model");
      return;
    }
    if (
      requiresModelProvider
      &&
      modelAccess.accessMode === "platform"
      && (!managedModelsReady || !selectedManagedModel)
    ) {
      setError(copy.managedUnavailable);
      return;
    }
    const id = messageId();
    pendingRef.current = true;
    setPending(true);
    setRunStage("queued");
    setError(null);
    try {
      const targetWorkspaceId = workspaceId ?? createExperimentWorkspaceId();
      const platformAccess = requiresModelProvider
        && modelAccess.accessMode === "platform"
        && !publicDemoConsole
        ? await issueManagedModelGrant(
            "assistant",
            targetWorkspaceId,
            selectedManagedModel!.provider,
            selectedManagedModel!.model,
          )
        : null;
      const documentContext = requestOnlyDocumentContext(referenceFiles);
      const result = publicDemoConsole
        ? modelAccess.accessMode === "platform" && selectedManagedModel
          ? (await orchestrateAssistantTurn({
              edition: editionTheme.id,
              workspaceId: targetWorkspaceId,
              organizationId: activeAssistantTenantContext(ownerId).organizationId,
              idempotencyKey: `assistant:${id}`,
              selectedModel: selectedManagedModel,
              locale,
              message: visibleMessage,
              requestedTaskType: selectedTaskType,
              currentValues: assistantCurrentValues(draft.form),
              documentContext,
              onStage: setRunStage,
            })).response
          : (() => {
              throw new CloudModelAccessError(
                "PLATFORM_ACCESS_REQUIRED",
                "The public console uses the included DroneDream managed-model allowance.",
                400,
              );
            })()
        : await apiClient.compileExperimentAssistantTurn({
        message_id: id,
        conversation_id: targetWorkspaceId,
        message: visibleMessage,
        locale,
        edition: editionTheme.id,
        requested_task_type: selectedTaskType ?? "auto_detect",
        conversation_summary: draft.conversation.summary,
        current_values: assistantCurrentValues(draft.form),
        explicit_field_ids: explicitAssistantFields(draft.conversation),
        current_parameters: assistantCurrentParameters(draft.selections),
        document_context: documentContext,
        llm: !requiresModelProvider
          ? null
          : modelAccess.accessMode === "platform"
          ? {
              access_mode: "platform",
              provider: "dronedream",
              platform_grant: platformAccess?.grant ?? null,
              api_key: null,
              model: null,
              base_url: null,
            }
          : {
              access_mode: "byok",
              provider: modelAccess.provider,
              api_key: modelAccess.apiKey,
              platform_grant: null,
              model: modelAccess.model.trim() || null,
              base_url: modelAccess.baseUrl.trim() || null,
            },
      });
      const next = applyAssistantTurn(
        draft,
        result,
        {
          id,
          role: "user",
          content: referenceFiles.length
            ? `${visibleMessage}\n\n${copy.attachmentLabel}: ${referenceFiles
                .map((file) => file.name)
                .join(" · ")}`
            : visibleMessage,
        },
        targetWorkspaceId,
      );
      const workflowBlocked = result.orchestration?.artifact_payload?.status === "blocked";
      const currentArtifactKind = result.orchestration?.artifact_kind ?? null;
      const persistableArtifactKind = !workflowBlocked
        && currentArtifactKind
        && assistantArtifactMatchesEdition(editionTheme.id, currentArtifactKind)
        ? currentArtifactKind
        : null;
      registerExperimentWorkspace({
        id: targetWorkspaceId,
        ownerId,
        tenantId: result.orchestration?.tenant_id,
        organizationId: result.orchestration?.organization_id,
        edition: editionTheme.id,
        name:
          next.form.display_name.trim()
          || result.experiment_summary.trim().slice(0, 255)
          || copy.untitledExperiment,
        source: "assistant",
        activeStep: next.activeStep,
        completedSteps: next.completedSteps,
        assistantArtifactKind: persistableArtifactKind,
        vehicleDraftId: null,
      });
      if (!workspaceId) {
        setWorkspaceId(targetWorkspaceId);
      }
      setDraft(next);
      setLatest(result);
      if (result.orchestration?.intent === "mission_autonomy") {
        storeAutonomyHandoff(visibleMessage);
      }
      setComposer((current) => current === submittedComposer ? "" : current);
      setReferenceFiles((current) => current.filter(
        (file) => !submittedReferenceFileIds.has(file.id),
      ));
    } catch (reason) {
      setError(assistantErrorMessage(reason, copy, interfaceLocale));
    } finally {
      pendingRef.current = false;
      setPending(false);
      setRunStage(null);
    }
  }

  function handleExample(example: string): void {
    setComposer(example);
  }

  function toggleVoiceInput(): void {
    if (voice.state === "listening" || voice.state === "requesting") {
      voice.stop();
      return;
    }
    void voice.start();
  }

  const voiceButtonLabel =
    voice.state === "requesting"
      ? copy.requestingVoice
      : voice.state === "listening"
        ? copy.stopVoice
        : voice.state === "error"
          ? voiceMessage(voice.error, copy) ?? copy.microphone
          : copy.microphone;
  const configuredLabels = latest
    ? acceptedFieldLabels(latest, locale)
    : [];
  const remainingLabels = latest ? reviewLabels(latest, locale) : [];

  return (
    <section
      className={`experiment-assistant-page ${messages.length ? "has-messages" : ""}`}
      data-brand-edition={editionTheme.id}
      data-grants-hardware-authority="false"
    >
      <div className="experiment-assistant-stage">
        {messages.length === 0 ? (
          <div className="assistant-empty-state">
            <div className="assistant-hero-icon" aria-hidden="true">
              <CloudTerminalIcon />
            </div>
            <h1>{editionCopy.title}</h1>
            <div className="assistant-examples">
              {editionCopy.examples.map((example, index) => (
                <button
                  key={example.title}
                  type="button"
                  aria-label={example.title}
                  onClick={() => handleExample(example.body)}
                >
                  <span className="assistant-example-heading">
                    <AssistantTemplateIcon index={index} />
                    <span>
                      <strong>{example.title}</strong>
                      <small>{example.body}</small>
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="assistant-thread" aria-live="polite">
            <div className="assistant-thread-toolbar">
              <button
                type="button"
                onClick={() => {
                  if (!window.confirm(copy.confirmClear)) return;
                  voice.stop();
                  setDraft(clearAssistantDraft(workspaceId));
                  if (workspaceId) {
                    removeExperimentWorkspace(ownerId, workspaceId, editionTheme.id);
                    setWorkspaceId(null);
                  } else {
                    clearExperimentDraft();
                  }
                  setLatest(null);
                  setComposer("");
                  setReferenceFiles([]);
                  setActionMenuOpen(false);
                  setSelectedTaskType(null);
                  setError(null);
                }}
              >
                {copy.newConversation}
              </button>
            </div>
            {messages.map((message) => (
              <article
                key={message.id}
                className={`assistant-message ${message.role}`}
              >
                <p>{message.content}</p>
              </article>
            ))}
            {pending ? (
              <article className="assistant-message assistant pending">
                <p>{runStage
                  ? locale === "zh-CN"
                    ? {
                        queued: "已进入当前对话队列…",
                        analyzing: "正在分析意图与工作空间边界…",
                        planning: "正在编排工作流程…",
                        calling_tools: "正在生成并保存可审阅草稿…",
                        validating: "正在校验草稿与安全边界…",
                        retry_wait: "模型服务繁忙，任务已安全进入重试队列…",
                        completed: "草稿已完成。",
                        failed_recoverable: "任务失败，但可以安全恢复重试。",
                        failed: "草稿创建失败。",
                      }[runStage]
                    : {
                        queued: "Queued for this conversation…",
                        analyzing: "Analyzing the intent and workspace boundary…",
                        planning: "Planning the workflow…",
                        calling_tools: "Creating and saving the reviewable draft…",
                        validating: "Validating the draft and safety boundary…",
                        retry_wait: "Provider busy; the task is safely queued for retry…",
                        completed: "Draft completed.",
                        failed_recoverable: "The task failed but can be safely retried.",
                        failed: "Draft creation failed.",
                      }[runStage]
                  : copy.sending}</p>
              </article>
            ) : null}
            {latest ? (
              <div className="assistant-draft-result">
                {latest.orchestration?.workflow.length ? (
                  <ol className="assistant-workflow-receipt" aria-label={locale === "zh-CN" ? "任务步骤" : "Task steps"}>
                    {latest.orchestration.workflow.map((step: AssistantWorkflowStep) => (
                      <li key={step.step} data-status={step.status}>
                        <span aria-hidden="true">{
                          step.status === "completed" ? "✓"
                            : step.status === "proposed" ? "→"
                              : step.status === "refused" ? "×" : "!"
                        }</span>
                        <span>{step.label}</span>
                      </li>
                    ))}
                  </ol>
                ) : null}
                {configuredLabels.length ? (
                  <div>
                    <strong>{copy.recognized}</strong>
                    <span>{configuredLabels.join(" · ")}</span>
                  </div>
                ) : null}
                {remainingLabels.length ? (
                  <div>
                    <strong>{copy.needsReview}</strong>
                    <span>{remainingLabels.join(" · ")}</span>
                  </div>
                ) : null}
                {latest.orchestration?.generated_files?.length ? (
                  <div className="assistant-generated-file">
                    <strong>{locale === "zh-CN" ? "已保存产物" : "Saved artifact"}</strong>
                    <span>{latest.orchestration.generated_files[0].display_name}</span>
                  </div>
                ) : null}
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => navigate(openDraftPath())}
                >
                  {editionCopy.openDraft}
                </button>
              </div>
            ) : null}
          </div>
        )}
      </div>

      <form className="assistant-composer" onSubmit={submitMessage}>
        <input
          ref={fileInputRef}
          className="assistant-reference-input"
          type="file"
          multiple
          tabIndex={-1}
          accept=".json,.txt,.md,.csv,.yaml,.yml,.toml,.xml,.log,text/plain,text/csv,application/json"
          aria-hidden="true"
          onChange={(event) => {
            void importReferenceFiles(event);
          }}
        />
        <textarea
          value={composer}
          maxLength={12_000}
          rows={3}
          placeholder={copy.placeholder}
          aria-label={copy.placeholder}
          onChange={(event) => setComposer(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        {referenceFiles.length ? (
          <>
            <div className="assistant-reference-files" aria-label={copy.attachmentLabel}>
              {referenceFiles.map((file) => (
                <span key={file.id}>
                  <FileText aria-hidden="true" strokeWidth={1.8} />
                  <b title={file.name}>{file.name}</b>
                  <button
                    type="button"
                    aria-label={`${copy.removeFile}: ${file.name}`}
                    title={`${copy.removeFile}: ${file.name}`}
                    onClick={() =>
                      setReferenceFiles((current) =>
                        current.filter((item) => item.id !== file.id),
                      )
                    }
                  >
                    <X aria-hidden="true" strokeWidth={1.9} />
                  </button>
                </span>
              ))}
            </div>
            <p className="assistant-reference-privacy">{copy.referencePrivacy}</p>
          </>
        ) : null}
        <div className="assistant-composer-bar">
          <div
            ref={actionMenuRef}
            className="assistant-add-menu"
            onKeyDown={(event) => {
              if (event.key === "Escape") setActionMenuOpen(false);
            }}
          >
            <button
              type="button"
              className="assistant-add-button"
              aria-label={copy.moreActions}
              title={copy.moreActions}
              aria-haspopup="menu"
              aria-expanded={actionMenuOpen}
              onClick={() => setActionMenuOpen((current) => !current)}
            >
              <Plus aria-hidden="true" strokeWidth={1.8} />
            </button>
            {actionMenuOpen ? (
              <div className="assistant-add-popover assistant-task-popover" role="menu">
                <strong className="assistant-task-popover-title">{copy.taskType}</strong>
                {taskOptions.map((task) => {
                  const TaskIcon = TASK_ICON_BY_TYPE[task.id];
                  return (
                    <button
                      key={task.id}
                      type="button"
                      role="menuitemradio"
                      aria-checked={selectedTaskType === task.id}
                      data-task-icon={task.id}
                      className={selectedTaskType === task.id ? "is-selected" : ""}
                      onClick={() => selectTask(task.id)}
                    >
                      <span className="assistant-task-icon" aria-hidden="true">
                        <TaskIcon strokeWidth={1.8} />
                      </span>
                      <span className="assistant-task-popover-copy"><b>{task.label}</b></span>
                    </button>
                  );
                })}
                <hr />
                <Link data-task-icon="manual" to="/jobs/new" role="menuitem" onClick={() => setActionMenuOpen(false)}>
                  <span className="assistant-task-icon" aria-hidden="true">
                    <PencilRuler strokeWidth={1.8} />
                  </span>
                  <span>{copy.manual}</span>
                </Link>
                <button
                  type="button"
                  role="menuitem"
                  data-task-icon="import"
                  onClick={() => {
                    setActionMenuOpen(false);
                    fileInputRef.current?.click();
                  }}
                >
                  <span className="assistant-task-icon" aria-hidden="true">
                    <FileUp strokeWidth={1.8} />
                  </span>
                  <span>{copy.importFiles}</span>
                </button>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className={`assistant-task-chip ${selectedTask ? "is-explicit" : ""}`}
            onClick={() => setActionMenuOpen(true)}
          >
            {selectedTask
              ? selectedTask.label
              : taskOptions.find(({ id }) => id === "control_tuning")?.label ?? copy.autoTask}
          </button>
          <span className="assistant-composer-spacer" />
          <AssistantModelPicker
            ariaLabel={copy.model}
            chooseModelLabel={chinese ? "选择模型" : "Choose model"}
            defaultGroupLabel={chinese ? "默认" : "Default"}
            customGroupLabel={chinese ? "自定义" : "Custom"}
            addCustomModelLabel={chinese ? "添加自定义模型" : "Add custom model"}
            temporarilyUnavailableLabel={chinese ? "暂时不可用" : "Temporarily unavailable"}
            defaultModels={assistantManagedModels}
            customProfiles={configuredModelProfiles}
            selectedDefault={modelAccess.accessMode === "platform" ? selectedManagedModel ?? null : null}
            selectedCustomId={selectedCustomProfileId}
            disabled={
              pending
              || (modelAccess.accessMode === "platform" && !managedModelsReady)
            }
            onSelectDefault={(model) => {
              selectAccessMode("platform");
              selectManagedModel(model.provider, model.model);
            }}
            onSelectCustom={(profileId) => {
              selectProfile(profileId);
              selectAccessMode("byok");
            }}
            onOpenSettings={() => openAppSettings("model")}
          />
          <button
            type="button"
            className={`assistant-voice-button ${
              voice.state === "listening"
                ? "listening"
                : voice.state === "requesting"
                  ? "requesting"
                  : voice.state === "error" ? "error" : ""
            }`}
            aria-label={voiceButtonLabel}
            aria-pressed={voice.state === "listening"}
            title={voiceButtonLabel}
            onClick={toggleVoiceInput}
          >
            {voice.state === "requesting" ? (
              <LoaderCircle aria-hidden="true" strokeWidth={1.9} />
            ) : voice.state === "listening" ? (
              <Square className="assistant-voice-stop-icon" aria-hidden="true" strokeWidth={1.9} />
            ) : voice.state === "error" ? (
              <MicOff aria-hidden="true" strokeWidth={1.9} />
            ) : (
              <Mic aria-hidden="true" strokeWidth={1.9} />
            )}
          </button>
          <button
            type="submit"
            className="assistant-send-button"
            disabled={(!composer.trim() && !referenceFiles.length) || pending}
            aria-label={copy.send}
            title={copy.send}
          >
            <ArrowUp aria-hidden="true" strokeWidth={2} />
          </button>
        </div>
        {error ? (
          <p className="assistant-composer-error" role="alert">
            {error}
          </p>
        ) : null}
      </form>
    </section>
  );
}
