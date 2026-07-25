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

function authStorage(): Storage | undefined {
  if (typeof window === "undefined") return undefined;
  // The desktop WebView does not yet have an OS-keychain-backed storage
  // adapter. Keep its refresh token session-scoped instead of writing it to
  // persistent WebView localStorage. Browser deployments may use the normal
  // origin-scoped localStorage session.
  return isDesktopRuntime() ? window.sessionStorage : window.localStorage;
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
