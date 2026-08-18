import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createRef } from "react";
import type { ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountDialog, AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";

const authMock = vi.hoisted(() => ({
  signInWithPassword: vi.fn(async () => undefined),
  sendRegistrationCode: vi.fn(async () => undefined),
  verifyRegistrationCode: vi.fn(async () => undefined),
}));

const desktopSignInMock = vi.hoisted(() => ({
  complete: vi.fn(async () => undefined),
  cancel: vi.fn(async (controller: AbortController) => {
    controller.abort();
    return false;
  }),
}));

vi.mock("../features/auth/desktopBrowserSignIn", () => ({
  cancelDesktopBrowserSignIn: desktopSignInMock.cancel,
  completeDesktopBrowserSignIn: desktopSignInMock.complete,
}));

vi.mock("../features/auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => ({
    configured: true,
    loading: false,
    account: null,
    googleEnabled: false,
    appleEnabled: false,
    signInWithPassword: authMock.signInWithPassword,
    sendRegistrationCode: authMock.sendRegistrationCode,
    verifyRegistrationCode: authMock.verifyRegistrationCode,
    signInWithProvider: vi.fn(),
    updateDisplayName: vi.fn(),
    updateAvatar: vi.fn(),
    signOut: vi.fn(),
  }),
}));

function renderWorkspace() {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <AppShell />,
        children: [{ path: "assistant", element: <div>Assistant workspace</div> }],
      },
    ],
    { initialEntries: ["/assistant"] },
  );
  const page = render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { ...page, router };
}

describe("workspace email and password authentication", () => {
  afterEach(() => {
    authMock.signInWithPassword.mockClear();
    authMock.sendRegistrationCode.mockClear();
    authMock.verifyRegistrationCode.mockClear();
    desktopSignInMock.complete.mockClear();
    desktopSignInMock.cancel.mockClear();
    delete window.__TAURI__;
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("uses a password for sign-in and exposes the complete registration form immediately", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    const { router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    const signInDialog = screen.getByRole("dialog", {
      name: "Sign in to DroneDream",
    });
    expect(within(signInDialog).queryByText(/one email as one account/i))
      .not.toBeInTheDocument();
    fireEvent.change(within(signInDialog).getByLabelText("Email address"), {
      target: { value: "pilot@example.com" },
    });
    fireEvent.change(within(signInDialog).getByLabelText("Password"), {
      target: { value: "correct-horse" },
    });
    fireEvent.click(within(signInDialog).getByRole("button", { name: "Sign in" }));
    await waitFor(() => {
      expect(authMock.signInWithPassword).toHaveBeenCalledWith(
        "pilot@example.com",
        "correct-horse",
      );
    });

    fireEvent.click(
      within(signInDialog).getByRole("button", {
        name: "New to DroneDream? Register now",
      }),
    );
    const registerDialog = screen.getByRole("dialog", { name: "Create account" });
    expect(within(registerDialog).getByLabelText("Verification code")).toBeVisible();
    expect(within(registerDialog).getByLabelText("Confirm password")).toBeVisible();

    fireEvent.change(within(registerDialog).getByLabelText("Email address"), {
      target: { value: "new@example.com" },
    });
    fireEvent.change(within(registerDialog).getByLabelText("Password"), {
      target: { value: "new-password" },
    });
    fireEvent.change(within(registerDialog).getByLabelText("Confirm password"), {
      target: { value: "new-password" },
    });
    fireEvent.click(
      within(registerDialog).getByRole("button", { name: "Send code" }),
    );
    await waitFor(() => {
      expect(authMock.sendRegistrationCode).toHaveBeenCalledWith(
        "new@example.com",
      );
    });

    fireEvent.change(within(registerDialog).getByLabelText("Verification code"), {
      target: { value: "123456" },
    });
    fireEvent.click(
      within(registerDialog).getByRole("button", { name: "Create account" }),
    );
    await waitFor(() => {
      expect(authMock.verifyRegistrationCode).toHaveBeenCalledWith(
        "new@example.com",
        "123456",
        "new-password",
      );
    });

    router.dispose();
  });

  it("uses only the edition-bound browser flow in the desktop account dialog", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    let finishSignIn: (() => void) | undefined;
    desktopSignInMock.complete.mockImplementationOnce(() => new Promise<undefined>((resolve) => {
      finishSignIn = () => resolve(undefined);
    }));

    render(
      <I18nProvider>
        <AccountDialog
          closeRef={createRef<HTMLButtonElement>()}
          required
          edition="sim"
          desktopBrowserAuthReady
          onClose={vi.fn()}
        />
      </I18nProvider>,
    );

    const dialog = screen.getByRole("dialog", { name: "Sign in to DroneDream" });
    expect(within(dialog).queryByLabelText("Email address")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Password")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", {
      name: "Continue securely in browser",
    }));
    await waitFor(() => {
      expect(desktopSignInMock.complete).toHaveBeenCalledWith("en", {
        signal: expect.any(AbortSignal),
      });
    });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(desktopSignInMock.cancel).toHaveBeenCalledWith(
        expect.any(AbortController),
      );
    });
    finishSignIn?.();
  });

  it("routes desktop users to Environment before browser authorization", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    const onOpenDesktopSetup = vi.fn();

    render(
      <I18nProvider>
        <AccountDialog
          closeRef={createRef<HTMLButtonElement>()}
          required
          edition="sim"
          onOpenDesktopSetup={onOpenDesktopSetup}
          onClose={vi.fn()}
        />
      </I18nProvider>,
    );

    const dialog = screen.getByRole("dialog", { name: "Sign in to DroneDream" });
    expect(within(dialog).queryByRole("button", {
      name: "Continue securely in browser",
    })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Open Environment" }));
    expect(onOpenDesktopSetup).toHaveBeenCalledOnce();
    expect(desktopSignInMock.complete).not.toHaveBeenCalled();
  });
});
