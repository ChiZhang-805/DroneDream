import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LauncherAccountForm } from "../components/LauncherAccountForm";

const auth = vi.hoisted(() => ({ configured: true, signInWithPassword: vi.fn(), sendRegistrationCode: vi.fn(), verifyRegistrationCode: vi.fn(), sendRecoveryCode: vi.fn(), verifyRecoveryCode: vi.fn() }));
vi.mock("../features/auth/AuthContext", () => ({ useAuthOrLocal: () => auth }));
vi.mock("../features/auth/supabaseClient", () => ({ captchaProtectionConfigured: false, turnstileSiteKey: "" }));

describe("LauncherAccountForm", () => {
  beforeEach(() => vi.resetAllMocks());
  it("submits real credentials through the account provider and advances only on success", async () => {
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
    fireEvent.submit(container.querySelector("form")!);
    await screen.findByLabelText("邮箱验证码");
    expect(auth.sendRegistrationCode).toHaveBeenCalledWith("new@example.com", undefined);
    expect(done).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("邮箱验证码"), { target: { value: "123456" } });
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(auth.verifyRegistrationCode).toHaveBeenCalledWith("new@example.com", "123456", "test-password");
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

});
