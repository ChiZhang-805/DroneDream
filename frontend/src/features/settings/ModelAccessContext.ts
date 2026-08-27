import { createContext, useContext } from "react";

import {
  type ManagedModelProvider,
  type ModelApiProtocol,
  type ModelProvider,
} from "./modelProviderCatalog";

export { modelProviderLabel } from "./modelProviderCatalog";
export type {
  ManagedModelProvider,
  ModelApiProtocol,
  ModelProvider,
} from "./modelProviderCatalog";
export type ModelAccessMode = "platform" | "byok";
export interface ModelAccessSettings {
  accessMode: ModelAccessMode;
  managedProvider: ManagedModelProvider;
  managedModel: string;
  provider: ModelProvider;
  apiKey: string;
  model: string;
  displayName: string;
  baseUrl: string;
  protocol: ModelApiProtocol;
  /** Opaque identifier only; the credential itself remains in AGENT Core's OS vault. */
  agentCoreProfileId: string | null;
  /** Stable model selector returned by AGENT Core, for example custom:cmp-... */
  agentCoreSelectionId: string | null;
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
  removeProfile: (profileId: string) => void;
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
