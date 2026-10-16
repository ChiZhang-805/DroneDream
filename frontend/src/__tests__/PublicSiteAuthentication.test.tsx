import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { SiteApp } from "../site/SiteApp";

const authMock = vi.hoisted(() => ({
  state: {
    account: null as {
      id: string;
      email: string;
      displayName: string;
      avatarUrl: null;
    } | null,
  },
  signInWithPassword: vi.fn(async (): Promise<void> => undefined),
  sendRegistrationCode: vi.fn(async (): Promise<void> => undefined),
  verifyRegistrationCode: vi.fn(async (): Promise<void> => undefined),
  sendRecoveryCode: vi.fn(async (): Promise<void> => undefined),
  verifyRecoveryCode: vi.fn(async (): Promise<void> => undefined),
  requestPasswordReset: vi.fn(async (): Promise<void> => undefined),
  updatePassword: vi.fn(async (): Promise<void> => undefined),
  signOut: vi.fn(async (): Promise<void> => undefined),
}));

vi.mock("../features/auth/AuthContext", () => ({
  useAuthOrLocal: () => ({
    configured: true,
    loading: false,
    passwordRecovery: false,
    account: authMock.state.account,
    googleEnabled: false,
    appleEnabled: false,
    signInWithPassword: authMock.signInWithPassword,
    sendRegistrationCode: authMock.sendRegistrationCode,
    verifyRegistrationCode: authMock.verifyRegistrationCode,
    sendRecoveryCode: authMock.sendRecoveryCode,
    verifyRecoveryCode: authMock.verifyRecoveryCode,
    requestPasswordReset: authMock.requestPasswordReset,
    updatePassword: authMock.updatePassword,
    signInWithProvider: vi.fn(async () => undefined),
    updateDisplayName: vi.fn(async () => undefined),
    updateAvatar: vi.fn(async () => undefined),
    signOut: authMock.signOut,
  }),
}));

function renderOAuthPage(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  window.history.replaceState(
    null,
    "",
    "/oauth/consent?authorization_id=authorization-1",
  );
  return render(
    <I18nProvider>
      <SiteApp />
    </I18nProvider>,
  );
}

