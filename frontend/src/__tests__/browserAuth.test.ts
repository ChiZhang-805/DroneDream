import { beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  getUser: vi.fn(),
}));
const bridgeMock = vi.hoisted(() => ({
  restoreBrowserAuthVault: vi.fn(),
}));

vi.mock("../desktop/bridge", () => ({
  restoreBrowserAuthVault: bridgeMock.restoreBrowserAuthVault,
}));

vi.mock("../features/auth/supabaseClient", () => ({
  supabaseClient: {
    auth: {
      getUser: authMock.getUser,
    },
  },
}));

import {
  adoptBrowserAuthSession,
  clearBrowserAuthSessionRefresh,
} from "../features/auth/browserAuth";

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
    bridgeMock.restoreBrowserAuthVault.mockReset();
    clearBrowserAuthSessionRefresh();
    vi.useRealTimers();
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

  it("does not publish an account after adoption is cancelled", async () => {
    let resolveUser!: (value: {
      data: { user: { id: string } };
      error: null;
    }) => void;
    authMock.getUser.mockReturnValue(new Promise((resolve) => {
      resolveUser = resolve;
    }));
    const controller = new AbortController();
    const listener = vi.fn();
    window.addEventListener("drone-dream:adopt-desktop-auth", listener);

    const adoption = adoptBrowserAuthSession(validSession, {
      signal: controller.signal,
    });
    controller.abort();
    resolveUser({ data: { user: { id: "user-1" } }, error: null });

    await expect(adoption).rejects.toThrow("cancelled");
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener("drone-dream:adopt-desktop-auth", listener);
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

  it("retries a transient native vault refresh before returning to sign-in", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-05T08:00:00Z"));
    const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 120 }));
    const accessToken = `header.${payload}.signature`;
    const session = { ...validSession, accessToken };
    const user = { id: "user-1", email: "pilot@example.com", user_metadata: {} };
    authMock.getUser.mockResolvedValue({ data: { user }, error: null });
    bridgeMock.restoreBrowserAuthVault
      .mockRejectedValueOnce(new Error("temporary native bridge failure"))
      .mockResolvedValueOnce(session);

    await adoptBrowserAuthSession(session);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(bridgeMock.restoreBrowserAuthVault).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(bridgeMock.restoreBrowserAuthVault).toHaveBeenCalledTimes(2);

    clearBrowserAuthSessionRefresh();
    vi.useRealTimers();
  });
});
