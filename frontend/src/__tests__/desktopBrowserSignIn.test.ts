import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  beginBrowserAuth,
  cancelBrowserAuth,
  clearBrowserAuthVault,
  restoreBrowserAuthVault,
} from "../desktop/bridge";
import {
  adoptBrowserAuthSession,
  shouldClearBrowserAuthVaultAfterAdoptionError,
} from "../features/auth/browserAuth";
import {
  cancelDesktopBrowserSignIn,
  completeDesktopBrowserSignIn,
  restoreDesktopBrowserSession,
} from "../features/auth/desktopBrowserSignIn";
import { activateDesktopAuthSession } from "../features/auth/desktopAuthActivation";

vi.mock("../desktop/bridge", () => ({
  beginBrowserAuth: vi.fn(),
  cancelBrowserAuth: vi.fn(),
  clearBrowserAuthVault: vi.fn(),
  restoreBrowserAuthVault: vi.fn(),
}));
vi.mock("../features/auth/browserAuth", () => ({
  adoptBrowserAuthSession: vi.fn(),
  shouldClearBrowserAuthVaultAfterAdoptionError: vi.fn(),
}));
vi.mock("../features/auth/desktopAuthActivation", () => ({
  activateDesktopAuthSession: vi.fn(),
}));

const SESSION = {
  protocolVersion: "desktop-browser-auth-pkce-v1" as const,
  editionId: "sim" as const,
  authClientId: "dronedream-desktop-sim",
  accessToken: "access-token",
  attemptIdHash: "a".repeat(64),
  stateHash: "b".repeat(64),
  subjectHash: "c".repeat(64),
  issuedAt: "2026-08-18T00:00:00.000Z",
  completedAt: "2026-08-18T00:00:01.000Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("desktop browser sign-in transaction", () => {
  beforeEach(() => {
    vi.mocked(beginBrowserAuth).mockReset();
    vi.mocked(cancelBrowserAuth).mockReset();
    vi.mocked(clearBrowserAuthVault).mockReset();
    vi.mocked(clearBrowserAuthVault).mockResolvedValue(true);
    vi.mocked(restoreBrowserAuthVault).mockReset();
    vi.mocked(adoptBrowserAuthSession).mockReset();
    vi.mocked(shouldClearBrowserAuthVaultAfterAdoptionError).mockReset();
    vi.mocked(shouldClearBrowserAuthVaultAfterAdoptionError).mockReturnValue(false);
    vi.mocked(activateDesktopAuthSession).mockReset();
  });

  it("requires a fresh browser transaction by default after every app launch", async () => {
    vi.mocked(beginBrowserAuth).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockResolvedValue(undefined);

    await completeDesktopBrowserSignIn("en");

    expect(activateDesktopAuthSession).toHaveBeenCalledOnce();
    expect(clearBrowserAuthVault).toHaveBeenCalledOnce();
    expect(restoreBrowserAuthVault).not.toHaveBeenCalled();
    expect(beginBrowserAuth).toHaveBeenCalledWith({ locale: "en" });
    expect(adoptBrowserAuthSession).toHaveBeenCalledWith(SESSION, {
      signal: undefined,
    });
  });

  it("silently restores a saved session without opening the browser", async () => {
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockResolvedValue(undefined);

    await expect(restoreDesktopBrowserSession()).resolves.toBe(true);

    expect(activateDesktopAuthSession).toHaveBeenCalledOnce();
    expect(beginBrowserAuth).not.toHaveBeenCalled();
    expect(adoptBrowserAuthSession).toHaveBeenCalledWith(SESSION, {
      signal: undefined,
    });
  });

  it("leaves browser sign-in idle when no saved session exists", async () => {
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(null);

    await expect(restoreDesktopBrowserSession()).resolves.toBe(false);

    expect(beginBrowserAuth).not.toHaveBeenCalled();
    expect(adoptBrowserAuthSession).not.toHaveBeenCalled();
  });

  it("opens PKCE in the browser only when no restorable session exists", async () => {
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(null);
    vi.mocked(beginBrowserAuth).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockResolvedValue(undefined);

    await completeDesktopBrowserSignIn("zh-CN");

    expect(beginBrowserAuth).toHaveBeenCalledWith({ locale: "zh-CN" });
    expect(adoptBrowserAuthSession).toHaveBeenCalledWith(SESSION, {
      signal: undefined,
    });
  });

  it("removes only a deterministically unusable edition grant", async () => {
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(null);
    vi.mocked(beginBrowserAuth).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockRejectedValue(new Error("invalid session"));
    vi.mocked(shouldClearBrowserAuthVaultAfterAdoptionError).mockReturnValue(true);
    vi.mocked(clearBrowserAuthVault).mockResolvedValue(true);

    await expect(completeDesktopBrowserSignIn("en")).rejects.toThrow("invalid session");
    expect(clearBrowserAuthVault).toHaveBeenCalledTimes(2);
  });

  it("preserves a fresh browser grant when adoption fails transiently", async () => {
    const transientError = new Error("Service unavailable.");
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(null);
    vi.mocked(beginBrowserAuth).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockRejectedValue(transientError);

    await expect(completeDesktopBrowserSignIn("en")).rejects.toBe(transientError);

    expect(shouldClearBrowserAuthVaultAfterAdoptionError)
      .toHaveBeenCalledWith(transientError);
    expect(clearBrowserAuthVault).toHaveBeenCalledOnce();
  });

  it("clears a deterministically unusable session during silent restoration", async () => {
    const rejectedSession = new Error("The saved session is no longer authorized.");
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockRejectedValue(rejectedSession);
    vi.mocked(shouldClearBrowserAuthVaultAfterAdoptionError).mockReturnValue(true);
    vi.mocked(clearBrowserAuthVault).mockResolvedValue(true);

    await expect(restoreDesktopBrowserSession()).rejects.toBe(rejectedSession);

    expect(clearBrowserAuthVault).toHaveBeenCalledOnce();
    expect(beginBrowserAuth).not.toHaveBeenCalled();
  });

  it("preserves the vault when silent restoration cannot reach the account service", async () => {
    const transientError = new Error("Failed to fetch");
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockRejectedValue(transientError);

    await expect(restoreDesktopBrowserSession()).rejects.toBe(transientError);

    expect(shouldClearBrowserAuthVaultAfterAdoptionError)
      .toHaveBeenCalledWith(transientError);
    expect(clearBrowserAuthVault).not.toHaveBeenCalled();
    expect(beginBrowserAuth).not.toHaveBeenCalled();
  });

  it("cancels vault restoration before any session can be adopted", async () => {
    const restored = deferred<typeof SESSION>();
    vi.mocked(restoreBrowserAuthVault).mockReturnValue(restored.promise);
    vi.mocked(cancelBrowserAuth).mockResolvedValue(false);
    const controller = new AbortController();

    const transaction = completeDesktopBrowserSignIn("en", {
      signal: controller.signal,
      restoreFromVault: true,
    });
    await cancelDesktopBrowserSignIn(controller);

    await expect(transaction).rejects.toThrow("cancelled");
    expect(cancelBrowserAuth).toHaveBeenCalledOnce();
    expect(adoptBrowserAuthSession).not.toHaveBeenCalled();
    expect(clearBrowserAuthVault).not.toHaveBeenCalled();
    restored.resolve(SESSION);
    await Promise.resolve();
    expect(adoptBrowserAuthSession).not.toHaveBeenCalled();
  });

  it("lets cancellation win while WebView adoption is pending", async () => {
    const adoption = deferred<void>();
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockReturnValue(adoption.promise);
    vi.mocked(cancelBrowserAuth).mockResolvedValue(false);
    const controller = new AbortController();

    const transaction = completeDesktopBrowserSignIn("en", {
      signal: controller.signal,
      restoreFromVault: true,
    });
    await vi.waitFor(() => expect(adoptBrowserAuthSession).toHaveBeenCalledOnce());
    await cancelDesktopBrowserSignIn(controller);

    await expect(transaction).rejects.toThrow("cancelled");
    expect(clearBrowserAuthVault).not.toHaveBeenCalled();
    adoption.resolve();
    await Promise.resolve();
  });

  it("cancels a pending native browser flow without waiting for its timeout", async () => {
    const browser = deferred<typeof SESSION>();
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(null);
    vi.mocked(beginBrowserAuth).mockReturnValue(browser.promise);
    vi.mocked(cancelBrowserAuth).mockResolvedValue(true);
    const controller = new AbortController();

    const transaction = completeDesktopBrowserSignIn("zh-CN", {
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(beginBrowserAuth).toHaveBeenCalledOnce());
    await cancelDesktopBrowserSignIn(controller);

    await expect(transaction).rejects.toThrow("cancelled");
    expect(adoptBrowserAuthSession).not.toHaveBeenCalled();
    browser.resolve(SESSION);
    await Promise.resolve();
    expect(adoptBrowserAuthSession).not.toHaveBeenCalled();
  });

  it("supports a fresh edition transaction without restoring another session", async () => {
    vi.mocked(beginBrowserAuth).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockResolvedValue(undefined);

    await completeDesktopBrowserSignIn("en", { restoreFromVault: false });

    expect(restoreBrowserAuthVault).not.toHaveBeenCalled();
    expect(clearBrowserAuthVault).toHaveBeenCalledOnce();
    expect(beginBrowserAuth).toHaveBeenCalledOnce();
  });
});
