import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  account: null as null | { id: string; email: string; displayName: string; avatarUrl: null },
  completeDesktopBrowserSignIn: vi.fn(),
  cancelDesktopBrowserSignIn: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("../components/LauncherAccountForm", () => ({ LauncherAccountForm: () => <form aria-label="Software account" /> }));

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

  it("opens the software account form without a browser transaction", () => {
    render(<FieldAuthControl locale="en" />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in to DroneDream · FIELD" }));
    expect(screen.getByRole("form", { name: "Software account" })).toBeInTheDocument();
    expect(mocks.completeDesktopBrowserSignIn).not.toHaveBeenCalled();
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
