import { createClient } from "@supabase/supabase-js";
import { describe, expect, it } from "vitest";

import {
  editionAuthStorageKey,
  supabaseAuthClientOptions,
} from "../features/auth/supabaseClient";

class TestStorage implements Storage {
  readonly reads: string[] = [];
  readonly #values = new Map<string, string>();

  get length() {
    return this.#values.size;
  }

  clear() {
    this.#values.clear();
  }

  getItem(key: string) {
    this.reads.push(String(key));
    return this.#values.get(String(key)) ?? null;
  }

  key(index: number) {
    return [...this.#values.keys()][index] ?? null;
  }

  removeItem(key: string) {
    this.#values.delete(String(key));
  }

  setItem(key: string, value: string) {
    this.#values.set(String(key), String(value));
  }
}

describe("Supabase session namespace", () => {
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

  it("omits the storageKey property for the browser client", () => {
    const options = supabaseAuthClientOptions({
      desktop: false,
      storage: new TestStorage(),
      storageKey: null,
    });

    expect(Object.hasOwn(options, "storageKey")).toBe(false);
  });

  it("restores a browser session from the standard Supabase storage key", async () => {
    const storage = new TestStorage();
    const storageKey = "sb-local-preview-auth-token";
    const session = {
      access_token: "synthetic-access-token",
      refresh_token: "synthetic-refresh-token",
      token_type: "bearer",
      expires_in: 3_600,
      expires_at: Math.floor(Date.now() / 1_000) + 3_600,
      user: {
        id: "user-1",
        aud: "authenticated",
        role: "authenticated",
        email: "pilot@example.test",
        app_metadata: { provider: "email", providers: ["email"] },
        user_metadata: {},
        identities: [],
        created_at: "2026-01-01T00:00:00.000Z",
      },
    };
    storage.setItem(storageKey, JSON.stringify(session));
    const client = createClient(
      "https://local-preview.invalid",
      "local-preview-only",
      {
        auth: supabaseAuthClientOptions({
          desktop: false,
          storage,
          storageKey: null,
        }),
      },
    );

    const { data, error } = await client.auth.getSession();

    expect(error).toBeNull();
    expect(data.session?.user.id).toBe("user-1");
    expect(storage.reads).toContain(storageKey);
    expect(storage.reads).not.toContain("undefined");
  });

  it("adds an edition-scoped storage key only for desktop", () => {
    const key = editionAuthStorageKey("sim");
    const desktopOptions = supabaseAuthClientOptions({
      desktop: true,
      storage: new TestStorage(),
      storageKey: key,
    });
    const browserOptions = supabaseAuthClientOptions({
      desktop: false,
      storage: new TestStorage(),
      storageKey: key,
    });

    expect(Object.hasOwn(desktopOptions, "storageKey")).toBe(true);
    expect("storageKey" in desktopOptions ? desktopOptions.storageKey : null)
      .toBe("dronedream-desktop-auth:sim:v1");
    expect(Object.hasOwn(browserOptions, "storageKey")).toBe(false);
  });
});
