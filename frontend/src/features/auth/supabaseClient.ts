import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { isDesktopRuntime } from "../../desktop/bridge";

const supabaseUrl = (
  import.meta.env.VITE_SUPABASE_URL as string | undefined
)?.trim();
const supabasePublishableKey = (
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
)?.trim();
const desktopRuntime = isDesktopRuntime();

export function editionAuthStorageKey(editionId: string | undefined): string | null {
  const normalized = editionId?.trim().toLowerCase();
  if (!normalized || !["universal", "sim", "lab", "field"].includes(normalized)) {
    return null;
  }
  return `dronedream-desktop-auth:${normalized}:v1`;
}

const desktopStorageKey = desktopRuntime
  ? editionAuthStorageKey(
      import.meta.env.VITE_DRONEDREAM_EDITION as string | undefined,
    )
  : undefined;

export const cloudAuthConfigured = Boolean(
  supabaseUrl &&
  supabasePublishableKey &&
  (!desktopRuntime || desktopStorageKey),
);

export interface BrowserAuthConfiguration {
  supabaseUrl: string;
  publishableKey: string;
}

export function browserAuthConfiguration(): BrowserAuthConfiguration | null {
  if (!cloudAuthConfigured || !supabaseUrl || !supabasePublishableKey) return null;
  return {
    supabaseUrl,
    publishableKey: supabasePublishableKey,
  };
}

class VolatileAuthStorage implements Storage {
  readonly #values = new Map<string, string>();

  get length(): number {
    return this.#values.size;
  }

  clear(): void {
    this.#values.clear();
  }

  getItem(key: string): string | null {
    return this.#values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.#values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.#values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.#values.set(key, value);
  }
}

const volatileAuthStorage = new VolatileAuthStorage();
const STORAGE_PROBE_KEY = "__dronedream_auth_storage_probe__";

export function supabaseAuthClientOptions({
  desktop,
  storage,
  storageKey,
}: {
  desktop: boolean;
  storage: Storage | undefined;
  storageKey: string | null | undefined;
}) {
  const sharedOptions = {
    autoRefreshToken: true,
    detectSessionInUrl: !desktop,
    persistSession: true,
    storage,
  };
  return desktop && storageKey
    ? { ...sharedOptions, storageKey }
    : sharedOptions;
}

function authStorage(): Storage | undefined {
  if (typeof window === "undefined") return undefined;
  // Native owns the persistent refresh grant in an edition-scoped Windows
  // credential namespace. The WebView keeps only its active process session;
  // browser deployments may use normal origin-scoped localStorage.
  try {
    const storage = desktopRuntime ? window.sessionStorage : window.localStorage;
    storage.setItem(STORAGE_PROBE_KEY, "1");
    storage.removeItem(STORAGE_PROBE_KEY);
    return storage;
  } catch {
    return volatileAuthStorage;
  }
}

interface DroneDreamGlobal {
  __droneDreamSupabaseClient?: SupabaseClient;
}

const clientHost = globalThis as typeof globalThis & DroneDreamGlobal;

export const supabaseClient: SupabaseClient | null = cloudAuthConfigured
  ? (clientHost.__droneDreamSupabaseClient ??=
      createClient(supabaseUrl ?? "", supabasePublishableKey ?? "", {
        auth: supabaseAuthClientOptions({
          desktop: desktopRuntime,
          storage: authStorage(),
          storageKey: desktopStorageKey,
        }),
      }))
  : null;

export const googleAuthEnabled =
  import.meta.env.VITE_AUTH_GOOGLE_ENABLED === "true";
export const appleAuthEnabled =
  import.meta.env.VITE_AUTH_APPLE_ENABLED === "true";

export const turnstileSiteKey = (
  import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined
)?.trim() ?? "";
export const captchaProtectionConfigured = Boolean(turnstileSiteKey);
