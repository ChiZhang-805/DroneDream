import {
  restoreBrowserAuthVault,
  type BrowserAuthSession,
} from "../../desktop/bridge";
import { setAuthAccessToken } from "./authTokenStore";
import {
  ADOPT_DESKTOP_AUTH_EVENT,
  DESKTOP_AUTH_REFRESH_FAILED_EVENT,
} from "./desktopAuthActivation";
import { supabaseClient } from "./supabaseClient";

const EXPECTED_PROTOCOL = "desktop-browser-auth-pkce-v1";
const CLIENT_BY_EDITION = {
  universal: "dronedream-desktop-universal",
  sim: "dronedream-desktop-sim",
  lab: "dronedream-desktop-lab",
  field: "dronedream-desktop-field",
} as const;
let refreshTimer: number | null = null;
const REFRESH_RETRY_DELAYS_MS = [15_000, 30_000, 60_000, 120_000, 300_000] as const;

function tokenExpiryMs(accessToken: string): number | null {
  try {
    const payload = accessToken.split(".")[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = JSON.parse(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="))) as { exp?: unknown };
    return typeof decoded.exp === "number" && Number.isFinite(decoded.exp)
      ? decoded.exp * 1000
      : null;
  } catch {
    return null;
  }
}

function armNativeRefresh(accessToken: string, delay: number, retryAttempt: number): void {
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => {
    refreshTimer = null;
    void restoreBrowserAuthVault()
      .then((session) => {
        if (!session) throw new Error("The desktop credential vault returned no session.");
        return adoptBrowserAuthSession(session);
      })
      .catch(() => {
        const retryDelay = REFRESH_RETRY_DELAYS_MS[retryAttempt];
        const expiry = tokenExpiryMs(accessToken);
        if (
          retryDelay !== undefined
          && expiry !== null
          && Date.now() + retryDelay < expiry
        ) {
          armNativeRefresh(accessToken, retryDelay, retryAttempt + 1);
          return;
        }
        setAuthAccessToken(null);
        window.dispatchEvent(new Event(DESKTOP_AUTH_REFRESH_FAILED_EVENT));
      });
  }, delay);
}

function scheduleNativeRefresh(accessToken: string): void {
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  refreshTimer = null;
  const expiry = tokenExpiryMs(accessToken);
  if (expiry === null) return;
  const delay = Math.max(15_000, Math.min(expiry - Date.now() - 60_000, 24 * 60 * 60 * 1000));
  armNativeRefresh(accessToken, delay, 0);
}

export function clearBrowserAuthSessionRefresh(): void {
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  refreshTimer = null;
}

function expectedDesktopEdition(): keyof typeof CLIENT_BY_EDITION {
  const configured = (import.meta.env.VITE_DRONEDREAM_EDITION as string | undefined)
    ?.trim()
    .toLowerCase();
  if (configured && configured in CLIENT_BY_EDITION) {
    return configured as keyof typeof CLIENT_BY_EDITION;
  }
  return "universal";
}

export async function adoptBrowserAuthSession(
  session: BrowserAuthSession,
  options: { signal?: AbortSignal } = {},
): Promise<void> {
  const throwIfCancelled = () => {
    if (options.signal?.aborted) {
      throw new Error("Desktop browser sign-in cancelled.");
    }
  };
  throwIfCancelled();
  if (!supabaseClient) {
    throw new Error("DroneDream account authentication is not configured.");
  }
  const edition = expectedDesktopEdition();
  if (
    session.protocolVersion !== EXPECTED_PROTOCOL
    || session.editionId !== edition
    || session.authClientId !== CLIENT_BY_EDITION[edition]
  ) {
    throw new Error("The browser session belongs to a different DroneDream edition.");
  }
  const { data, error } = await supabaseClient.auth.getUser(session.accessToken);
  // Cancellation must win over a token response. No account event or access
  // token may escape after the operator has cancelled the transaction.
  throwIfCancelled();
  if (error || !data.user) {
    throw new Error(error?.message || "The browser session could not be adopted.");
  }
  setAuthAccessToken(session.accessToken);
  window.dispatchEvent(new CustomEvent(ADOPT_DESKTOP_AUTH_EVENT, {
    detail: { user: data.user, accessToken: session.accessToken },
  }));
  scheduleNativeRefresh(session.accessToken);
}
