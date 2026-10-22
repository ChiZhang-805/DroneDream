import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LauncherAccountForm } from "../components/LauncherAccountForm";

const auth = vi.hoisted(() => ({ configured: true, signInWithPassword: vi.fn(), sendRegistrationCode: vi.fn(), verifyRegistrationCode: vi.fn(), sendRecoveryCode: vi.fn(), verifyRecoveryCode: vi.fn(), signInWithProvider: vi.fn() }));
const social = vi.hoisted(() => ({
  google: true,
  github: true,
  slack: true,
  configuration: { supabaseUrl: "https://account.example.test", publishableKey: "public-test-key" } as null | { supabaseUrl: string; publishableKey: string },
  complete: vi.fn(),
  cancel: vi.fn(async (controller: AbortController) => { controller.abort(); return true; }),
}));
vi.mock("../features/auth/AuthContext", () => ({ useAuthOrLocal: () => auth }));
vi.mock("../features/auth/supabaseClient", () => ({
  captchaProtectionConfigured: false,
  turnstileSiteKey: "",
  get googleAuthEnabled() { return social.google; },
  get githubAuthEnabled() { return social.github; },
  get slackAuthEnabled() { return social.slack; },
  browserAuthConfiguration: () => social.configuration,
}));
vi.mock("../features/auth/desktopBrowserSignIn", () => ({
  completeDesktopBrowserSignIn: social.complete,
  cancelDesktopBrowserSignIn: social.cancel,
}));

