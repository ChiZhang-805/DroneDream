import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearDesktopProviderReturn,
  consumeDesktopProviderReturn,
  hasDesktopProviderHandoff,
  markDesktopProviderRedirect,
  parseDesktopProviderHandoff,
  rememberDesktopProviderPreference,
  takeDesktopProviderPreference,
} from "../site/desktopProviderHandoff";

const AUTH_ORIGIN = "https://accounts.example.test";
const NOW = 1_800_000_000_000;

function authorizeUrl() {
  const url = new URL("/auth/v1/oauth/authorize", AUTH_ORIGIN);
  url.search = new URLSearchParams({
    response_type: "code",
    client_id: "desktop-provider-client",
    redirect_uri: "http://127.0.0.1:49214/desktop-auth/autonomy/callback",
    state: "a".repeat(64),
    nonce: "b".repeat(64),
    code_challenge: "c".repeat(43),
    code_challenge_method: "S256",
    scope: "openid email profile",
  }).toString();
  return url;
}

function entryUrl(authorize = authorizeUrl(), provider = "google") {
  const url = new URL("https://getdronedream.com/oauth/consent");
  url.search = new URLSearchParams({
    desktop_provider: provider,
    desktop_authorize: authorize.toString(),
    locale: "en",
  }).toString();
  return url;
}

