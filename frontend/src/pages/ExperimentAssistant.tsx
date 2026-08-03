import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowUp,
  Cloud,
  FileText,
  Mic,
  Orbit,
  Paperclip,
  PencilRuler,
  Plus,
  Wind,
  Workflow,
  X,
} from "lucide-react";

import { apiClient, ApiClientError } from "../api/client";
import { openAppSettings } from "../appSettings";
import { isDesktopRuntime } from "../desktop/bridge";
import { recordProductEvent } from "../features/analytics/productEvents";
import {
  applyAssistantTurn,
  assistantCurrentParameters,
  assistantCurrentValues,
  clearAssistantDraft,
  explicitAssistantFields,
  loadAssistantDraft,
  type AssistantDraft,
} from "../features/experiment/assistantDraft";
import { clearExperimentDraft } from "../features/experiment/draftStorage";
import { useOptionalAuth } from "../features/auth/AuthContext";
import {
  createExperimentWorkspaceId,
  registerExperimentWorkspace,
  removeExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";
import { useVoiceInput } from "../features/experiment/useVoiceInput";
import {
  modelProviderLabel,
  useModelAccess,
} from "../features/settings/ModelAccessContext";
import {
  CloudModelAccessError,
  getManagedModelCatalog,
  issueManagedModelGrant,
  type ManagedModelCatalogEntry,
} from "../features/settings/cloudModelAccess";
import { useI18n } from "../i18n/I18nProvider";
import type {
  ExperimentAssistantDocumentContext,
  ExperimentAssistantTurnResponse,
} from "../types/api";

const COPY = {
  en: {
    title: "What flight experiment should we build?",
    subtitle:
      "Describe the flight, model, constraints, and trial budget; DroneDream will turn your intent into a reviewable experiment draft.",
    manual: "Create manually",
    moreActions: "More ways to start",
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
    voiceConsentDesktop:
      "Windows WebView2 may send microphone audio to Microsoft for speech transcription. Audio is not added to the experiment draft.",
    voiceConsentWeb:
      "Your browser may send microphone audio to its speech service for transcription. Audio is not added to the experiment draft.",
    startVoice: "Allow and start",
    cancelVoice: "Cancel",
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
    confirmClear:
      "Clear this conversation and discard its current experiment draft?",
    examples: [
      {
        title: "Circular Track",
        body: "Tune an x500 on a 5 m circular track at 3 m altitude, balancing tracking accuracy, wind robustness, and repeatable trials.",
      },
      {
        title: "Wind Robustness",
        body: "Build a robust windy experiment, compare trusted optimizers within 220 trials, and verify the best parameters.",
      },
      {
        title: "Harness Decisions",
        body: "Use real PX4/Gazebo, tune horizontal control parameters, and let the Harness select tools from each evidence update.",
      },
    ],
  },
  "zh-CN": {
    title: "想创建怎样的飞行调优实验？",
    subtitle:
      "直接说出轨迹、机型、调优目标、控制参数、仿真场景和次数预算，先生成可审查草案。",
    manual: "手动创建",
    moreActions: "更多创建方式",
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
    voiceConsentDesktop:
      "Windows WebView2 可能将麦克风音频发送给 Microsoft 完成语音转写，原始音频不会写入实验草稿。",
    voiceConsentWeb:
      "浏览器可能将麦克风音频发送给其语音服务完成转写，原始音频不会写入实验草稿。",
    startVoice: "允许并开始",
    cancelVoice: "取消",
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
        title: "圆形航迹调优",
        body: "让 x500 在 3 米高度沿半径 5 米的圆形轨迹飞行，并重点改善跟踪精度与抗风稳定性。",
      },
      {
        title: "抗风鲁棒验证",
        body: "创建强调鲁棒性的有风场景，在 220 次预算内比较优化工具并复验最佳参数组合。",
      },
      {
        title: "智能工具决策",
        body: "使用真实 PX4/Gazebo 调优水平控制参数，由 Harness 根据每轮证据选择算法。",
      },
    ],
  },
} as const;

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
): string {
  if (reason instanceof CloudModelAccessError) {
    return reason.message || copy.requestFailed;
  }
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
  return reason.message || copy.requestFailed;
}

