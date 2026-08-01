import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { isDesktopRuntime } from "../../desktop/bridge";

const supabaseUrl = (
  import.meta.env.VITE_SUPABASE_URL as string | undefined
)?.trim();
const supabasePublishableKey = (
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
)?.trim();

export const cloudAuthConfigured = Boolean(
  supabaseUrl && supabasePublishableKey,
);

export interface BrowserAuthConfiguration {
  supabaseUrl: string;
  publishableKey: string;
}

export function browserAuthConfiguration(): BrowserAuthConfiguration | null {
  if (!supabaseUrl || !supabasePublishableKey) return null;
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
  // The desktop WebView does not yet have an OS-keychain-backed storage
  // adapter. Keep its refresh token session-scoped instead of writing it to
  // persistent WebView localStorage. Browser deployments may use the normal
  // origin-scoped localStorage session.
  try {
    const storage = isDesktopRuntime() ? window.sessionStorage : window.localStorage;
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

interface DroneDreamGlobal {
  __droneDreamSupabaseClient?: SupabaseClient;
}

const clientHost = globalThis as typeof globalThis & DroneDreamGlobal;

export const supabaseClient: SupabaseClient | null = cloudAuthConfigured
  ? (clientHost.__droneDreamSupabaseClient ??=
      createClient(supabaseUrl ?? "", supabasePublishableKey ?? "", {
        auth: {
          autoRefreshToken: true,
          detectSessionInUrl: !isDesktopRuntime(),
          persistSession: true,
          storage: authStorage(),
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
