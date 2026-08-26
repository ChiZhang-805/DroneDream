import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  account: null as null | { id: string; email: string; displayName: string; avatarUrl: null },
  completeDesktopBrowserSignIn: vi.fn(),
  cancelDesktopBrowserSignIn: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("../desktop/bridge", () => ({
  isDesktopRuntime: () => true,
}));
vi.mock("../features/auth/AuthContext", () => ({
  useAuthOrLocal: () => ({
    account: mocks.account,
    configured: true,
    signOut: mocks.signOut,
  }),
}));
vi.mock("../features/auth/desktopBrowserSignIn", () => ({
  completeDesktopBrowserSignIn: mocks.completeDesktopBrowserSignIn,
  cancelDesktopBrowserSignIn: mocks.cancelDesktopBrowserSignIn,
}));
vi.mock("../features/auth/supabaseClient", () => ({
  browserAuthConfiguration: () => ({
    supabaseUrl: "https://account.example.invalid",
    publishableKey: "public-test-key",
  }),
}));

import { FieldAuthControl } from "../field/FieldAuthControl";

describe("FieldAuthControl", () => {
  beforeEach(() => {
    mocks.account = null;
    vi.clearAllMocks();
    mocks.completeDesktopBrowserSignIn.mockResolvedValue(undefined);
    mocks.cancelDesktopBrowserSignIn.mockResolvedValue(false);
    mocks.signOut.mockResolvedValue(undefined);
  });

  it("starts one explicit Field browser transaction without granting authority", async () => {
    const { container } = render(<FieldAuthControl locale="en" />);

    fireEvent.click(screen.getByRole("button", {
      name: "Sign in to DroneDream · FIELD",
    }));

    await waitFor(() => expect(mocks.completeDesktopBrowserSignIn).toHaveBeenCalledWith(
      "en",
      expect.objectContaining({
        signal: expect.any(AbortSignal),
        restoreFromVault: false,
        onAdopting: expect.any(Function),
      }),
    ));
    expect(container.firstChild).toHaveAttribute("data-authority", "false");
  });

  it("shows a failure when the shared Field transaction cannot adopt", async () => {
    mocks.completeDesktopBrowserSignIn.mockRejectedValueOnce(
      new Error("The browser session belongs to a different DroneDream edition."),
    );
    render(<FieldAuthControl locale="zh-CN" />);

    fireEvent.click(screen.getByRole("button", { name: "登录 DroneDream · FIELD" }));

    await waitFor(() => expect(mocks.completeDesktopBrowserSignIn).toHaveBeenCalledTimes(1));
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
    expect(mocks.completeDesktopBrowserSignIn).not.toHaveBeenCalled();
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

    await waitFor(() => expect(mocks.completeDesktopBrowserSignIn).toHaveBeenCalledOnce());
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
    expect(mocks.completeDesktopBrowserSignIn).not.toHaveBeenCalled();
  });
});
