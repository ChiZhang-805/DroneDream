import { createContext, useContext } from "react";

export type ModelProvider = "openai" | "qwen" | "deepseek" | "kimi" | "custom";
export type ManagedModelProvider = Exclude<ModelProvider, "custom">;
export type ModelAccessMode = "platform" | "byok";

export function modelProviderLabel(provider: ModelProvider): string {
  return {
    openai: "OpenAI",
    qwen: "Qwen",
    deepseek: "DeepSeek",
    kimi: "Kimi",
    custom: "Custom",
  }[provider];
}

export interface ModelAccessSettings {
  accessMode: ModelAccessMode;
  managedProvider: ManagedModelProvider;
  managedModel: string;
  provider: ModelProvider;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export interface ModelAccessProfile extends ModelAccessSettings {
  id: string;
}

export interface ModelAccessContextValue {
  settings: ModelAccessSettings;
  profiles: ModelAccessProfile[];
  activeProfileId: string;
  updateSettings: (values: Partial<ModelAccessSettings>) => void;
  selectAccessMode: (mode: ModelAccessMode) => void;
  selectManagedProvider: (provider: ManagedModelProvider) => void;
  selectManagedModel: (provider: ManagedModelProvider, model: string) => void;
  selectProvider: (provider: ModelProvider) => void;
  selectProfile: (profileId: string) => void;
  addProfile: () => void;
  removeActiveProfile: () => void;
}

export const ModelAccessContext = createContext<ModelAccessContextValue | null>(null);

export function useModelAccess(): ModelAccessContextValue {
  const context = useContext(ModelAccessContext);
  if (!context) {
    throw new Error("useModelAccess must be used inside ModelAccessProvider");
  }
  return context;
}
