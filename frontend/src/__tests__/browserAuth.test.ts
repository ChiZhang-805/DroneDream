import { beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  setSession: vi.fn(),
}));

vi.mock("../features/auth/supabaseClient", () => ({
  supabaseClient: {
    auth: {
      setSession: authMock.setSession,
    },
  },
}));

import { adoptBrowserAuthSession } from "../features/auth/browserAuth";

const validSession = {
  protocolVersion: "desktop-browser-auth-pkce-v1" as const,
  editionId: "universal" as const,
  authClientId: "dronedream-desktop-universal",
  accessToken: "header.payload.signature",
  refreshToken: "refresh-token-value",
  attemptIdHash: "a".repeat(64),
  stateHash: "b".repeat(64),
  subjectHash: "c".repeat(64),
  issuedAt: "2026-08-05T08:00:00Z",
  completedAt: "2026-08-05T08:00:01Z",
};

describe("browser auth session adoption", () => {
  beforeEach(() => {
    authMock.setSession.mockReset();
  });

  it("adopts the exact access and refresh token pair once", async () => {
    authMock.setSession.mockResolvedValue({ error: null });

    await expect(adoptBrowserAuthSession(validSession)).resolves.toBeUndefined();

    expect(authMock.setSession).toHaveBeenCalledTimes(1);
    expect(authMock.setSession).toHaveBeenCalledWith({
      access_token: "header.payload.signature",
      refresh_token: "refresh-token-value",
    });
  });

  it("fails closed when Supabase rejects the browser session", async () => {
    authMock.setSession.mockResolvedValue({
      error: { message: "Session is no longer valid." },
    });

    await expect(adoptBrowserAuthSession({
      ...validSession,
      accessToken: "expired-token",
      refreshToken: "expired-refresh-token",
    })).rejects.toThrow("Session is no longer valid.");
  });

  it("rejects a session issued for another desktop edition before adoption", async () => {
    authMock.setSession.mockResolvedValue({ error: null });

    await expect(adoptBrowserAuthSession({
      ...validSession,
      editionId: "sim",
      authClientId: "dronedream-desktop-sim",
    })).rejects.toThrow("different DroneDream edition");

    expect(authMock.setSession).not.toHaveBeenCalled();
  });
});
