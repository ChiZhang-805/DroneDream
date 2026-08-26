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
  BrowserAuthAdoptionError,
  clearBrowserAuthSessionRefresh,
  shouldClearBrowserAuthVaultAfterAdoptionError,
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
    vi.unstubAllEnvs();
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
      data: { user: null },
      error: {
        name: "AuthApiError",
        message: "Session is no longer valid.",
        status: 401,
      },
    });

    const error = await adoptBrowserAuthSession({
      ...validSession,
      accessToken: "expired-token",
    }).then(() => null, (reason: unknown) => reason);

    expect(error).toMatchObject({
      failure: "credential-rejected",
      message: "Session is no longer valid.",
    });
    expect(shouldClearBrowserAuthVaultAfterAdoptionError(error)).toBe(true);
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

    const error = await adoptBrowserAuthSession({
      ...validSession,
      editionId: "sim",
      authClientId: "dronedream-desktop-sim",
    }).then(() => null, (reason: unknown) => reason);

    expect(error).toMatchObject({
      failure: "session-binding",
      message: "The browser session belongs to a different DroneDream edition.",
    });
    expect(shouldClearBrowserAuthVaultAfterAdoptionError(error)).toBe(true);
    expect(authMock.getUser).not.toHaveBeenCalled();
  });

  it.each(["future-edition", "__proto__"])(
    "fails closed for unknown non-empty build edition %s without clearing a valid vault",
    async (configuredEdition) => {
      vi.stubEnv("VITE_DRONEDREAM_EDITION", configuredEdition);

      const error = await adoptBrowserAuthSession(validSession)
        .then(() => null, (reason: unknown) => reason);

      expect(error).toMatchObject({
        failure: "configuration",
        message: expect.stringContaining(`"${configuredEdition}" is unsupported`),
      });
      expect(shouldClearBrowserAuthVaultAfterAdoptionError(error)).toBe(false);
      expect(authMock.getUser).not.toHaveBeenCalled();
    },
  );

  it("defaults a missing build edition to Universal", async () => {
    vi.stubEnv("VITE_DRONEDREAM_EDITION", "");
    const user = { id: "universal-user", email: "pilot@example.com", user_metadata: {} };
    authMock.getUser.mockResolvedValue({ data: { user }, error: null });

    await expect(adoptBrowserAuthSession(validSession)).resolves.toBeUndefined();

    expect(authMock.getUser).toHaveBeenCalledWith("header.payload.signature");
  });

  it.each([401, 403])(
    "marks an explicit HTTP %s rejection as unrecoverable",
    async (status) => {
      authMock.getUser.mockResolvedValue({
        data: { user: null },
        error: { name: "AuthApiError", message: `Rejected with ${status}.`, status },
      });

      const error = await adoptBrowserAuthSession(validSession)
        .then(() => null, (reason: unknown) => reason);

      expect(error).toMatchObject({ failure: "credential-rejected" });
      expect(shouldClearBrowserAuthVaultAfterAdoptionError(error)).toBe(true);
    },
  );

  it.each([
    ["network failure", { name: "AuthRetryableFetchError", message: "Failed to fetch", status: 0 }],
    ["timeout", { name: "TimeoutError", message: "The request timed out." }],
    ["HTTP 429", { name: "AuthApiError", message: "Too many requests.", status: 429 }],
    ["HTTP 503", { name: "AuthRetryableFetchError", message: "Service unavailable.", status: 503 }],
  ])("preserves the vault after a transient %s", async (_label, remoteError) => {
    authMock.getUser.mockResolvedValue({
      data: { user: null },
      error: remoteError,
    });

    const error = await adoptBrowserAuthSession(validSession)
      .then(() => null, (reason: unknown) => reason);

    expect(error).toBeInstanceOf(BrowserAuthAdoptionError);
    expect(error).toMatchObject({ failure: "transient" });
    expect(shouldClearBrowserAuthVaultAfterAdoptionError(error)).toBe(false);
  });

  it("preserves the vault for an unclassified adoption error", async () => {
    authMock.getUser.mockResolvedValue({
      data: { user: null },
      error: { name: "AuthApiError", message: "Unexpected request.", status: 400 },
    });

    const error = await adoptBrowserAuthSession(validSession)
      .then(() => null, (reason: unknown) => reason);

    expect(error).toMatchObject({ failure: "unknown" });
    expect(shouldClearBrowserAuthVaultAfterAdoptionError(error)).toBe(false);
  });

  it("adopts the AGENT browser session for the autonomy desktop edition", async () => {
    vi.stubEnv("VITE_DRONEDREAM_EDITION", "autonomy");
    const user = { id: "agent-user", email: "pilot@example.com", user_metadata: {} };
    authMock.getUser.mockResolvedValue({ data: { user }, error: null });

    await expect(adoptBrowserAuthSession({
      ...validSession,
      editionId: "autonomy",
      authClientId: "dronedream-desktop-autonomy",
    })).resolves.toBeUndefined();

    expect(authMock.getUser).toHaveBeenCalledWith("header.payload.signature");
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
