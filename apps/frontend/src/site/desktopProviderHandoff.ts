import type { BrowserAuthRequest } from "../desktop/bridge";
import { isAllowedDesktopRedirectUri } from "./oauthConsentPolicy";

export type DesktopSocialProvider = NonNullable<BrowserAuthRequest["provider"]>;
const PREFERENCE_KEY = "dronedream:desktop-provider-preference:v1";
const RETURN_KEY = "dronedream:desktop-provider-return:v1";
const MAX_AGE_MS = 10 * 60 * 1000;
const PROVIDERS: readonly string[] = ["google", "github", "slack_oidc"];

function isProvider(value: unknown): value is DesktopSocialProvider {
  return typeof value === "string" && PROVIDERS.includes(value);
}

export function hasDesktopProviderHandoff(search = window.location.search): boolean {
  const params = new URLSearchParams(search);
  return params.has("desktop_provider") || params.has("desktop_authorize");
}

/** Accept only the fixed authorization service and registered desktop callbacks. */
export function parseDesktopProviderHandoff(href: string, supabaseUrl: string) {
  try {
    const entry = new URL(href);
    if (entry.origin !== "https://getdronedream.com"
      || !["/oauth/consent", "/oauth/consent/"].includes(entry.pathname)) return null;
    const params = entry.searchParams;
    const allowed = ["desktop_provider", "desktop_authorize", "locale"];
    if ([...params.keys()].some((key) => !allowed.includes(key) || params.getAll(key).length !== 1)) return null;
    const provider = params.get("desktop_provider");
    const rawAuthorize = params.get("desktop_authorize");
    if (!isProvider(provider) || !rawAuthorize || rawAuthorize.length > 4096) return null;
    if (params.has("locale") && !["en", "zh-CN"].includes(params.get("locale") ?? "")) return null;
    if (entry.hash || entry.username || entry.password) return null;
    const expected = new URL("/auth/v1/oauth/authorize", supabaseUrl);
    const authorize = new URL(rawAuthorize);
    if (expected.protocol !== "https:" || authorize.origin !== expected.origin
      || authorize.pathname !== expected.pathname || authorize.hash
      || authorize.username || authorize.password) return null;
    const fields = authorize.searchParams;
    const keys = ["response_type", "client_id", "redirect_uri", "state", "code_challenge", "code_challenge_method", "scope", "nonce"];
    if ([...fields.keys()].some((key) => !keys.includes(key))
      || keys.some((key) => fields.getAll(key).length !== 1)) return null;
    if (fields.get("response_type") !== "code" || fields.get("code_challenge_method") !== "S256"
      || fields.get("scope") !== "openid email profile"
      || !isAllowedDesktopRedirectUri(fields.get("redirect_uri") ?? "")
      || !/^[A-Za-z0-9_-]{8,512}$/u.test(fields.get("client_id") ?? "")
      || !/^[a-f0-9]{64}$/u.test(fields.get("state") ?? "")
      || !/^[a-f0-9]{64}$/u.test(fields.get("nonce") ?? "")
      || !/^[A-Za-z0-9_-]{43}$/u.test(fields.get("code_challenge") ?? "")) return null;
    return { provider, authorizeUrl: authorize.toString() };
  } catch {
    return null;
  }
}

function readFresh(key: string, now: number): Record<string, unknown> | null {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(key) ?? "null") as Record<string, unknown> | null;
    if (!value || typeof value.createdAt !== "number"
      || now < value.createdAt || now - value.createdAt > MAX_AGE_MS
      || !isProvider(value.provider)) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

export function rememberDesktopProviderPreference(provider: DesktopSocialProvider, now = Date.now()): void {
  if (!isProvider(provider)) throw new Error("Unsupported sign-in provider.");
  window.sessionStorage.setItem(PREFERENCE_KEY, JSON.stringify({ provider, createdAt: now }));
}

/** A preference only chooses a provider; it never authorizes or authenticates. */
export function takeDesktopProviderPreference(now = Date.now()): DesktopSocialProvider | null {
  const value = readFresh(PREFERENCE_KEY, now);
  try { window.sessionStorage.removeItem(PREFERENCE_KEY); } catch { return null; }
  return value?.provider as DesktopSocialProvider | undefined ?? null;
}

export function markDesktopProviderRedirect(authorizationId: string, provider: DesktopSocialProvider, now = Date.now()): void {
  if (!/^[A-Za-z0-9._~-]{8,512}$/u.test(authorizationId) || !isProvider(provider)) {
    throw new Error("Invalid provider sign-in request.");
  }
  window.sessionStorage.setItem(RETURN_KEY, JSON.stringify({ authorizationId, provider, createdAt: now }));
}

/** Consume only after the SDK publishes an authenticated account on OAuth return. */
export function consumeDesktopProviderReturn(authorizationId: string, now = Date.now()): boolean {
  const value = readFresh(RETURN_KEY, now);
  if (value?.authorizationId !== authorizationId) return false;
  try { window.sessionStorage.removeItem(RETURN_KEY); } catch { return false; }
  return true;
}

export function clearDesktopProviderReturn(): void {
  try { window.sessionStorage.removeItem(RETURN_KEY); } catch { /* No persisted continuation. */ }
}