describe("public website account authentication", () => {
  beforeEach(() => {
    window.localStorage.clear();
    authMock.state.account = null;
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline test")));
    [
      authMock.signInWithPassword,
      authMock.sendRegistrationCode,
      authMock.verifyRegistrationCode,
      authMock.sendRecoveryCode,
      authMock.verifyRecoveryCode,
      authMock.requestPasswordReset,
      authMock.updatePassword,
      authMock.signOut,
    ].forEach((mock) => mock.mockClear());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("opens a branded non-closable sign-in page directly for desktop OAuth", async () => {
    const { container } = renderOAuthPage();

    const dialog = await screen.findByRole("dialog", { name: "Sign in" });
    expect(
      container.querySelector('.site-auth-brand [data-brand-edition="universal"]'),
    ).toBeVisible();
    expect(within(dialog).getByLabelText("Email address")).toBeVisible();
    expect(within(dialog).getByLabelText("Password")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Register" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Forgot password" })).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Close account dialog" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in and continue" }))
      .not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Sign in" })).toBeVisible();
    fireEvent.mouseDown(container.querySelector(".site-auth-backdrop") as HTMLElement);
    expect(screen.getByRole("dialog", { name: "Sign in" })).toBeVisible();
  });

  it.each([
    "/oauth/consent",
    "/oauth/consent?authorization_id=bad%20id",
  ])(
    "shows the invalid-request state instead of locking signed-out users behind authentication at %s",
    async (url) => {
      window.history.replaceState(null, "", url);
      const { container } = render(
        <I18nProvider>
          <SiteApp />
        </I18nProvider>,
      );

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "This desktop sign-in request is missing or invalid. Return to the app and try again.",
      );
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(container.querySelector(".site-auth-backdrop")).not.toBeInTheDocument();
      expect(container.querySelector(".site-oauth-consent")).toBeVisible();
    },
  );

  it("registers with email, password confirmation, and a verification code", async () => {
    renderOAuthPage();
    const signInDialog = await screen.findByRole("dialog", { name: "Sign in" });
    fireEvent.click(within(signInDialog).getByRole("button", { name: "Register" }));

    const dialog = screen.getByRole("dialog", { name: "Create account" });
    fireEvent.change(within(dialog).getByLabelText("Email address"), {
      target: { value: "new@example.com" },
    });
    fireEvent.change(within(dialog).getByLabelText("Password"), {
      target: { value: "new-password" },
    });
    fireEvent.change(within(dialog).getByLabelText("Confirm password"), {
      target: { value: "new-password" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send code" }));

    await waitFor(() => {
      expect(authMock.sendRegistrationCode).toHaveBeenCalledWith("new@example.com");
    });
    fireEvent.change(within(dialog).getByLabelText("Verification code"), {
      target: { value: "123456" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(authMock.verifyRegistrationCode).toHaveBeenCalledWith(
        "new@example.com",
        "123456",
        "new-password",
      );
    });
  });

  it("signs in with an emailed verification code", async () => {
    renderOAuthPage();
    const signInDialog = await screen.findByRole("dialog", { name: "Sign in" });
    fireEvent.click(within(signInDialog).getByRole("button", { name: "Forgot password" }));

    const choiceDialog = screen.getByRole("dialog", { name: "Recover account" });
    fireEvent.click(within(choiceDialog).getByRole("button", {
      name: "Sign in with an email code",
    }));

    const dialog = screen.getByRole("dialog", { name: "Email code sign-in" });
    fireEvent.change(within(dialog).getByLabelText("Email address"), {
      target: { value: "pilot@example.com" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send code" }));
    await waitFor(() => {
      expect(authMock.sendRecoveryCode).toHaveBeenCalledWith("pilot@example.com");
    });
    fireEvent.change(within(dialog).getByLabelText("Verification code"), {
      target: { value: "654321" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(authMock.verifyRecoveryCode).toHaveBeenCalledWith(
        "pilot@example.com",
        "654321",
      );
    });
  });

  it("resets the password with an emailed code and signs in", async () => {
    renderOAuthPage();
    const signInDialog = await screen.findByRole("dialog", { name: "Sign in" });
    fireEvent.click(within(signInDialog).getByRole("button", { name: "Forgot password" }));
    fireEvent.click(screen.getByRole("button", {
      name: "Reset password with an email code",
    }));

    const dialog = screen.getByRole("dialog", { name: "Reset password" });
    fireEvent.change(within(dialog).getByLabelText("Email address"), {
      target: { value: "pilot@example.com" },
    });
    fireEvent.change(within(dialog).getByLabelText("Password"), {
      target: { value: "replacement-password" },
    });
    fireEvent.change(within(dialog).getByLabelText("Confirm password"), {
      target: { value: "replacement-password" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send code" }));
    await waitFor(() => {
      expect(authMock.sendRecoveryCode).toHaveBeenCalledWith("pilot@example.com");
    });
    fireEvent.change(within(dialog).getByLabelText("Verification code"), {
      target: { value: "654321" },
    });
    fireEvent.click(within(dialog).getByRole("button", {
      name: "Reset password and sign in",
    }));

    await waitFor(() => {
      expect(authMock.verifyRecoveryCode).toHaveBeenCalledWith(
        "pilot@example.com",
        "654321",
        "replacement-password",
      );
    });
  });

  it("keeps the public authentication page in English when an old Chinese preference exists", async () => {
    renderOAuthPage("zh-CN");

    const dialog = await screen.findByRole("dialog", { name: "Sign in" });
    expect(within(dialog).getByLabelText("Email address")).toBeVisible();
    expect(within(dialog).getByLabelText("Password")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Register" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Forgot password" })).toBeVisible();
    expect(within(dialog).queryByText("邮箱地址")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("忘记密码")).not.toBeInTheDocument();
  });

  it("keeps every public registration and recovery mode in English", async () => {
    renderOAuthPage("zh-CN");

    let dialog = await screen.findByRole("dialog", { name: "Sign in" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Register" }));

    dialog = screen.getByRole("dialog", { name: "Create account" });
    expect(within(dialog).getByLabelText("Email address")).toBeVisible();
    expect(within(dialog).getByLabelText("Password")).toBeVisible();
    expect(within(dialog).getByLabelText("Confirm password")).toBeVisible();
    expect(within(dialog).getByLabelText("Verification code")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Send code" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Back to sign in" })).toBeVisible();

    fireEvent.click(within(dialog).getByRole("button", { name: "Back to sign in" }));
    dialog = screen.getByRole("dialog", { name: "Sign in" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Forgot password" }));

    dialog = screen.getByRole("dialog", { name: "Recover account" });
    expect(within(dialog).getByRole("button", { name: "Sign in with an email code" }))
      .toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Reset password with an email code" }))
      .toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign in with an email code" }));

    dialog = screen.getByRole("dialog", { name: "Email code sign-in" });
    expect(within(dialog).getByLabelText("Email address")).toBeVisible();
    expect(within(dialog).getByLabelText("Verification code")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Sign in" })).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Back to sign in" }));
    fireEvent.click(screen.getByRole("button", { name: "Forgot password" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset password with an email code" }));

    dialog = screen.getByRole("dialog", { name: "Reset password" });
    expect(within(dialog).getByLabelText("Email address")).toBeVisible();
    expect(within(dialog).getByLabelText("Password")).toBeVisible();
    expect(within(dialog).getByLabelText("Confirm password")).toBeVisible();
    expect(within(dialog).getByLabelText("Verification code")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Reset password and sign in" })).toBeVisible();
    expect(dialog).not.toHaveTextContent(
      /创建账号|邮箱地址|确认密码|邮箱验证码|忘记密码|修改密码/u,
    );
  });

  it("replaces provider failures with the public English account error", async () => {
    authMock.signInWithPassword.mockRejectedValueOnce(
      new Error("Invalid login credentials"),
    );
    renderOAuthPage("zh-CN");

    const dialog = await screen.findByRole("dialog", { name: "Sign in" });
    fireEvent.change(within(dialog).getByLabelText("Email address"), {
      target: { value: "pilot@example.com" },
    });
    fireEvent.change(within(dialog).getByLabelText("Password"), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign in" }));

    expect(await within(dialog).findByRole("alert"))
      .toHaveTextContent("The account request could not be completed. Please try again.");
    expect(dialog).not.toHaveTextContent("Invalid login credentials");
  });

  it("keeps the OAuth auth page locked while a temporary session is still pending", async () => {
    let finishVerification: (() => void) | null = null;
    authMock.verifyRecoveryCode.mockImplementationOnce(() => new Promise<void>((resolve) => {
      finishVerification = resolve;
    }));
    const page = renderOAuthPage();

    let dialog = await screen.findByRole("dialog", { name: "Sign in" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Forgot password" }));
    fireEvent.click(screen.getByRole("button", {
      name: "Reset password with an email code",
    }));
    dialog = screen.getByRole("dialog", { name: "Reset password" });
    fireEvent.change(within(dialog).getByLabelText("Email address"), {
      target: { value: "pilot@example.com" },
    });
    fireEvent.change(within(dialog).getByLabelText("Password"), {
      target: { value: "replacement-password" },
    });
    fireEvent.change(within(dialog).getByLabelText("Confirm password"), {
      target: { value: "replacement-password" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send code" }));
    await waitFor(() => expect(authMock.sendRecoveryCode).toHaveBeenCalledOnce());
    fireEvent.change(within(dialog).getByLabelText("Verification code"), {
      target: { value: "654321" },
    });
    fireEvent.click(within(dialog).getByRole("button", {
      name: "Reset password and sign in",
    }));
    await waitFor(() => expect(authMock.verifyRecoveryCode).toHaveBeenCalledOnce());

    authMock.state.account = {
      id: "account-1",
      email: "pilot@example.com",
      displayName: "Pilot",
      avatarUrl: null,
    };
    page.rerender(
      <I18nProvider>
        <SiteApp />
      </I18nProvider>,
    );

    expect(screen.getByRole("dialog", { name: "Reset password" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Close account dialog" }))
      .not.toBeInTheDocument();
    expect(page.container.querySelector(".site-oauth-consent")).not.toBeInTheDocument();

    authMock.state.account = null;
    await act(async () => {
      finishVerification?.();
    });
  });
});
