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

describe("browser auth session adoption", () => {
  beforeEach(() => {
    authMock.setSession.mockReset();
  });

  it("adopts the exact access and refresh token pair once", async () => {
    authMock.setSession.mockResolvedValue({ error: null });

    await expect(adoptBrowserAuthSession({
      accessToken: "header.payload.signature",
      refreshToken: "refresh-token-value",
    })).resolves.toBeUndefined();

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
      accessToken: "expired-token",
      refreshToken: "expired-refresh-token",
    })).rejects.toThrow("Session is no longer valid.");
  });
});
