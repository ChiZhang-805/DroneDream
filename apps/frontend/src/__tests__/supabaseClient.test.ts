import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BROWSER_AUTH_STORAGE_KEY,
  editionAuthStorageKey,
  migrateLegacyBrowserAuthStorage,
} from "../features/auth/supabaseClient";

describe("desktop Supabase session namespace", () => {
  it("uses an explicit browser session namespace", () => {
    expect(BROWSER_AUTH_STORAGE_KEY).toBe("dronedream-browser-auth:v1");
  });

  it("migrates only a structurally valid legacy browser session", () => {
    const session = JSON.stringify({
      access_token: "access-token",
      refresh_token: "refresh-token",
      user: { id: "user-1" },
    });
    window.localStorage.setItem("undefined", session);

    migrateLegacyBrowserAuthStorage(window.localStorage);

    expect(window.localStorage.getItem(BROWSER_AUTH_STORAGE_KEY)).toBe(session);
    expect(window.localStorage.getItem("undefined")).toBeNull();
    window.localStorage.clear();

    window.localStorage.setItem("undefined", JSON.stringify({ theme: "dark" }));
    migrateLegacyBrowserAuthStorage(window.localStorage);
    expect(window.localStorage.getItem(BROWSER_AUTH_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem("undefined")).not.toBeNull();
    window.localStorage.clear();
  });

  it("uses a distinct versioned WebView storage key for every edition", () => {
    const keys = ["universal", "sim", "lab", "field", "autonomy"]
      .map((edition) => editionAuthStorageKey(edition));

    expect(new Set(keys).size).toBe(5);
    expect(keys).toEqual([
      "dronedream-desktop-auth:universal:v1",
      "dronedream-desktop-auth:sim:v1",
      "dronedream-desktop-auth:lab:v1",
      "dronedream-desktop-auth:field:v1",
      "dronedream-desktop-auth:autonomy:v1",
    ]);
  });

  it("fails closed for missing or unknown edition identities", () => {
    expect(editionAuthStorageKey(undefined)).toBeNull();
    expect(editionAuthStorageKey("")).toBeNull();
    expect(editionAuthStorageKey("unknown")).toBeNull();
  });
});

describe("desktop session hydration", () => {
  const currentKey = "dronedream-desktop-auth:autonomy:v1";
  const session = JSON.stringify({
    access_token: "active-access-token",
    refresh_token: "active-refresh-token",
    user: { id: "pilot-1" },
  });

  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    vi.stubEnv("VITE_DRONEDREAM_EDITION", "autonomy");
    // These storage tests must not create a live cloud client.
    vi.stubEnv("VITE_SUPABASE_URL", "");
    vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", "");
  });

  afterEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    delete window.__TAURI__;
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("does not restore a desktop login from a previous WebView session", async () => {
    window.sessionStorage.setItem(currentKey, session);
    const { hasActiveDesktopAuthSession } = await import("../features/auth/supabaseClient");

    expect(hasActiveDesktopAuthSession()).toBe(false);
    window.sessionStorage.removeItem(currentKey);
    expect(hasActiveDesktopAuthSession()).toBe(false);
  });

  it("does not use another edition or persistent browser storage to bypass sign-in", async () => {
    window.sessionStorage.setItem("dronedream-desktop-auth:sim:v1", session);
    window.sessionStorage.setItem(BROWSER_AUTH_STORAGE_KEY, session);
    window.localStorage.setItem(currentKey, session);
    window.localStorage.setItem(BROWSER_AUTH_STORAGE_KEY, session);
    const { hasActiveDesktopAuthSession } = await import("../features/auth/supabaseClient");

    expect(hasActiveDesktopAuthSession()).toBe(false);
  });

  it.each([
    "not-json",
    "null",
    "{}",
    JSON.stringify({ access_token: "", refresh_token: "refresh", user: {} }),
    JSON.stringify({ access_token: "access", refresh_token: "", user: {} }),
    JSON.stringify({ access_token: "access", refresh_token: "refresh", user: null }),
  ])("ignores a malformed stored session: %s", async (stored) => {
    window.sessionStorage.setItem(currentKey, stored);
    const { hasActiveDesktopAuthSession } = await import("../features/auth/supabaseClient");

    expect(hasActiveDesktopAuthSession()).toBe(false);
  });

  it("does not activate desktop hydration in a normal browser", async () => {
    delete window.__TAURI__;
    window.sessionStorage.setItem(currentKey, session);
    const { hasActiveDesktopAuthSession } = await import("../features/auth/supabaseClient");

    expect(hasActiveDesktopAuthSession()).toBe(false);
  });

  it("requires a known edition identity even when a session exists", async () => {
    vi.stubEnv("VITE_DRONEDREAM_EDITION", "unknown");
    window.sessionStorage.setItem(currentKey, session);
    const { hasActiveDesktopAuthSession } = await import("../features/auth/supabaseClient");

    expect(hasActiveDesktopAuthSession()).toBe(false);
  });
});

describe("direct browser provider response", () => {
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).__droneDreamSupabaseClient;
    window.history.replaceState(null, "", "/");
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it.each([
    ["#access_token=fresh&refresh_token=refresh", "fresh", "pilot-1"],
    ["#access_token=fresh&refresh_token=refresh", "old-session", null],
    ["#error=access_denied", "old-session", null],
    ["", "old-session", null],
  ])("verifies the returned grant, never a previously stored session (%s)", async (hash, storedToken, expected) => {
    vi.resetModules();
    delete window.__TAURI__;
    vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", "public-test-key");
    window.history.replaceState(null, "", `/oauth/consent?authorization_id=request-123&desktop_provider_return=google${hash}`);
    const getUser = vi.fn().mockResolvedValue({ data: { user: { id: "pilot-1" } }, error: null });
    (globalThis as Record<string, unknown>).__droneDreamSupabaseClient = {
      auth: {
        getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: storedToken } }, error: null }),
        getUser,
      },
    };
    const { verifyBrowserProviderReturn } = await import("../features/auth/supabaseClient");
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    expect(await verifyBrowserProviderReturn()).toBe(expected);
    expect(await verifyBrowserProviderReturn()).toBe(expected);
    expect(getUser).toHaveBeenCalledTimes(expected ? 1 : 0);
  });
});
