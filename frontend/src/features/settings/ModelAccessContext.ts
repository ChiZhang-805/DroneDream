import { createContext, useContext } from "react";

export type ModelProvider = "openai" | "qwen" | "deepseek" | "custom";

export interface ModelAccessSettings {
  provider: ModelProvider;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export interface ModelAccessContextValue {
  settings: ModelAccessSettings;
  updateSettings: (values: Partial<ModelAccessSettings>) => void;
  selectProvider: (provider: ModelProvider) => void;
}

export const ModelAccessContext = createContext<ModelAccessContextValue | null>(null);

export function useModelAccess(): ModelAccessContextValue {
  const context = useContext(ModelAccessContext);
  if (!context) {
    throw new Error("useModelAccess must be used inside ModelAccessProvider");
  }
  return context;
}
