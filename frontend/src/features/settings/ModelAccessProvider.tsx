import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { ModelAccessContext } from "./ModelAccessContext";
import type {
  ModelAccessContextValue,
  ModelAccessSettings,
  ModelProvider,
} from "./ModelAccessContext";

interface PersistedModelAccessSettings {
  provider: ModelProvider;
  model: string;
  baseUrl: string;
}

const MODEL_ACCESS_STORAGE_KEY = "dronedream:model-access:v1";
const MODEL_ACCESS_SESSION_KEY = "dronedream:model-access-key:v1";

const DEFAULT_MODEL_ACCESS: ModelAccessSettings = {
  provider: "openai",
  apiKey: "",
  model: "",
  baseUrl: "",
};

const PROVIDER_DEFAULTS: Record<
  ModelProvider,
  Pick<ModelAccessSettings, "model" | "baseUrl">
> = {
  openai: { model: "", baseUrl: "" },
  qwen: {
    model: "qwen-plus",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  deepseek: {
    model: "deepseek-v4-flash",
    baseUrl: "https://api.deepseek.com",
  },
  custom: { model: "", baseUrl: "" },
};

function isModelProvider(value: unknown): value is ModelProvider {
  return ["openai", "qwen", "deepseek", "custom"].includes(String(value));
}

function loadModelAccessSettings(): ModelAccessSettings {
  if (typeof window === "undefined") return DEFAULT_MODEL_ACCESS;
  let persisted: PersistedModelAccessSettings | null = null;
  try {
    const raw = window.localStorage.getItem(MODEL_ACCESS_STORAGE_KEY);
    const candidate = raw ? JSON.parse(raw) as Record<string, unknown> : null;
    if (
      candidate
      && isModelProvider(candidate.provider)
      && typeof candidate.model === "string"
      && typeof candidate.baseUrl === "string"
    ) {
      persisted = {
        provider: candidate.provider,
        model: candidate.model,
        baseUrl: candidate.baseUrl,
      };
    }
  } catch {
    persisted = null;
  }
  let apiKey = "";
  try {
    apiKey = window.sessionStorage.getItem(MODEL_ACCESS_SESSION_KEY) ?? "";
  } catch {
    apiKey = "";
  }
  return {
    ...DEFAULT_MODEL_ACCESS,
    ...(persisted ?? {}),
    apiKey,
  };
}

export function ModelAccessProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<ModelAccessSettings>(loadModelAccessSettings);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        MODEL_ACCESS_STORAGE_KEY,
        JSON.stringify({
          provider: settings.provider,
          model: settings.model,
          baseUrl: settings.baseUrl,
        } satisfies PersistedModelAccessSettings),
      );
      if (settings.apiKey) {
        window.sessionStorage.setItem(MODEL_ACCESS_SESSION_KEY, settings.apiKey);
      } else {
        window.sessionStorage.removeItem(MODEL_ACCESS_SESSION_KEY);
      }
    } catch {
      // Storage may be unavailable in hardened browser contexts. The provider
      // still keeps the current settings in memory for this app session.
    }
  }, [settings]);

  const updateSettings = useCallback((values: Partial<ModelAccessSettings>) => {
    setSettings((current) => ({ ...current, ...values }));
  }, []);

  const selectProvider = useCallback((provider: ModelProvider) => {
    setSettings((current) => ({
      ...current,
      provider,
      ...PROVIDER_DEFAULTS[provider],
    }));
  }, []);

  const value = useMemo<ModelAccessContextValue>(() => ({
    settings,
    updateSettings,
    selectProvider,
  }), [selectProvider, settings, updateSettings]);

  return (
    <ModelAccessContext.Provider value={value}>
      {children}
    </ModelAccessContext.Provider>
  );
}
