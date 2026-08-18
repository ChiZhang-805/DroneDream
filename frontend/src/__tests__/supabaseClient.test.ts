import { describe, expect, it } from "vitest";

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
    const keys = ["universal", "sim", "lab", "field"]
      .map((edition) => editionAuthStorageKey(edition));

    expect(new Set(keys).size).toBe(4);
    expect(keys).toEqual([
      "dronedream-desktop-auth:universal:v1",
      "dronedream-desktop-auth:sim:v1",
      "dronedream-desktop-auth:lab:v1",
      "dronedream-desktop-auth:field:v1",
    ]);
  });

  it("fails closed for missing or unknown edition identities", () => {
    expect(editionAuthStorageKey(undefined)).toBeNull();
    expect(editionAuthStorageKey("")).toBeNull();
    expect(editionAuthStorageKey("unknown")).toBeNull();
  });
});
