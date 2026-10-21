import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { ModelAccessContext } from "./ModelAccessContext";
import type {
  ModelAccessContextValue,
  ModelAccessMode,
  ModelAccessProfile,
  ModelAccessSettings,
  ManagedModelProvider,
  ModelProvider,
} from "./ModelAccessContext";
import {
  isManagedModelProvider,
  isModelProvider,
  modelProviderDefaults,
  type ModelApiProtocol,
} from "./modelProviderCatalog";

interface PersistedModelAccessProfile {
  id: string;
  accessMode: ModelAccessMode;
  managedProvider: ManagedModelProvider;
  managedModel: string;
  provider: ModelProvider;
  model: string;
  displayName: string;
  baseUrl: string;
  protocol: ModelApiProtocol;
  agentCoreProfileId: string | null;
  agentCoreSelectionId: string | null;
}
interface PersistedModelAccessProfiles {
  activeProfileId: string;
  profiles: PersistedModelAccessProfile[];
}

interface ModelAccessState {
  storageKey: string;
  activeProfileId: string;
  profiles: ModelAccessProfile[];
}

const MODEL_ACCESS_STORAGE_KEY = "dronedream:model-access:v1";
const LEGACY_MODEL_ACCESS_SESSION_KEY = "dronedream:model-access-key:v1";
const DEFAULT_PROFILE_ID = "default";

/** Partition non-secret selectors by account; anonymous settings are not an account fallback. */
function modelAccessStorageKey(accountScope: string | null | undefined): string {
  const normalized = accountScope?.trim();
  if (!normalized) return MODEL_ACCESS_STORAGE_KEY;
  return `${MODEL_ACCESS_STORAGE_KEY}:${encodeURIComponent(normalized.slice(0, 160))}`;
}

const DEFAULT_MODEL_ACCESS: ModelAccessSettings = {
  accessMode: "platform",
  managedProvider: "openai",
  managedModel: "gpt-4.1",
  provider: "openai",
  apiKey: "",
  model: "",
  displayName: "",
  baseUrl: "",
  protocol: "openai-responses",
  agentCoreProfileId: null,
  agentCoreSelectionId: null,
};

function isModelApiProtocol(value: unknown): value is ModelApiProtocol {
  return typeof value === "string" && [
    "openai-responses",
    "openai-chat",
    "anthropic-messages",
    "google-generate-content",
    "aws-bedrock-converse",
    "ollama-chat",
    "custom-http",
  ].includes(value);
}

function isModelAccessMode(value: unknown): value is ModelAccessMode {
  return value === "platform" || value === "byok";
}

