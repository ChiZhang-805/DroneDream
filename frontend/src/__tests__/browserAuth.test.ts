import { beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  getUser: vi.fn(),
}));

vi.mock("../features/auth/supabaseClient", () => ({
  supabaseClient: {
    auth: {
      getUser: authMock.getUser,
    },
  },
}));

import { adoptBrowserAuthSession } from "../features/auth/browserAuth";

const validSession = {
  protocolVersion: "desktop-browser-auth-pkce-v1" as const,
  editionId: "universal" as const,
  authClientId: "dronedream-desktop-universal",
  accessToken: "header.payload.signature",
  attemptIdHash: "a".repeat(64),
  stateHash: "b".repeat(64),
  subjectHash: "c".repeat(64),
  issuedAt: "2026-08-05T08:00:00Z",
  completedAt: "2026-08-05T08:00:01Z",
};

describe("browser auth session adoption", () => {
  beforeEach(() => {
    authMock.getUser.mockReset();
  });

  it("validates the access token without exposing the native refresh grant", async () => {
    const user = { id: "user-1", email: "pilot@example.com", user_metadata: {} };
    authMock.getUser.mockResolvedValue({ data: { user }, error: null });
    const listener = vi.fn();
    window.addEventListener("drone-dream:adopt-desktop-auth", listener);

    await expect(adoptBrowserAuthSession(validSession)).resolves.toBeUndefined();

    expect(authMock.getUser).toHaveBeenCalledWith("header.payload.signature");
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("drone-dream:adopt-desktop-auth", listener);
  });

  it("fails closed when Supabase rejects the browser session", async () => {
    authMock.getUser.mockResolvedValue({
      data: { user: null }, error: { message: "Session is no longer valid." },
    });

    await expect(adoptBrowserAuthSession({
      ...validSession,
      accessToken: "expired-token",
    })).rejects.toThrow("Session is no longer valid.");
  });

  it("rejects a session issued for another desktop edition before adoption", async () => {
    authMock.getUser.mockResolvedValue({ data: { user: {} }, error: null });

    await expect(adoptBrowserAuthSession({
      ...validSession,
      editionId: "sim",
      authClientId: "dronedream-desktop-sim",
    })).rejects.toThrow("different DroneDream edition");

    expect(authMock.getUser).not.toHaveBeenCalled();
  });
});
