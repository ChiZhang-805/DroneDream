import { describe, expect, it } from "vitest";

import {
  isAccountCommunityOriginAllowed,
  isSensitiveCloudOriginAllowed,
} from "../security/sensitiveOrigin";

describe("sensitive cloud origin policy", () => {
  it("rejects the public HTTP mirror and unknown or opaque origins", () => {
    expect(isSensitiveCloudOriginAllowed("http://47.93.180.216/community/"))
      .toBe(false);
    expect(isSensitiveCloudOriginAllowed("http://getdronedream.com/pricing/"))
      .toBe(false);
    expect(isSensitiveCloudOriginAllowed("https://unknown.example/"))
      .toBe(false);
    expect(
      isSensitiveCloudOriginAllowed("https://getdronedream.com:8443/"),
    ).toBe(false);
    expect(isSensitiveCloudOriginAllowed("null")).toBe(false);
  });

  it("allows explicit HTTPS production origins and local app development", () => {
    expect(isSensitiveCloudOriginAllowed("https://getdronedream.com/"))
      .toBe(true);
    expect(
      isSensitiveCloudOriginAllowed(
        "https://chizhang-805.github.io/DroneDream/",
      ),
    ).toBe(true);
    expect(isSensitiveCloudOriginAllowed("http://localhost:5173/")).toBe(true);
    expect(isSensitiveCloudOriginAllowed("http://tauri.localhost/")).toBe(true);
    expect(isSensitiveCloudOriginAllowed("tauri://localhost/")).toBe(true);
  });

  it("allows account and community access on the approved HTTP preview origins only", () => {
    expect(isAccountCommunityOriginAllowed("http://47.93.180.216/community/"))
      .toBe(true);
    expect(isAccountCommunityOriginAllowed("http://getdronedream.com/account/"))
      .toBe(true);
    expect(isAccountCommunityOriginAllowed("http://www.getdronedream.com/community/"))
      .toBe(true);
    expect(isAccountCommunityOriginAllowed("http://47.93.180.216:8080/account/"))
      .toBe(false);
    expect(isAccountCommunityOriginAllowed("http://unknown.example/community/"))
      .toBe(false);
    expect(isAccountCommunityOriginAllowed("null")).toBe(false);
  });
});