export function ExperimentAssistant() {
  const navigate = useNavigate();
  const { locale } = useI18n();
  const auth = useOptionalAuth();
  const ownerId = auth?.account?.id ?? "local";
  const copy = COPY[locale];
  const {
    settings: modelAccess,
    profiles: modelProfiles,
    activeProfileId,
    selectManagedProvider,
    selectProfile,
  } = useModelAccess();
  const docsPreview = import.meta.env.DEV
    && new URLSearchParams(window.location.search).has("docsPreview");
  const [managedModels, setManagedModels] = useState<ManagedModelCatalogEntry[]>(
    docsPreview
      ? [
          { provider: "openai", display_name: "GPT", model: "gpt-4.1", enabled: true, assistant_enabled: true, job_enabled: true, policy_version: 1 },
          { provider: "deepseek", display_name: "DeepSeek", model: "deepseek-chat", enabled: true, assistant_enabled: true, job_enabled: true, policy_version: 1 },
          { provider: "qwen", display_name: "Qwen", model: "qwen-plus", enabled: true, assistant_enabled: true, job_enabled: true, policy_version: 1 },
        ]
      : [],
  );
  const [managedModelsReady, setManagedModelsReady] = useState(docsPreview);
  const configuredModelProfiles = modelProfiles.filter((profile) =>
    profile.apiKey.trim(),
  );
  const selectedManagedModel = managedModels.find(
    (model) => model.provider === modelAccess.managedProvider,
  );
  const selectedModelProfileId = modelAccess.accessMode === "platform"
    ? selectedManagedModel
      ? `managed:${selectedManagedModel.provider}`
      : "none"
    : configuredModelProfiles.some(
    (profile) => profile.id === activeProfileId,
  )
      ? activeProfileId
      : "none";
  const [draft, setDraft] = useState<AssistantDraft>(loadAssistantDraft);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [composer, setComposer] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiceConsentPending, setVoiceConsentPending] = useState(false);
  const [voiceConsentGranted, setVoiceConsentGranted] = useState(false);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [referenceFiles, setReferenceFiles] = useState<AssistantReferenceFile[]>(
    [],
  );
  const [latest, setLatest] = useState<ExperimentAssistantTurnResponse | null>(
    null,
  );
  const pendingRef = useRef(false);
  const actionMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (modelAccess.accessMode !== "platform") return;
    if (docsPreview) {
      setManagedModelsReady(true);
      return;
    }
    if (!auth?.account) {
      setManagedModels([]);
      setManagedModelsReady(false);
      return;
    }
    let active = true;
    setManagedModelsReady(false);
    void getManagedModelCatalog()
      .then((catalog) => {
        if (!active) return;
        const available = catalog.models.filter((model) =>
          model.enabled && model.assistant_enabled
        );
        setManagedModels(available);
        setManagedModelsReady(true);
      })
      .catch(() => {
        if (!active) return;
        setManagedModels([]);
        setManagedModelsReady(true);
      });
    return () => {
      active = false;
    };
  }, [
    auth?.account,
    docsPreview,
    modelAccess.accessMode,
  ]);

  useEffect(() => {
    if (
      modelAccess.accessMode === "platform"
      && managedModels.length > 0
      && !managedModels.some(
        (model) => model.provider === modelAccess.managedProvider,
      )
    ) {
      selectManagedProvider(managedModels[0].provider);
    }
  }, [
    managedModels,
    modelAccess.accessMode,
    modelAccess.managedProvider,
    selectManagedProvider,
  ]);

  const appendTranscript = useCallback((transcript: string) => {
    setComposer((current) =>
      current.trim() ? `${current.trim()} ${transcript}` : transcript,
    );
  }, []);
  const voice = useVoiceInput({
    locale,
    onTranscript: appendTranscript,
  });
  const messages = draft.conversation.messages;

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
    if (visibleMessage.length > MAX_ASSISTANT_MESSAGE_LENGTH) {
      setError(copy.messageTooLong);
      return;
    }
    if (modelAccess.accessMode === "byok" && !modelAccess.apiKey.trim()) {
      setError(copy.modelRequired);
      openAppSettings();
      return;
    }
    if (
      modelAccess.accessMode === "platform"
      && (!managedModelsReady || !selectedManagedModel)
    ) {
      setError(copy.managedUnavailable);
      return;
    }
    const id = messageId();
    pendingRef.current = true;
    setPending(true);
    setError(null);
    try {
      const platformGrant = modelAccess.accessMode === "platform"
        ? (await issueManagedModelGrant(
            "assistant",
            workspaceId ?? `draft:${ownerId}`,
            modelAccess.managedProvider,
          )).grant
        : null;
      const result = await apiClient.compileExperimentAssistantTurn({
        message_id: id,
        message: visibleMessage,
        locale,
        conversation_summary: draft.conversation.summary,
        current_values: assistantCurrentValues(draft.form),
        explicit_field_ids: explicitAssistantFields(draft.conversation),
        current_parameters: assistantCurrentParameters(draft.selections),
        document_context: requestOnlyDocumentContext(referenceFiles),
        llm: modelAccess.accessMode === "platform"
          ? {
              access_mode: "platform",
              provider: "dronedream",
              platform_grant: platformGrant,
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
      const targetWorkspaceId = workspaceId ?? createExperimentWorkspaceId();
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
      registerExperimentWorkspace({
        id: targetWorkspaceId,
        ownerId,
        name:
          next.form.display_name.trim()
          || result.experiment_summary.trim().slice(0, 255)
          || copy.untitledExperiment,
        source: "assistant",
        activeStep: next.activeStep,
        completedSteps: next.completedSteps,
      });
      if (!workspaceId) {
        setWorkspaceId(targetWorkspaceId);
      }
      setDraft(next);
      setLatest(result);
      setComposer((current) => current === submittedComposer ? "" : current);
      setReferenceFiles((current) => current.filter(
        (file) => !submittedReferenceFileIds.has(file.id),
      ));
      void recordProductEvent("assistant_turn_succeeded", {
        access_mode: modelAccess.accessMode,
        provider: modelAccess.accessMode === "platform"
          ? modelAccess.managedProvider
          : modelAccess.provider,
        has_reference_files: referenceFiles.length > 0,
      });
    } catch (reason) {
      setError(assistantErrorMessage(reason, copy));
      void recordProductEvent("assistant_turn_failed", {
        access_mode: modelAccess.accessMode,
        provider: modelAccess.accessMode === "platform"
          ? modelAccess.managedProvider
          : modelAccess.provider,
      });
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }

  function handleExample(example: string): void {
    setComposer(example);
  }

  const voiceStatus =
    voice.state === "requesting"
      ? copy.requestingVoice
      : voice.state === "listening"
        ? copy.listening
        : voiceMessage(voice.error, copy);
  const voiceConsentCopy = isDesktopRuntime()
    ? copy.voiceConsentDesktop
    : copy.voiceConsentWeb;
  const configuredLabels = latest
    ? acceptedFieldLabels(latest, locale)
    : [];
  const remainingLabels = latest ? reviewLabels(latest, locale) : [];

  return (
    <section className={`experiment-assistant-page ${messages.length ? "has-messages" : ""}`}>
      <div className="experiment-assistant-stage">
        {messages.length === 0 ? (
          <div className="assistant-empty-state">
            <div className="assistant-hero-icon" aria-hidden="true">
              <Cloud strokeWidth={1.65} />
              <span>&gt;_</span>
            </div>
            <h1>{copy.title}</h1>
            <p>{copy.subtitle}</p>
            <div className="assistant-examples">
              {copy.examples.map((example, index) => (
                <button
                  key={example.title}
                  type="button"
                  onClick={() => handleExample(example.body)}
                >
                  <span className="assistant-example-heading">
                    <AssistantTemplateIcon index={index} />
                    <strong>{example.title}</strong>
                  </span>
                  <span className="assistant-example-body">{example.body}</span>
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
                    removeExperimentWorkspace(ownerId, workspaceId);
                    setWorkspaceId(null);
                  } else {
                    clearExperimentDraft();
                  }
                  setLatest(null);
                  setComposer("");
                  setReferenceFiles([]);
                  setActionMenuOpen(false);
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
                <p>{copy.sending}</p>
              </article>
            ) : null}
            {latest ? (
              <div className="assistant-draft-result">
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
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => navigate(
                    workspaceId
                      ? `/jobs/new?experiment=${encodeURIComponent(workspaceId)}`
                      : "/jobs/new",
                  )}
                >
                  {copy.openExperiment}
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
              <div className="assistant-add-popover" role="menu">
                <Link to="/jobs/new" role="menuitem" onClick={() => setActionMenuOpen(false)}>
                  <PencilRuler aria-hidden="true" strokeWidth={1.8} />
                  <span>{copy.manual}</span>
                </Link>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setActionMenuOpen(false);
                    fileInputRef.current?.click();
                  }}
                >
                  <Paperclip aria-hidden="true" strokeWidth={1.8} />
                  <span>{copy.importFiles}</span>
                </button>
              </div>
            ) : null}
          </div>
          <span className="assistant-composer-spacer" />
          <select
            className="assistant-model-button"
            aria-label={copy.model}
            value={selectedModelProfileId}
            disabled={
              pending
              || (modelAccess.accessMode === "platform" && !managedModelsReady)
            }
            onChange={(event) => {
              if (event.target.value.startsWith("managed:")) {
                selectManagedProvider(
                  event.target.value.slice("managed:".length) as
                    | "openai"
                    | "deepseek"
                    | "qwen",
                );
              } else if (event.target.value !== "none") {
                selectProfile(event.target.value);
              }
            }}
          >
            {modelAccess.accessMode === "platform" ? (
              managedModels.length ? (
                managedModels.map((model) => (
                  <option key={model.provider} value={`managed:${model.provider}`}>
                    {model.display_name} · {model.model}
                  </option>
                ))
              ) : (
                <option value="none">{copy.managedUnavailable}</option>
              )
            ) : (
              <>
                <option value="none">{copy.noModel}</option>
                {configuredModelProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {modelProviderLabel(profile.provider)} ·{" "}
                    {profile.model.trim() || "default"}
                  </option>
                ))}
              </>
            )}
          </select>
          <button
            type="button"
            className={`assistant-voice-button ${
              voice.state === "listening" ? "listening" : ""
            }`}
            aria-label={
              voice.state === "listening" ? copy.stopVoice : copy.microphone
            }
            title={
              voice.state === "listening" ? copy.stopVoice : copy.microphone
            }
            onClick={() => {
              if (voice.state === "listening") {
                voice.stop();
                return;
              }
              if (!voice.supported) {
                void voice.start();
                return;
              }
              if (!voiceConsentGranted) {
                setVoiceConsentPending(true);
                return;
              }
              void voice.start();
            }}
          >
            <Mic aria-hidden="true" strokeWidth={1.9} />
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
        {voiceConsentPending ? (
          <div className="assistant-voice-consent" role="note">
            <p>{voiceConsentCopy}</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setVoiceConsentPending(false);
                setVoiceConsentGranted(true);
                void voice.start();
              }}
            >
              {copy.startVoice}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => setVoiceConsentPending(false)}
            >
              {copy.cancelVoice}
            </button>
          </div>
        ) : null}
        {voiceStatus ? (
          <p className="assistant-composer-status">{voiceStatus}</p>
        ) : null}
        {error ? (
          <p className="assistant-composer-error" role="alert">
            {error}
          </p>
        ) : null}
      </form>
    </section>
  );
}
