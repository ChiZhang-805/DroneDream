import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  beginBrowserAuth,
  clearBrowserAuthVault,
  restoreBrowserAuthVault,
} from "../desktop/bridge";
import { adoptBrowserAuthSession } from "../features/auth/browserAuth";
import { completeDesktopBrowserSignIn } from "../features/auth/desktopBrowserSignIn";
import { activateDesktopAuthSession } from "../features/auth/desktopAuthActivation";

vi.mock("../desktop/bridge", () => ({
  beginBrowserAuth: vi.fn(),
  clearBrowserAuthVault: vi.fn(),
  restoreBrowserAuthVault: vi.fn(),
}));
vi.mock("../features/auth/browserAuth", () => ({
  adoptBrowserAuthSession: vi.fn(),
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

describe("desktop browser sign-in transaction", () => {
  beforeEach(() => {
    vi.mocked(beginBrowserAuth).mockReset();
    vi.mocked(clearBrowserAuthVault).mockReset();
    vi.mocked(restoreBrowserAuthVault).mockReset();
    vi.mocked(adoptBrowserAuthSession).mockReset();
    vi.mocked(activateDesktopAuthSession).mockReset();
  });

  it("adopts the exact edition session restored from the credential vault", async () => {
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockResolvedValue(undefined);

    await completeDesktopBrowserSignIn("en");

    expect(activateDesktopAuthSession).toHaveBeenCalledOnce();
    expect(beginBrowserAuth).not.toHaveBeenCalled();
    expect(adoptBrowserAuthSession).toHaveBeenCalledWith(SESSION);
    expect(clearBrowserAuthVault).not.toHaveBeenCalled();
  });

  it("opens PKCE in the browser only when no restorable session exists", async () => {
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(null);
    vi.mocked(beginBrowserAuth).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockResolvedValue(undefined);

    await completeDesktopBrowserSignIn("zh-CN");

    expect(beginBrowserAuth).toHaveBeenCalledWith({ locale: "zh-CN" });
    expect(adoptBrowserAuthSession).toHaveBeenCalledWith(SESSION);
  });

  it("removes only the unusable edition grant when WebView adoption fails", async () => {
    vi.mocked(restoreBrowserAuthVault).mockResolvedValue(null);
    vi.mocked(beginBrowserAuth).mockResolvedValue(SESSION);
    vi.mocked(adoptBrowserAuthSession).mockRejectedValue(new Error("invalid session"));
    vi.mocked(clearBrowserAuthVault).mockResolvedValue(true);

    await expect(completeDesktopBrowserSignIn("en")).rejects.toThrow("invalid session");
    expect(clearBrowserAuthVault).toHaveBeenCalledOnce();
  });
});
