import { Eye, EyeOff, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { ModelProviderLogo } from "./AssistantModelPicker";
import {
  createAgentCoreCustomModel,
  deleteAgentCoreCustomModel,
  testAgentCoreCustomModel,
} from "../features/autonomy/agentCore";
import {
  useModelAccess,
  type ModelAccessProfile,
} from "../features/settings/ModelAccessContext";
import {
  detectModelProvider,
  MODEL_API_PROTOCOL_LABELS,
  MODEL_PROVIDER_CATALOG,
  modelProviderDefinition,
  modelProviderDefaults,
  type ModelApiProtocol,
  type ModelProvider,
} from "../features/settings/modelProviderCatalog";

import "./CustomModelSettingsPanel.css";

interface CustomModelSettingsPanelProps {
  locale: "en" | "zh-CN";
  edition?: BrandEditionId;
}

interface ModelProfileDraft {
  provider: ModelProvider;
  apiKey: string;
  model: string;
  displayName: string;
  baseUrl: string;
  protocol: ModelApiProtocol;
}

function draftFromProfile(profile: ModelAccessProfile): ModelProfileDraft {
  return {
    provider: profile.provider,
    apiKey: profile.apiKey,
    model: profile.model,
    displayName: profile.displayName,
    baseUrl: profile.baseUrl,
    protocol: profile.protocol,
  };
}

function endpointIsValid(provider: ModelProvider, value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  try {
    const url = new URL(trimmed);
    if (url.protocol === "https:") return true;
    return provider === "ollama"
      && url.protocol === "http:"
      && ["localhost", "127.0.0.1", "::1", "[::1]"].includes(url.hostname);
  } catch {
    return false;
  }
}

export function CustomModelSettingsPanel({ locale, edition }: CustomModelSettingsPanelProps) {
  const chinese = locale === "zh-CN";
  const usesAgentCoreVault = edition === "autonomy";
  const {
    settings,
    profiles,
    activeProfileId,
    updateSettings,
    selectProfile,
    addProfile,
    removeProfile,
  } = useModelAccess();
  const [draft, setDraft] = useState<ModelProfileDraft>(() => draftFromProfile({
    id: activeProfileId,
    ...settings,
  }));
  const [showApiKey, setShowApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const skipNextSettingsSyncRef = useRef(false);

  useEffect(() => {
    if (skipNextSettingsSyncRef.current) {
      skipNextSettingsSyncRef.current = false;
      return;
    }
    setDraft(draftFromProfile({ id: activeProfileId, ...settings }));
    setShowApiKey(false);
    setMessage(null);
  }, [activeProfileId, settings]);

  const provider = useMemo(() => modelProviderDefinition(draft.provider), [draft.provider]);
  const profileLabel = (profile: ModelAccessProfile) => (
    profile.displayName.trim()
    || profile.model.trim()
    || modelProviderDefinition(profile.provider).label
  );

  const chooseProvider = (nextProvider: ModelProvider) => {
    const defaults = modelProviderDefaults(nextProvider);
    setDraft((current) => ({
      ...current,
      provider: nextProvider,
      apiKey: current.provider === nextProvider ? current.apiKey : "",
      model: defaults.model,
      displayName: "",
      baseUrl: defaults.baseUrl,
      protocol: defaults.protocol,
    }));
    setMessage(null);
  };

  const detect = () => {
    const result = detectModelProvider(draft);
    const definition = modelProviderDefinition(result.provider);
    const defaults = modelProviderDefaults(result.provider);
    setDraft((current) => ({
      ...current,
      provider: result.provider,
      baseUrl: current.baseUrl.trim() || defaults.baseUrl,
      model: current.model.trim() || defaults.model,
      protocol: result.provider === "custom" ? current.protocol : defaults.protocol,
      displayName: current.displayName.trim() || current.model.trim() || definition.label,
    }));
    if (result.provider === "custom") {
      setMessage({
        kind: "error",
        text: chinese
          ? "暂未识别出供应商，请选择“自定义”并检查接口协议。"
          : "Provider not recognized. Keep Custom selected and verify the API protocol.",
      });
      return;
    }
    const confidence = {
      high: chinese ? "高置信度" : "high confidence",
      medium: chinese ? "中等置信度" : "medium confidence",
      low: chinese ? "低置信度" : "low confidence",
    }[result.confidence];
    setMessage({
      kind: "success",
      text: chinese
        ? `已在本机识别为 ${definition.label}（${confidence}），未发送 API Key。`
        : `Detected ${definition.label} locally (${confidence}); the API key was not transmitted.`,
    });
  };

  const save = async () => {
    if (!draft.model.trim()) {
      setMessage({
        kind: "error",
        text: chinese ? "请填写模型 ID。" : "Enter a model ID.",
      });
      return;
    }
    if (!endpointIsValid(draft.provider, draft.baseUrl)) {
      setMessage({
        kind: "error",
        text: chinese
          ? "请填写有效的 HTTPS API 地址；本机 Ollama 可以使用 localhost HTTP。"
          : "Enter a valid HTTPS API URL; local Ollama may use localhost HTTP.",
      });
      return;
    }
    const existingCoreBinding = usesAgentCoreVault
      && Boolean(settings.agentCoreProfileId && settings.agentCoreSelectionId);
    const coreConnectionUnchanged = existingCoreBinding
      && draft.provider === settings.provider
      && draft.model.trim() === settings.model
      && draft.baseUrl.trim() === settings.baseUrl
      && draft.protocol === settings.protocol;
    if (draft.provider !== "ollama" && !draft.apiKey.trim() && !coreConnectionUnchanged) {
      setMessage({
        kind: "error",
        text: chinese ? "请填写 API Key。" : "Enter an API key.",
      });
      return;
    }
    const normalized = {
      ...draft,
      model: draft.model.trim(),
      displayName: draft.displayName.trim() || draft.model.trim(),
      baseUrl: draft.baseUrl.trim(),
    };
    if (usesAgentCoreVault && coreConnectionUnchanged && !draft.apiKey.trim()) {
      skipNextSettingsSyncRef.current = true;
      updateSettings({ ...normalized, apiKey: "", accessMode: "byok" });
      setMessage({
        kind: "success",
        text: chinese ? "模型配置已保存在本机安全凭证库中。" : "Model profile is stored in the local secure credential vault.",
      });
      return;
    }
    setSaving(true);
    try {
      if (usesAgentCoreVault) {
        if (draft.protocol !== "openai-responses" && draft.protocol !== "openai-chat") {
          throw new Error(chinese
            ? "AGENT Core 当前支持 Responses 与 OpenAI 兼容 Chat 接口。"
            : "AGENT Core currently supports Responses and OpenAI-compatible Chat APIs.");
        }
        const oldProfileId = settings.agentCoreProfileId;
        const created = await createAgentCoreCustomModel({
          display_name: normalized.displayName,
          base_url: normalized.baseUrl,
          model_id: normalized.model,
          api_key: normalized.apiKey.trim() || "ollama-local",
          api_style: draft.protocol === "openai-responses" ? "responses" : "chat-completions",
          provider: draft.provider === "custom" ? undefined : draft.provider,
        });
        let tested = false;
        try {
          tested = (await testAgentCoreCustomModel(created.profile_id)).ok;
        } catch {
          // Some compatible providers do not expose /models. The profile is
          // still usable and inference will remain fail-closed at mission time.
        }
        skipNextSettingsSyncRef.current = true;
        updateSettings({
          ...normalized,
          apiKey: "",
          accessMode: "byok",
          agentCoreProfileId: created.profile_id,
          agentCoreSelectionId: created.selection_id,
        });
        setDraft((current) => ({ ...current, apiKey: "" }));
        if (oldProfileId && oldProfileId !== created.profile_id) {
          try {
            await deleteAgentCoreCustomModel(oldProfileId);
          } catch {
            // The new credential is already active. An orphan cleanup can be
            // retried without weakening the current profile.
          }
        }
        setMessage({
          kind: "success",
          text: chinese
            ? `模型配置已加密保存到 Windows 当前用户凭证库${tested ? "，连接验证通过" : ""}。`
            : `Model profile encrypted in the current Windows user's credential vault${tested ? "; connection verified" : ""}.`,
        });
        return;
      }
      skipNextSettingsSyncRef.current = true;
      updateSettings({
        ...normalized,
        apiKey: normalized.apiKey.trim(),
        accessMode: "byok",
        agentCoreProfileId: null,
        agentCoreSelectionId: null,
      });
      setMessage({
        kind: "success",
        text: chinese
          ? "模型配置已保存；API Key 仅保留在当前软件会话的内存中。"
          : "Model configuration saved. The API key remains only in memory for this app session.",
      });
    } catch (reason) {
      setMessage({
        kind: "error",
        text: reason instanceof Error
          ? reason.message
          : (chinese ? "模型配置保存失败。" : "Unable to save the model profile."),
      });
    } finally {
      setSaving(false);
    }
  };

  const removeProfileEntry = async (profile: ModelAccessProfile) => {
    if (profile?.agentCoreProfileId) {
      setSaving(true);
      try {
        await deleteAgentCoreCustomModel(profile.agentCoreProfileId);
      } catch (reason) {
        setMessage({
          kind: "error",
          text: reason instanceof Error
            ? reason.message
            : (chinese ? "无法从安全凭证库删除模型。" : "Unable to remove the model from the secure vault."),
        });
        setSaving(false);
        return;
      }
      setSaving(false);
    }
    removeProfile(profile.id);
  };

  const removeSelectedProfile = async () => {
    const profile = profiles.find((item) => item.id === activeProfileId);
    if (profile) await removeProfileEntry(profile);
  };

  return (
    <div className="custom-model-settings">
      <div className="custom-model-profile-toolbar">
        <label htmlFor="settings_model_profile">
          <span>{chinese ? "模型配置" : "Model profile"}</span>
          <select
            id="settings_model_profile"
            value={activeProfileId}
            onChange={(event) => selectProfile(event.target.value)}
          >
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {modelProviderDefinition(profile.provider).label} · {profileLabel(profile)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn custom-model-icon-button"
          onClick={addProfile}
          disabled={profiles.length >= 12}
          aria-label={chinese ? "添加模型配置" : "Add model profile"}
          title={chinese ? "添加模型配置" : "Add model profile"}
        >
          <Plus aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn custom-model-icon-button"
          onClick={() => void removeSelectedProfile()}
          disabled={profiles.length <= 1 || saving}
          aria-label={chinese ? "删除模型配置" : "Remove model profile"}
          title={chinese ? "删除模型配置" : "Remove model profile"}
        >
          <Trash2 aria-hidden="true" />
        </button>
      </div>

      <div
        className="custom-model-profile-list"
        aria-label={chinese ? "已添加的模型" : "Added models"}
      >
        {profiles.map((profile) => (
          <div
            key={profile.id}
            className={profile.id === activeProfileId ? "is-active" : undefined}
          >
            <button
              type="button"
              className="custom-model-profile-select"
              aria-pressed={profile.id === activeProfileId}
              onClick={() => selectProfile(profile.id)}
            >
              <ModelProviderLogo provider={profile.provider} />
              <span>
                <strong>{profileLabel(profile)}</strong>
                <small>{modelProviderDefinition(profile.provider).label} · {profile.model || (chinese ? "未配置" : "Not configured")}</small>
              </span>
            </button>
            <button
              type="button"
              className="custom-model-profile-delete"
              disabled={profiles.length <= 1 || saving}
              aria-label={chinese ? `删除 ${profileLabel(profile)}` : `Delete ${profileLabel(profile)}`}
              title={chinese ? "删除模型配置" : "Delete model profile"}
              onClick={() => void removeProfileEntry(profile)}
            >
              <Trash2 aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>

      <div className="custom-model-endpoint-row">
        <label htmlFor="settings_model_base_url">
          <span>{chinese ? "API 地址" : "API URL"}</span>
          <input
            id="settings_model_base_url"
            type="url"
            value={draft.baseUrl}
            maxLength={2_048}
            onChange={(event) => setDraft((current) => ({ ...current, baseUrl: event.target.value }))}
            placeholder="https://…/v1"
          />
        </label>
        <label htmlFor="settings_model_api_key">
          <span>API Key</span>
          <span className="custom-model-secret-input">
            <input
              id="settings_model_api_key"
              type={showApiKey ? "text" : "password"}
              autoComplete="off"
              value={draft.apiKey}
              maxLength={512}
              onChange={(event) => setDraft((current) => ({ ...current, apiKey: event.target.value }))}
               placeholder={usesAgentCoreVault
                 ? (settings.agentCoreProfileId
                   ? (chinese ? "已安全保存；留空可继续使用" : "Stored securely; leave blank to keep using it")
                   : (chinese ? "保存到 Windows 当前用户凭证库" : "Saved to the current Windows user's vault"))
                 : (chinese ? "仅保留在当前会话内存中" : "Kept only in memory for this session")}
            />
            <button
              type="button"
              onClick={() => setShowApiKey((visible) => !visible)}
              aria-label={showApiKey
                ? (chinese ? "隐藏 API Key" : "Hide API key")
                : (chinese ? "显示 API Key" : "Show API key")}
              title={showApiKey
                ? (chinese ? "隐藏 API Key" : "Hide API key")
                : (chinese ? "显示 API Key" : "Show API key")}
            >
              {showApiKey ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
            </button>
          </span>
        </label>
      </div>

      <div className="custom-model-identity-row">
        <label htmlFor="settings_model_provider">
          <span>{chinese ? "供应商" : "Provider"}</span>
          <span className="custom-model-provider-select">
            <ModelProviderLogo provider={draft.provider} />
            <select
              id="settings_model_provider"
              aria-label={chinese ? "供应商" : "Provider"}
              value={draft.provider}
              onChange={(event) => chooseProvider(event.target.value as ModelProvider)}
            >
              {MODEL_PROVIDER_CATALOG.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
          </span>
        </label>
        <label htmlFor="settings_model_name">
          <span>{chinese ? "模型 ID" : "Model ID"}</span>
          <input
            id="settings_model_name"
            value={draft.model}
            maxLength={128}
            onChange={(event) => setDraft((current) => ({ ...current, model: event.target.value }))}
            placeholder={provider.defaultModel || (chinese ? "必填" : "Required")}
          />
        </label>
        <label htmlFor="settings_model_display_name">
          <span>{chinese ? "显示名称" : "Display name"}</span>
          <input
            id="settings_model_display_name"
            value={draft.displayName}
            maxLength={128}
            onChange={(event) => setDraft((current) => ({ ...current, displayName: event.target.value }))}
            placeholder={chinese ? "可选" : "Optional"}
          />
        </label>
        <label htmlFor="settings_model_protocol">
          <span>{chinese ? "接口协议" : "API protocol"}</span>
          <select
            id="settings_model_protocol"
            value={draft.protocol}
            onChange={(event) => setDraft((current) => ({
              ...current,
              protocol: event.target.value as ModelApiProtocol,
            }))}
          >
            {provider.protocols.map((protocol) => (
              <option key={protocol} value={protocol}>{MODEL_API_PROTOCOL_LABELS[protocol]}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="custom-model-actions">
        {message ? (
          <p className={`custom-model-message custom-model-message-${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
            {message.text}
          </p>
        ) : <span aria-hidden="true" />}
        <button type="button" className="btn" onClick={detect}>
          <Search aria-hidden="true" />
          {chinese ? "识别供应商与模型" : "Detect provider and model"}
        </button>
         <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>
           {saving ? (chinese ? "正在保存" : "Saving") : (chinese ? "保存" : "Save")}
        </button>
      </div>
      <p className="custom-model-security-note">
        {chinese
          ? usesAgentCoreVault
            ? "识别过程仅在本机完成。API Key 由 AGENT Core 加密保存到 Windows 当前用户凭证库，不写入浏览器存储、任务草稿或日志。"
            : "识别过程仅在本机完成。API Key 不写入本地存储、任务草稿或日志。"
          : usesAgentCoreVault
            ? "Detection runs locally. AGENT Core encrypts the API key in the current Windows user's credential vault; it is never written to browser storage, task drafts, or logs."
            : "Detection runs locally. The API key is never written to local storage, task drafts, or logs."}
      </p>
    </div>
  );
}
