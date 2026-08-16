import {
  restoreBrowserAuthVault,
  type BrowserAuthSession,
} from "../../desktop/bridge";
import { setAuthAccessToken } from "./authTokenStore";
import { ADOPT_DESKTOP_AUTH_EVENT } from "./desktopAuthActivation";
import { supabaseClient } from "./supabaseClient";

const EXPECTED_PROTOCOL = "desktop-browser-auth-pkce-v1";
const CLIENT_BY_EDITION = {
  universal: "dronedream-desktop-universal",
  sim: "dronedream-desktop-sim",
  lab: "dronedream-desktop-lab",
  field: "dronedream-desktop-field",
} as const;
let refreshTimer: number | null = null;

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

function scheduleNativeRefresh(accessToken: string): void {
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  refreshTimer = null;
  const expiry = tokenExpiryMs(accessToken);
  if (expiry === null) return;
  const delay = Math.max(15_000, Math.min(expiry - Date.now() - 60_000, 24 * 60 * 60 * 1000));
  refreshTimer = window.setTimeout(() => {
    refreshTimer = null;
    void restoreBrowserAuthVault()
      .then((session) => session && adoptBrowserAuthSession(session))
      .catch(() => undefined);
  }, delay);
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
): Promise<void> {
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
  if (error || !data.user) {
    throw new Error(error?.message || "The browser session could not be adopted.");
  }
  setAuthAccessToken(session.accessToken);
  window.dispatchEvent(new CustomEvent(ADOPT_DESKTOP_AUTH_EVENT, {
    detail: { user: data.user, accessToken: session.accessToken },
  }));
  scheduleNativeRefresh(session.accessToken);
}
