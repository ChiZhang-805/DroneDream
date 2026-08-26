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
  autonomy: "dronedream-desktop-autonomy",
} as const;

export type BrowserAuthAdoptionFailure =
  | "configuration"
  | "session-binding"
  | "credential-rejected"
  | "transient"
  | "unknown";

export class BrowserAuthAdoptionError extends Error {
  readonly failure: BrowserAuthAdoptionFailure;

  constructor(
    message: string,
    failure: BrowserAuthAdoptionFailure,
    cause?: unknown,
  ) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "BrowserAuthAdoptionError";
    this.failure = failure;
  }
}

export function shouldClearBrowserAuthVaultAfterAdoptionError(
  error: unknown,
): boolean {
  return error instanceof BrowserAuthAdoptionError
    && (
      error.failure === "session-binding"
      || error.failure === "credential-rejected"
    );
}

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
  if (!configured) return "universal";
  if (Object.hasOwn(CLIENT_BY_EDITION, configured)) {
    return configured as keyof typeof CLIENT_BY_EDITION;
  }
  throw new BrowserAuthAdoptionError(
    `The configured DroneDream edition "${configured}" is unsupported. Browser session adoption was blocked.`,
    "configuration",
  );
}

function errorDetails(error: unknown): {
  message: string | null;
  name: string | null;
  status: number | null;
  code: string | null;
} {
  if (typeof error !== "object" || error === null) {
    return {
      message: typeof error === "string" && error.trim() ? error : null,
      name: null,
      status: null,
      code: null,
    };
  }
  const candidate = error as {
    message?: unknown;
    name?: unknown;
    status?: unknown;
    code?: unknown;
  };
  return {
    message: typeof candidate.message === "string" && candidate.message.trim()
      ? candidate.message
      : null,
    name: typeof candidate.name === "string" ? candidate.name : null,
    status: typeof candidate.status === "number" && Number.isFinite(candidate.status)
      ? candidate.status
      : null,
    code: typeof candidate.code === "string" ? candidate.code : null,
  };
}

function classifyRemoteAdoptionError(error: unknown): BrowserAuthAdoptionError {
  const { message, name, status, code } = errorDetails(error);
  const normalizedMessage = message?.toLowerCase() ?? "";
  if (
    status === 401
    || status === 403
    || name === "AuthSessionMissingError"
    || code === "session_not_found"
  ) {
    return new BrowserAuthAdoptionError(
      message ?? "The saved browser session is no longer authorized.",
      "credential-rejected",
      error,
    );
  }
  if (
    status === 0
    || status === 429
    || (status !== null && status >= 500 && status <= 599)
    || name === "AuthRetryableFetchError"
    || name === "AbortError"
    || name === "TimeoutError"
    || normalizedMessage.includes("failed to fetch")
    || normalizedMessage.includes("network")
    || normalizedMessage.includes("timed out")
    || normalizedMessage.includes("timeout")
    || normalizedMessage.includes("offline")
    || normalizedMessage.includes("temporarily unavailable")
  ) {
    return new BrowserAuthAdoptionError(
      message
        ?? "The account service could not validate the saved browser session. The saved sign-in was preserved; try again.",
      "transient",
      error,
    );
  }
  return new BrowserAuthAdoptionError(
    message
      ?? "The browser session could not be adopted. The saved sign-in was preserved; try again.",
    "unknown",
    error,
  );
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
    throw new BrowserAuthAdoptionError(
      "DroneDream account authentication is not configured.",
      "configuration",
    );
  }
  const edition = expectedDesktopEdition();
  if (session.protocolVersion !== EXPECTED_PROTOCOL) {
    throw new BrowserAuthAdoptionError(
      "The browser session uses an unsupported authentication protocol.",
      "session-binding",
    );
  }
  if (session.editionId !== edition) {
    throw new BrowserAuthAdoptionError(
      "The browser session belongs to a different DroneDream edition.",
      "session-binding",
    );
  }
  if (session.authClientId !== CLIENT_BY_EDITION[edition]) {
    throw new BrowserAuthAdoptionError(
      "The browser session does not match this DroneDream edition's authentication client.",
      "session-binding",
    );
  }
  let response: Awaited<ReturnType<typeof supabaseClient.auth.getUser>>;
  try {
    response = await supabaseClient.auth.getUser(session.accessToken);
  } catch (error) {
    throwIfCancelled();
    throw classifyRemoteAdoptionError(error);
  }
  // Cancellation must win over a token response. No account event or access
  // token may escape after the operator has cancelled the transaction.
  throwIfCancelled();
  const { data, error } = response;
  if (error || !data.user) {
    if (!error) {
      throw new BrowserAuthAdoptionError(
        "The browser session could not be adopted because it has no authenticated account.",
        "credential-rejected",
      );
    }
    throw classifyRemoteAdoptionError(error);
  }
  setAuthAccessToken(session.accessToken);
  window.dispatchEvent(new CustomEvent(ADOPT_DESKTOP_AUTH_EVENT, {
    detail: { user: data.user, accessToken: session.accessToken },
  }));
  scheduleNativeRefresh(session.accessToken);
}