describe("LauncherAccountForm", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    auth.configured = true;
    social.google = true;
    social.github = true;
    social.slack = true;
    social.configuration = { supabaseUrl: "https://account.example.test", publishableKey: "public-test-key" };
    social.cancel.mockImplementation(async (controller) => { controller.abort(); return true; });
  });
  it("submits the entered credentials through the account provider and advances only on success", async () => {
    const done = vi.fn();
    auth.signInWithPassword.mockRejectedValueOnce(new Error("invalid credentials"));
    const { container } = render(<LauncherAccountForm locale="en" onAuthenticated={done} />);
    const message = container.querySelector(".launcher-auth-message");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "pilot@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-password" } });
    fireEvent.submit(container.querySelector("form")!);
    await screen.findByRole("alert");
    expect(done).not.toHaveBeenCalled();
    expect(container.querySelector(".launcher-auth-message")).toBe(message);
    expect(auth.signInWithPassword).toHaveBeenCalledWith("pilot@example.com", "test-password", undefined);
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
  });
  it("requires the emailed code before completing registration", async () => {
    const done = vi.fn();
    const { container } = render(<LauncherAccountForm locale="zh-CN" onAuthenticated={done} />);
    fireEvent.click(screen.getByRole("tab", { name: "注册" }));
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "test-password" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "test-password" } });
    expect(screen.getByLabelText("邮箱验证码")).toBeVisible();
    expect(screen.getByRole("button", { name: "完成注册" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));
    await waitFor(() => expect(auth.sendRegistrationCode).toHaveBeenCalledWith("new@example.com", undefined));
    await screen.findByRole("button", { name: "重新发送" });
    expect(screen.getByLabelText("密码")).toBeVisible();
    expect(screen.getByLabelText("确认密码")).toBeVisible();
    expect(done).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("邮箱验证码"), { target: { value: "123456" } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(auth.verifyRegistrationCode).toHaveBeenCalledWith("new@example.com", "123456", "test-password");
  });
  it("rejects mismatched passwords and invalidates the code when the email changes", async () => {
    const done = vi.fn();
    const { container } = render(<LauncherAccountForm locale="zh-CN" onAuthenticated={done} />);
    fireEvent.click(screen.getByRole("tab", { name: "注册" }));
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "test-password" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "different-password" } });
    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));
    await screen.findByRole("button", { name: "重新发送" });
    fireEvent.change(screen.getByLabelText("邮箱验证码"), { target: { value: "123456" } });
    fireEvent.submit(container.querySelector("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("两次输入的密码不一致。");
    expect(auth.verifyRegistrationCode).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "test-password" } });
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "other@example.com" } });
    expect(screen.getByLabelText("邮箱验证码")).toHaveValue("");
    fireEvent.submit(container.querySelector("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("请先发送邮箱验证码。");
    expect(auth.verifyRegistrationCode).not.toHaveBeenCalled();
  });
  it("recovers an existing account with an emailed code and a new password", async () => {
    const done = vi.fn();
    const { container } = render(<LauncherAccountForm locale="en" onAuthenticated={done} />);
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "pilot@example.com" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-password" } });
    fireEvent.submit(container.querySelector("form")!);
    await screen.findByLabelText("Email code");
    expect(auth.sendRecoveryCode).toHaveBeenCalledWith("pilot@example.com", undefined);
    expect(auth.sendRegistrationCode).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "654321" } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(auth.verifyRecoveryCode).toHaveBeenCalledWith("pilot@example.com", "654321", "new-password");
  });

  it.each([
    ["Google", "google"],
    ["GitHub", "github"],
    ["Slack", "slack_oidc"],
  ])("completes %s sign-in only after the native session has been adopted", async (label, provider) => {
    let finish!: () => void;
    social.complete.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    const done = vi.fn();
    render(<LauncherAccountForm locale="en" onAuthenticated={done} />);
    fireEvent.click(screen.getByRole("button", { name: `Continue with ${label}` }));
    expect(social.complete).toHaveBeenCalledWith("en", expect.objectContaining({
      provider,
      signal: expect.any(AbortSignal),
      onAdopting: expect.any(Function),
    }));
    expect(done).not.toHaveBeenCalled();
    expect(auth.signInWithProvider).not.toHaveBeenCalled();
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Email")).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Create account" })).toBeDisabled();
    for (const name of ["Google", "GitHub", "Slack"]) {
      expect(screen.getByRole("button", { name: `Continue with ${name}` })).toBeDisabled();
    }
    fireEvent.click(screen.getByRole("button", { name: `Continue with ${label}` }));
    expect(social.complete).toHaveBeenCalledOnce();
    act(() => social.complete.mock.calls[0][1].onAdopting());
    expect(done).not.toHaveBeenCalled();
    await act(async () => finish());
    expect(done).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Email")).toBeEnabled();
  });

  it("shows only providers enabled by the configured account service", () => {
    social.google = false;
    social.slack = false;
    render(<LauncherAccountForm locale="en" />);
    expect(screen.queryByRole("button", { name: "Continue with Google" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue with Slack" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with GitHub" })).toBeEnabled();
  });

  it("does not start a provider transaction when the account service is unavailable", () => {
    auth.configured = false;
    social.configuration = null;
    const done = vi.fn();
    render(<LauncherAccountForm locale="en" onAuthenticated={done} />);
    for (const name of ["Google", "GitHub", "Slack"]) {
      const button = screen.queryByRole("button", { name: `Continue with ${name}` });
      if (button) {
        expect(button).toBeDisabled();
        fireEvent.click(button);
      }
    }
    expect(social.complete).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
  });

  it("keeps failed provider sign-in retryable without displaying its raw error", async () => {
    social.complete.mockRejectedValueOnce(new Error("Rejected native token=not-for-display"));
    const done = vi.fn();
    render(<LauncherAccountForm locale="en" onAuthenticated={done} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent("not-for-display");
    expect(done).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Email")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(social.complete).toHaveBeenCalledTimes(2);
  });

  it("cancels the active provider attempt and ignores a late success", async () => {
    let finish!: () => void;
    social.complete.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    const done = vi.fn();
    render(<LauncherAccountForm locale="en" onAuthenticated={done} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    const signal = social.complete.mock.calls[0][1].signal as AbortSignal;
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    await waitFor(() => expect(social.cancel).toHaveBeenCalledOnce());
    expect(signal.aborted).toBe(true);
    await act(async () => finish());
    expect(done).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Email")).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("cancels a pending provider attempt on unmount without publishing a late callback", async () => {
    let finish!: () => void;
    social.complete.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    const done = vi.fn();
    const page = render(<LauncherAccountForm locale="en" onAuthenticated={done} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with GitHub" }));
    const signal = social.complete.mock.calls[0][1].signal as AbortSignal;
    page.unmount();
    expect(social.cancel).toHaveBeenCalledOnce();
    expect(signal.aborted).toBe(true);
    await act(async () => finish());
    expect(done).not.toHaveBeenCalled();
  });

});
