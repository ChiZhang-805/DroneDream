import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  account: null as null | { id: string; email: string; displayName: string; avatarUrl: null },
  beginBrowserAuth: vi.fn(),
  cancelBrowserAuth: vi.fn(),
  clearBrowserAuthVault: vi.fn(),
  signOut: vi.fn(),
  adoptBrowserAuthSession: vi.fn(),
  activateDesktopAuthSession: vi.fn(),
}));

vi.mock("../desktop/bridge", () => ({
  beginBrowserAuth: mocks.beginBrowserAuth,
  cancelBrowserAuth: mocks.cancelBrowserAuth,
  clearBrowserAuthVault: mocks.clearBrowserAuthVault,
  isDesktopRuntime: () => true,
}));
vi.mock("../features/auth/AuthContext", () => ({
  useAuthOrLocal: () => ({
    account: mocks.account,
    configured: true,
    signOut: mocks.signOut,
  }),
}));
vi.mock("../features/auth/browserAuth", () => ({
  adoptBrowserAuthSession: mocks.adoptBrowserAuthSession,
}));
vi.mock("../features/auth/desktopAuthActivation", () => ({
  activateDesktopAuthSession: mocks.activateDesktopAuthSession,
}));
vi.mock("../features/auth/supabaseClient", () => ({
  browserAuthConfiguration: () => ({
    supabaseUrl: "https://account.example.invalid",
    publishableKey: "public-test-key",
  }),
}));

import { FieldAuthControl } from "../field/FieldAuthControl";

const FIELD_SESSION = {
  protocolVersion: "desktop-browser-auth-pkce-v1",
  editionId: "field",
  authClientId: "dronedream-desktop-field",
  accessToken: "redacted-access",
  attemptIdHash: "a".repeat(64),
  stateHash: "b".repeat(64),
  subjectHash: "c".repeat(64),
  issuedAt: "2026-08-06T00:00:00Z",
  completedAt: "2026-08-06T00:00:01Z",
} as const;

describe("FieldAuthControl", () => {
  beforeEach(() => {
    mocks.account = null;
    vi.clearAllMocks();
    mocks.beginBrowserAuth.mockResolvedValue(FIELD_SESSION);
    mocks.adoptBrowserAuthSession.mockResolvedValue(undefined);
    mocks.cancelBrowserAuth.mockResolvedValue(true);
    mocks.clearBrowserAuthVault.mockResolvedValue(true);
    mocks.signOut.mockResolvedValue(undefined);
  });

  it("starts one explicit Field browser transaction without granting authority", async () => {
    const { container } = render(<FieldAuthControl locale="en" />);

    fireEvent.click(screen.getByRole("button", {
      name: "Sign in to DroneDream · FIELD",
    }));

    await waitFor(() => expect(mocks.adoptBrowserAuthSession).toHaveBeenCalledWith(
      FIELD_SESSION,
    ));
    expect(mocks.beginBrowserAuth).toHaveBeenCalledTimes(1);
    expect(mocks.beginBrowserAuth).toHaveBeenCalledWith({ locale: "en" });
    expect(mocks.activateDesktopAuthSession).toHaveBeenCalledTimes(1);
    expect(container.firstChild).toHaveAttribute("data-authority", "false");
  });

  it("clears only the Field vault when session adoption fails", async () => {
    mocks.adoptBrowserAuthSession.mockRejectedValueOnce(
      new Error("The browser session belongs to a different DroneDream edition."),
    );
    render(<FieldAuthControl locale="zh-CN" />);

    fireEvent.click(screen.getByRole("button", { name: "登录 DroneDream · FIELD" }));

    await waitFor(() => expect(mocks.clearBrowserAuthVault).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("alert")).toHaveTextContent("Field 登录未完成。");
  });

  it("uses the edition-local sign-out path for an active Field account", async () => {
    mocks.account = {
      id: "field-user",
      email: "field@example.invalid",
      displayName: "Field operator",
      avatarUrl: null,
    };
    render(<FieldAuthControl locale="en" />);

    fireEvent.click(screen.getByRole("button", {
      name: "Sign out of DroneDream · FIELD",
    }));

    await waitFor(() => expect(mocks.signOut).toHaveBeenCalledTimes(1));
    expect(mocks.beginBrowserAuth).not.toHaveBeenCalled();
  });

  it("keeps the launcher action disabled until the Field workspace is ready", () => {
    render(
      <FieldAuthControl
        launcher
        launcherReady={false}
        locale="en"
        onAuthenticated={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", {
      name: "Sign in and enter the tuning platform",
    })).toBeDisabled();
  });

  it("enters the launcher only after adopting the Field browser session", async () => {
    const onAuthenticated = vi.fn();
    render(
      <FieldAuthControl
        launcher
        launcherReady
        locale="en"
        onAuthenticated={onAuthenticated}
      />,
    );

    fireEvent.click(screen.getByRole("button", {
      name: "Sign in and enter the tuning platform",
    }));

    await waitFor(() => expect(mocks.adoptBrowserAuthSession).toHaveBeenCalledWith(
      FIELD_SESSION,
    ));
    expect(onAuthenticated).toHaveBeenCalledTimes(1);
  });

  it("lets an existing Field account enter without signing out", () => {
    mocks.account = {
      id: "field-user",
      email: "field@example.invalid",
      displayName: "Field operator",
      avatarUrl: null,
    };
    const onAuthenticated = vi.fn();
    render(
      <FieldAuthControl
        launcher
        launcherReady
        locale="en"
        onAuthenticated={onAuthenticated}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Enter the tuning platform" }));

    expect(onAuthenticated).toHaveBeenCalledTimes(1);
    expect(mocks.signOut).not.toHaveBeenCalled();
    expect(mocks.beginBrowserAuth).not.toHaveBeenCalled();
  });
});