/** UI identity only; this is neither a credential nor an authorization token. */
function newProfileId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `model-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Empty editable selection; choosing a model does not certify its runtime availability. */
function defaultProfile(): ModelAccessProfile {
  return {
    id: DEFAULT_PROFILE_ID,
    ...DEFAULT_MODEL_ACCESS,
  };
}

/** Recover bounded metadata from untrusted browser storage, never a saved API key. */
function parsePersistedProfile(value: unknown): PersistedModelAccessProfile | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.id !== "string"
    || !candidate.id
    || candidate.id.length > 128
    || !isModelProvider(candidate.provider)
    || typeof candidate.model !== "string"
    || candidate.model.length > 128
    || (candidate.displayName !== undefined
      && (typeof candidate.displayName !== "string" || candidate.displayName.length > 128))
    || typeof candidate.baseUrl !== "string"
    || candidate.baseUrl.length > 2_048
  ) {
    return null;
  }
  return {
    id: candidate.id,
    accessMode: isModelAccessMode(candidate.accessMode)
      ? candidate.accessMode
      : "platform",
    managedProvider: isManagedModelProvider(candidate.managedProvider)
      ? candidate.managedProvider
      : "openai",
    managedModel: typeof candidate.managedModel === "string"
        && candidate.managedModel.length > 0
        && candidate.managedModel.length <= 128
      ? candidate.managedModel
      : "gpt-4.1",
    provider: candidate.provider,
    model: candidate.model,
    displayName: typeof candidate.displayName === "string" ? candidate.displayName : "",
    baseUrl: candidate.baseUrl,
    protocol: isModelApiProtocol(candidate.protocol)
      ? candidate.protocol
      : modelProviderDefaults(candidate.provider).protocol,
    agentCoreProfileId: typeof candidate.agentCoreProfileId === "string"
        && /^cmp-[a-f0-9]{24}$/u.test(candidate.agentCoreProfileId)
      ? candidate.agentCoreProfileId
      : null,
    agentCoreSelectionId: typeof candidate.agentCoreSelectionId === "string"
        && /^custom:cmp-[a-f0-9]{24}$/u.test(candidate.agentCoreSelectionId)
      ? candidate.agentCoreSelectionId
      : null,
  };
}

/** Rehydrate account metadata and purge the retired session-key path without reading its key. */
function loadModelAccessState(
  accountScope?: string | null,
): ModelAccessState {
  const storageKey = modelAccessStorageKey(accountScope);
  if (typeof window === "undefined") {
    return {
      storageKey,
      activeProfileId: DEFAULT_PROFILE_ID,
      profiles: [defaultProfile()],
    };
  }
  let persisted: PersistedModelAccessProfiles | null = null;
  try {
    const raw = window.localStorage.getItem(storageKey);
    const candidate = raw ? JSON.parse(raw) as Record<string, unknown> : null;
    if (
      candidate
      && typeof candidate.activeProfileId === "string"
      && Array.isArray(candidate.profiles)
    ) {
      const parsedProfiles = candidate.profiles
        .map(parsePersistedProfile)
        .filter((profile): profile is PersistedModelAccessProfile => profile !== null)
        .slice(0, 12);
      const seenProfileIds = new Set<string>();
      const profiles = parsedProfiles.filter((profile) => {
        if (seenProfileIds.has(profile.id)) return false;
        seenProfileIds.add(profile.id);
        return true;
      });
      if (
        profiles.length > 0
        && profiles.some((profile) => profile.id === candidate.activeProfileId)
      ) {
        persisted = {
          activeProfileId: candidate.activeProfileId,
          profiles,
        };
      }
    } else if (
      candidate
      && isModelProvider(candidate.provider)
      && typeof candidate.model === "string"
      && typeof candidate.baseUrl === "string"
    ) {
      // Migrate the pre-profile metadata shape without ever importing a key.
      persisted = {
        activeProfileId: DEFAULT_PROFILE_ID,
        profiles: [{
          id: DEFAULT_PROFILE_ID,
          accessMode: "platform",
          managedProvider: "openai",
          managedModel: "gpt-4.1",
          provider: candidate.provider,
          model: candidate.model,
          displayName: "",
            baseUrl: candidate.baseUrl,
            protocol: modelProviderDefaults(candidate.provider).protocol,
            agentCoreProfileId: null,
            agentCoreSelectionId: null,
        }],
      };
    }
  } catch {
    persisted = null;
  }
  // API keys deliberately start empty on every provider mount. Saved credentials
  // are resolved by the Agent Core vault using opaque IDs, not browser storage.
  try {
    window.sessionStorage.removeItem(LEGACY_MODEL_ACCESS_SESSION_KEY);
  } catch {
    // Best-effort cleanup of credentials written by pre-1.0.0 builds.
  }
  const profiles = persisted?.profiles.map((profile) => ({
    ...profile,
    apiKey: "",
  })) ?? [defaultProfile()];
  return {
    storageKey,
    activeProfileId: persisted?.activeProfileId ?? DEFAULT_PROFILE_ID,
    profiles,
  };
}

interface ModelAccessProviderProps {
  children: ReactNode;
  initialSettings?: Partial<ModelAccessSettings>;
  accountScope?: string | null;
}

/** Own editable model metadata; CustomModelSettingsPanel performs explicit vault saves. */
export function ModelAccessProvider({
  children,
  initialSettings,
  accountScope,
}: ModelAccessProviderProps) {
  const storageKey = modelAccessStorageKey(accountScope);
  const previousStorageKey = useRef(storageKey);
  const [state, setState] = useState<ModelAccessState>(() => {
    const loaded = loadModelAccessState(accountScope);
    if (!initialSettings) return loaded;
    const normalizedInitialSettings = (
      initialSettings.apiKey
      && initialSettings.accessMode === undefined
    )
      ? { ...initialSettings, accessMode: "byok" as const }
      : initialSettings;
    return {
      ...loaded,
      profiles: loaded.profiles.map((profile) =>
        profile.id === loaded.activeProfileId
          ? { ...profile, ...normalizedInitialSettings }
          : profile
      ),
    };
  });

  useEffect(() => {
    if (storageKey === previousStorageKey.current) return;
    previousStorageKey.current = storageKey;
    // Provider/model/endpoint metadata belongs to the signed-in account just
    // as much as its in-memory key does. Loading the next account's scoped
    // profile avoids sending a newly entered credential to an endpoint left
    // behind by a different user on the same Windows installation.
    setState(loadModelAccessState(accountScope));
  }, [accountScope, storageKey]);

  const settings = state.profiles.find(
    (profile) => profile.id === state.activeProfileId,
  ) ?? state.profiles[0] ?? defaultProfile();

  useEffect(() => {
    if (state.storageKey !== storageKey) return;
    try {
      // Explicit projection is intentional: spreading a profile here would persist apiKey.
      window.localStorage.setItem(
        storageKey,
        JSON.stringify({
          activeProfileId: state.activeProfileId,
          profiles: state.profiles.map((profile) => ({
            id: profile.id,
            accessMode: profile.accessMode,
            managedProvider: profile.managedProvider,
            managedModel: profile.managedModel,
            provider: profile.provider,
            model: profile.model,
            displayName: profile.displayName,
            baseUrl: profile.baseUrl,
            protocol: profile.protocol,
            agentCoreProfileId: profile.agentCoreProfileId,
            agentCoreSelectionId: profile.agentCoreSelectionId,
          })),
        } satisfies PersistedModelAccessProfiles),
      );
      window.sessionStorage.removeItem(LEGACY_MODEL_ACCESS_SESSION_KEY);
    } catch {
      // Storage may be unavailable in hardened browser contexts. The provider
      // still keeps the current settings in memory for this app session.
    }
  }, [state, storageKey]);

  /** Update a draft atomically; identity changes invalidate its saved-vault binding. */
  const updateSettings = useCallback((values: Partial<ModelAccessSettings>) => {
    setState((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.id === current.activeProfileId
          ? {
              ...profile,
              ...values,
              // A BYOK credential is scoped to the endpoint where the user
              // entered it. Editing that endpoint must not silently carry the
              // old credential to a different host. A caller that deliberately
              // replaces both values in one atomic update may provide apiKey.
              ...(((values.baseUrl !== undefined && values.baseUrl !== profile.baseUrl)
                  || (values.provider !== undefined && values.provider !== profile.provider))
                && values.apiKey === undefined
                ? { apiKey: "" }
                : {}),
              ...((values.provider !== undefined && values.provider !== profile.provider)
                || (values.baseUrl !== undefined && values.baseUrl !== profile.baseUrl)
                || (values.model !== undefined && values.model !== profile.model)
                || (values.protocol !== undefined && values.protocol !== profile.protocol)
                ? {
                    ...(values.agentCoreProfileId === undefined ? { agentCoreProfileId: null } : {}),
                    ...(values.agentCoreSelectionId === undefined ? { agentCoreSelectionId: null } : {}),
                  }
                : {}),
            }
          : profile
      ),
    }));
  }, []);

  /** Switch provider defaults only on a real change, never reset a same-provider endpoint. */
  const selectProvider = useCallback((provider: ModelProvider) => {
    setState((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.id === current.activeProfileId && profile.provider !== provider
          ? {
              ...profile,
              provider,
              // Credentials belong to a provider/endpoint pair. Never carry a
              // key across providers where it could be sent to the wrong host.
              apiKey: "",
              agentCoreProfileId: null,
              agentCoreSelectionId: null,
              ...modelProviderDefaults(provider),
            }
          : profile
      ),
    }));
  }, []);

  /** Choose a platform selector; cloud entitlement and model availability remain server-owned. */
  const selectManagedProvider = useCallback((managedProvider: ManagedModelProvider) => {
    setState((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.id === current.activeProfileId
          ? {
              ...profile,
              managedProvider,
              managedModel: {
                openai: "gpt-4.1",
                deepseek: "deepseek-v4-flash",
                qwen: "qwen-plus",
                kimi: "kimi-k2.6",
              }[managedProvider],
            }
          : profile
      ),
    }));
  }, []);

  /** Preserve the exact catalog model ID instead of silently substituting another provider. */
  const selectManagedModel = useCallback((
    managedProvider: ManagedModelProvider,
    managedModel: string,
  ) => {
    if (!managedModel.trim() || managedModel.length > 128) return;
    setState((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.id === current.activeProfileId
          ? { ...profile, managedProvider, managedModel }
          : profile
      ),
    }));
  }, []);

  /** Switching billing/access mode does not migrate a BYOK credential to the platform. */
  const selectAccessMode = useCallback((accessMode: ModelAccessMode) => {
    setState((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.id === current.activeProfileId
          ? { ...profile, accessMode }
          : profile
      ),
    }));
  }, []);

  /** Select an existing local draft; a missing ID cannot create a phantom profile. */
  const selectProfile = useCallback((profileId: string) => {
    setState((current) =>
      current.profiles.some((profile) => profile.id === profileId)
        ? { ...current, activeProfileId: profileId }
        : current
    );
  }, []);

  /** Create one empty draft within the UI cap, without duplicating another profile's key. */
  const addProfile = useCallback(() => {
    setState((current) => {
      if (current.profiles.length >= 12) return current;
      const id = newProfileId();
      return {
        storageKey: current.storageKey,
        activeProfileId: id,
        profiles: [
          ...current.profiles,
          {
            id,
            accessMode: "byok",
            managedProvider: "openai",
            managedModel: "gpt-4.1",
            provider: "custom",
            apiKey: "",
            agentCoreProfileId: null,
            agentCoreSelectionId: null,
            ...modelProviderDefaults("custom"),
          },
        ],
      };
    });
  }, []);

  /** Remove local metadata only; the settings panel separately requests vault deletion. */
  const removeProfile = useCallback((profileId: string) => {
    setState((current) => {
      if (current.profiles.length === 1) {
        if (current.profiles[0]?.id !== profileId) return current;
        return {
          storageKey: current.storageKey,
          activeProfileId: DEFAULT_PROFILE_ID,
          profiles: [{
            ...defaultProfile(),
            accessMode: "byok",
          }],
        };
      }
      const profiles = current.profiles.filter(
        (profile) => profile.id !== profileId,
      );
      if (profiles.length === current.profiles.length) return current;
      return {
        storageKey: current.storageKey,
        activeProfileId: current.activeProfileId === profileId
          ? profiles[0].id
          : current.activeProfileId,
        profiles,
      };
    });
  }, []);

  const removeActiveProfile = useCallback(() => {
    removeProfile(state.activeProfileId);
  }, [removeProfile, state.activeProfileId]);

  const value = useMemo<ModelAccessContextValue>(() => ({
    settings,
    profiles: state.profiles,
    activeProfileId: state.activeProfileId,
    updateSettings,
    selectAccessMode,
    selectManagedProvider,
    selectManagedModel,
    selectProvider,
    selectProfile,
    addProfile,
    removeProfile,
    removeActiveProfile,
  }), [
    addProfile,
    removeProfile,
    removeActiveProfile,
    selectProfile,
    selectManagedProvider,
    selectManagedModel,
    selectProvider,
    selectAccessMode,
    settings,
    state.activeProfileId,
    state.profiles,
    updateSettings,
  ]);

  return (
    <ModelAccessContext.Provider value={value}>
      {children}
    </ModelAccessContext.Provider>
  );
}
