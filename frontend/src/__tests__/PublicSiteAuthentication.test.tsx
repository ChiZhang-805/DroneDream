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

  it("keeps the Simplified Chinese authentication page free of English field copy", async () => {
    renderOAuthPage("zh-CN");

    const dialog = await screen.findByRole("dialog", { name: "登录" });
    expect(within(dialog).getByLabelText("邮箱地址")).toBeVisible();
    expect(within(dialog).getByLabelText("密码")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "注册" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "忘记密码" })).toBeVisible();
    expect(within(dialog).queryByText("Email address")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Forgot password")).not.toBeInTheDocument();
  });

  it("localizes every Simplified Chinese registration and recovery mode", async () => {
    renderOAuthPage("zh-CN");

    let dialog = await screen.findByRole("dialog", { name: "登录" });
    fireEvent.click(within(dialog).getByRole("button", { name: "注册" }));

    dialog = screen.getByRole("dialog", { name: "创建账号" });
    expect(within(dialog).getByLabelText("邮箱地址")).toBeVisible();
    expect(within(dialog).getByLabelText("密码")).toBeVisible();
    expect(within(dialog).getByLabelText("确认密码")).toBeVisible();
    expect(within(dialog).getByLabelText("邮箱验证码")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "发送验证码" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "返回登录" })).toBeVisible();

    fireEvent.click(within(dialog).getByRole("button", { name: "返回登录" }));
    dialog = screen.getByRole("dialog", { name: "登录" });
    fireEvent.click(within(dialog).getByRole("button", { name: "忘记密码" }));

    dialog = screen.getByRole("dialog", { name: "找回账号" });
    expect(within(dialog).getByRole("button", { name: "使用邮箱验证码登录" }))
      .toBeVisible();
    expect(within(dialog).getByRole("button", { name: "使用邮箱验证码修改密码" }))
      .toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "使用邮箱验证码登录" }));

    dialog = screen.getByRole("dialog", { name: "邮箱验证码登录" });
    expect(within(dialog).getByLabelText("邮箱地址")).toBeVisible();
    expect(within(dialog).getByLabelText("邮箱验证码")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "登录" })).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "返回登录" }));
    fireEvent.click(screen.getByRole("button", { name: "忘记密码" }));
    fireEvent.click(screen.getByRole("button", { name: "使用邮箱验证码修改密码" }));

    dialog = screen.getByRole("dialog", { name: "修改密码" });
    expect(within(dialog).getByLabelText("邮箱地址")).toBeVisible();
    expect(within(dialog).getByLabelText("密码")).toBeVisible();
    expect(within(dialog).getByLabelText("确认密码")).toBeVisible();
    expect(within(dialog).getByLabelText("邮箱验证码")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "修改密码并登录" })).toBeVisible();
    expect(dialog).not.toHaveTextContent(
      /Create account|Email address|Confirm password|Verification code|Forgot password|Reset password/u,
    );
  });

  it("replaces English Supabase failures with a localized Chinese account error", async () => {
    authMock.signInWithPassword.mockRejectedValueOnce(
      new Error("Invalid login credentials"),
    );
    renderOAuthPage("zh-CN");

    const dialog = await screen.findByRole("dialog", { name: "登录" });
    fireEvent.change(within(dialog).getByLabelText("邮箱地址"), {
      target: { value: "pilot@example.com" },
    });
    fireEvent.change(within(dialog).getByLabelText("密码"), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "登录" }));

    expect(await within(dialog).findByRole("alert"))
      .toHaveTextContent("无法完成账号请求，请稍后重试。");
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
