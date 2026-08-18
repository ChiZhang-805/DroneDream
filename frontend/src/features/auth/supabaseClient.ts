import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { isDesktopRuntime } from "../../desktop/bridge";

const supabaseUrl = (
  import.meta.env.VITE_SUPABASE_URL as string | undefined
)?.trim();
const supabasePublishableKey = (
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
)?.trim();
const desktopRuntime = isDesktopRuntime();
export const BROWSER_AUTH_STORAGE_KEY = "dronedream-browser-auth:v1";
const LEGACY_BROWSER_AUTH_STORAGE_KEY = "undefined";

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
    // Some enterprise browser/WebView policies expose the Storage property but
    // throw on access. Keep the session usable in memory for this process
    // instead of crashing module initialization or falling back to a different
    // persistent storage class.
    return volatileAuthStorage;
  }
}

export function migrateLegacyBrowserAuthStorage(
  storage: Storage | undefined,
): void {
  if (!storage || desktopRuntime) return;
  try {
    if (storage.getItem(BROWSER_AUTH_STORAGE_KEY)) return;
    const legacy = storage.getItem(LEGACY_BROWSER_AUTH_STORAGE_KEY);
    if (!legacy) return;
    const parsed = JSON.parse(legacy) as Record<string, unknown>;
    if (
      typeof parsed.access_token !== "string"
      || typeof parsed.refresh_token !== "string"
      || typeof parsed.user !== "object"
      || parsed.user === null
    ) {
      return;
    }
    storage.setItem(BROWSER_AUTH_STORAGE_KEY, legacy);
    storage.removeItem(LEGACY_BROWSER_AUTH_STORAGE_KEY);
  } catch {
    // A malformed or inaccessible legacy entry must not block authentication.
  }
}

interface DroneDreamGlobal {
  __droneDreamSupabaseClient?: SupabaseClient;
}

const clientHost = globalThis as typeof globalThis & DroneDreamGlobal;
const selectedAuthStorage = authStorage();
migrateLegacyBrowserAuthStorage(selectedAuthStorage);

export const supabaseClient: SupabaseClient | null = cloudAuthConfigured
  ? (clientHost.__droneDreamSupabaseClient ??=
      createClient(supabaseUrl ?? "", supabasePublishableKey ?? "", {
        auth: {
          autoRefreshToken: true,
          detectSessionInUrl: !isDesktopRuntime(),
          persistSession: true,
          storage: selectedAuthStorage,
          storageKey: desktopStorageKey ?? BROWSER_AUTH_STORAGE_KEY,
        },
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
