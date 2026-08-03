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

interface PersistedModelAccessProfile {
  id: string;
  accessMode: ModelAccessMode;
  managedProvider: ManagedModelProvider;
  provider: ModelProvider;
  model: string;
  baseUrl: string;
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

function modelAccessStorageKey(accountScope: string | null | undefined): string {
  const normalized = accountScope?.trim();
  if (!normalized) return MODEL_ACCESS_STORAGE_KEY;
  return `${MODEL_ACCESS_STORAGE_KEY}:${encodeURIComponent(normalized.slice(0, 160))}`;
}

const DEFAULT_MODEL_ACCESS: ModelAccessSettings = {
  accessMode: "platform",
  managedProvider: "openai",
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

function isManagedModelProvider(value: unknown): value is ManagedModelProvider {
  return ["openai", "qwen", "deepseek"].includes(String(value));
}

function isModelAccessMode(value: unknown): value is ModelAccessMode {
  return value === "platform" || value === "byok";
}

function newProfileId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `model-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function defaultProfile(): ModelAccessProfile {
  return {
    id: DEFAULT_PROFILE_ID,
    ...DEFAULT_MODEL_ACCESS,
  };
}

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
    provider: candidate.provider,
    model: candidate.model,
    baseUrl: candidate.baseUrl,
  };
}

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
          provider: candidate.provider,
          model: candidate.model,
          baseUrl: candidate.baseUrl,
        }],
      };
    }
  } catch {
    persisted = null;
  }
  // API keys deliberately start empty on every provider mount. Keeping a
  // credential in sessionStorage still exposes it to any script executing in
  // the WebView; the packaged credential bridge will replace this in-memory
  // development path.
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
      window.localStorage.setItem(
        storageKey,
        JSON.stringify({
          activeProfileId: state.activeProfileId,
          profiles: state.profiles.map((profile) => ({
            id: profile.id,
            accessMode: profile.accessMode,
            managedProvider: profile.managedProvider,
            provider: profile.provider,
            model: profile.model,
            baseUrl: profile.baseUrl,
          })),
        } satisfies PersistedModelAccessProfiles),
      );
      window.sessionStorage.removeItem(LEGACY_MODEL_ACCESS_SESSION_KEY);
    } catch {
      // Storage may be unavailable in hardened browser contexts. The provider
      // still keeps the current settings in memory for this app session.
    }
  }, [state, storageKey]);

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
              ...(values.baseUrl !== undefined
                && values.baseUrl !== profile.baseUrl
                && values.apiKey === undefined
                ? { apiKey: "" }
                : {}),
            }
          : profile
      ),
    }));
  }, []);

  const selectProvider = useCallback((provider: ModelProvider) => {
    setState((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.id === current.activeProfileId
          ? {
              ...profile,
              provider,
              // Credentials belong to a provider/endpoint pair. Never carry a
              // key across providers where it could be sent to the wrong host.
              apiKey: profile.provider === provider ? profile.apiKey : "",
              ...PROVIDER_DEFAULTS[provider],
            }
          : profile
      ),
    }));
  }, []);

  const selectManagedProvider = useCallback((managedProvider: ManagedModelProvider) => {
    setState((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.id === current.activeProfileId
          ? { ...profile, managedProvider }
          : profile
      ),
    }));
  }, []);

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

  const selectProfile = useCallback((profileId: string) => {
    setState((current) =>
      current.profiles.some((profile) => profile.id === profileId)
        ? { ...current, activeProfileId: profileId }
        : current
    );
  }, []);

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
            provider: "custom",
            apiKey: "",
            ...PROVIDER_DEFAULTS.custom,
          },
        ],
      };
    });
  }, []);

  const removeActiveProfile = useCallback(() => {
    setState((current) => {
      if (current.profiles.length <= 1) return current;
      const profiles = current.profiles.filter(
        (profile) => profile.id !== current.activeProfileId,
      );
      return {
        storageKey: current.storageKey,
        activeProfileId: profiles[0].id,
        profiles,
      };
    });
  }, []);

  const value = useMemo<ModelAccessContextValue>(() => ({
    settings,
    profiles: state.profiles,
    activeProfileId: state.activeProfileId,
    updateSettings,
    selectAccessMode,
    selectManagedProvider,
    selectProvider,
    selectProfile,
    addProfile,
    removeActiveProfile,
  }), [
    addProfile,
    removeActiveProfile,
    selectProfile,
    selectManagedProvider,
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