describe("desktop social provider handoff", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("distinguishes an initial provider handoff from the authorization return", () => {
    expect(hasDesktopProviderHandoff("?desktop_provider=google")).toBe(true);
    expect(hasDesktopProviderHandoff("?desktop_authorize=invalid")).toBe(true);
    expect(hasDesktopProviderHandoff("?authorization_id=authorization-1")).toBe(false);
  });

  it.each(["google", "github", "slack_oidc"])(
    "keeps the native PKCE authorization intact when selecting %s",
    (provider) => {
      const authorize = authorizeUrl();
      expect(parseDesktopProviderHandoff(entryUrl(authorize, provider).toString(), AUTH_ORIGIN))
        .toEqual({ provider, authorizeUrl: authorize.toString() });
    },
  );

  it("accepts the canonical trailing-slash production route without changing the native request", () => {
    const authorize = authorizeUrl();
    const entry = entryUrl(authorize);
    entry.pathname = "/oauth/consent/";
    expect(parseDesktopProviderHandoff(entry.toString(), AUTH_ORIGIN))
      .toEqual({ provider: "google", authorizeUrl: authorize.toString() });
  });

  it.each([
    ["universal", 49210], ["sim", 49211], ["lab", 49212], ["field", 49213], ["autonomy", 49214],
  ])("allows the registered callback for %s without changing its edition", (edition, port) => {
    const authorize = authorizeUrl();
    const redirect = `http://127.0.0.1:${port}/desktop-auth/${edition}/callback`;
    authorize.searchParams.set("redirect_uri", redirect);
    const parsed = parseDesktopProviderHandoff(entryUrl(authorize).toString(), AUTH_ORIGIN);
    expect(parsed).not.toBeNull();
    expect(new URL(parsed!.authorizeUrl).searchParams.get("redirect_uri")).toBe(redirect);
  });

  it.each([
    ["HTTP downgrade", (url: URL) => { url.protocol = "http:"; }],
    ["another host", (url: URL) => { url.hostname = "untrusted.example.test"; }],
    ["another path", (url: URL) => { url.pathname = "/auth/v1/authorize"; }],
    ["userinfo", (url: URL) => { url.username = "pilot"; }],
    ["fragment", (url: URL) => { url.hash = "secret"; }],
    ["extra token", (url: URL) => { url.searchParams.set("access_token", "not-a-valid-handoff"); }],
    ["duplicate state", (url: URL) => { url.searchParams.append("state", "d".repeat(64)); }],
    ["missing nonce", (url: URL) => { url.searchParams.delete("nonce"); }],
    ["implicit token response", (url: URL) => { url.searchParams.set("response_type", "token"); }],
    ["plain challenge", (url: URL) => { url.searchParams.set("code_challenge_method", "plain"); }],
    ["unregistered callback", (url: URL) => { url.searchParams.set("redirect_uri", "http://127.0.0.1:49210/desktop-auth/sim/callback"); }],
    ["broad scopes", (url: URL) => { url.searchParams.set("scope", "openid email profile admin"); }],
  ] as const)("rejects an authorization URL with %s", (_label, change) => {
    const authorize = authorizeUrl();
    change(authorize);
    expect(parseDesktopProviderHandoff(entryUrl(authorize).toString(), AUTH_ORIGIN)).toBeNull();
  });

  it.each([
    ["HTTP entry", (url: URL) => { url.protocol = "http:"; }],
    ["untrusted entry origin", (url: URL) => { url.hostname = "untrusted.example.test"; }],
    ["another entry path", (url: URL) => { url.pathname = "/account"; }],
    ["unsupported locale", (url: URL) => { url.searchParams.set("locale", "xx-YY"); }],
    ["unknown provider", (url: URL) => { url.searchParams.set("desktop_provider", "untrusted"); }],
    ["duplicate provider", (url: URL) => { url.searchParams.append("desktop_provider", "github"); }],
    ["missing authorization", (url: URL) => { url.searchParams.delete("desktop_authorize"); }],
    ["extra redirect", (url: URL) => { url.searchParams.set("redirectTo", "https://untrusted.example.test"); }],
    ["fragment", (url: URL) => { url.hash = "token"; }],
    ["userinfo", (url: URL) => { url.username = "pilot"; }],
  ] as const)("rejects an initial handoff with %s", (_label, change) => {
    const entry = entryUrl();
    change(entry);
    expect(parseDesktopProviderHandoff(entry.toString(), AUTH_ORIGIN)).toBeNull();
  });

  it("stores only a short-lived provider preference in this tab and consumes it once", () => {
    rememberDesktopProviderPreference("google", NOW);
    expect(window.sessionStorage.length).toBe(1);
    const value = JSON.parse(window.sessionStorage.getItem(window.sessionStorage.key(0)!)!);
    expect(value).toEqual({ provider: "google", createdAt: NOW });
    expect(window.localStorage.length).toBe(0);
    expect(takeDesktopProviderPreference(NOW + 60_000)).toBe("google");
    expect(takeDesktopProviderPreference(NOW + 60_000)).toBeNull();
  });

  it.each([NOW - 1, NOW + 600_001])("rejects a preference with an invalid age at %s", (time) => {
    rememberDesktopProviderPreference("github", NOW);
    expect(takeDesktopProviderPreference(time)).toBeNull();
    expect(window.sessionStorage.length).toBe(0);
  });

  it("matches the provider return to exactly one authorization request", () => {
    markDesktopProviderRedirect("authorization-1", "slack_oidc", NOW);
    expect(consumeDesktopProviderReturn("authorization-2", NOW + 1)).toBe(false);
    expect(consumeDesktopProviderReturn("authorization-1", NOW + 1)).toBe(true);
    expect(consumeDesktopProviderReturn("authorization-1", NOW + 1)).toBe(false);
    expect(window.localStorage.length).toBe(0);
  });

  it("rejects expired returns and explicitly clears abandoned requests", () => {
    markDesktopProviderRedirect("authorization-1", "google", NOW);
    expect(consumeDesktopProviderReturn("authorization-1", NOW + 600_001)).toBe(false);
    markDesktopProviderRedirect("authorization-2", "github", NOW);
    clearDesktopProviderReturn();
    expect(consumeDesktopProviderReturn("authorization-2", NOW)).toBe(false);
  });

  it("fails closed when the preference cannot be read from tab storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("storage unavailable"); });
    expect(takeDesktopProviderPreference(NOW)).toBeNull();
    expect(consumeDesktopProviderReturn("authorization-1", NOW)).toBe(false);
  });
});
