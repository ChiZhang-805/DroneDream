import { describe, expect, it } from "vitest";

import { editionAuthStorageKey } from "../features/auth/supabaseClient";

describe("desktop Supabase session namespace", () => {
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
