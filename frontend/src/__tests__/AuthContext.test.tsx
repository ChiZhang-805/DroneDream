import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { AuthProvider, useAuth } from "../features/auth/AuthContext";
import {
  activateDesktopAuthSession,
  ADOPT_DESKTOP_AUTH_EVENT,
} from "../features/auth/desktopAuthActivation";

const authMock = vi.hoisted(() => {
  const state = {
    user: {
      id: "user-1",
      email: "pilot.name@example.com",
      user_metadata: {} as Record<string, unknown>,
    },
  };
  const getSession = vi.fn(async () => ({
    data: {
      session: {
        user: state.user,
        access_token: "session-token",
      },
    },
    error: null,
  }));
  let stateChangeCallback: ((event: string, session: unknown) => void) | null = null;
  const onAuthStateChange = vi.fn((callback: (event: string, session: unknown) => void) => {
    stateChangeCallback = callback;
    return {
      data: {
        subscription: { unsubscribe: vi.fn() },
      },
    };
  });
  const uploadAvatar = vi.fn(async () => ({ data: { path: "user-1/avatar.jpg" }, error: null }));
  const removeAvatar = vi.fn(async () => ({ data: [], error: null }));
  const storageFrom = vi.fn(() => ({
    upload: uploadAvatar,
    remove: removeAvatar,
  }));
  return {
    state,
    getSession,
    onAuthStateChange,
    signInWithPassword: vi.fn(async () => ({ data: {}, error: null })),
    signInWithOtp: vi.fn(async () => ({ data: {}, error: null })),
    resetPasswordForEmail: vi.fn(async () => ({ data: {}, error: null })),
    verifyOtp: vi.fn(async () => ({ data: {}, error: null })),
    signOut: vi.fn(async (): Promise<{
      data: Record<string, never>;
      error: Error | null;
    }> => ({ data: {}, error: null })),
    updateUser: vi.fn(async (
      payload: { data?: Record<string, unknown>; password?: string },
    ): Promise<{
      data: { user: typeof state.user };
      error: Error | null;
    }> => {
      if (payload.data) {
        state.user = {
          ...state.user,
          user_metadata: { ...state.user.user_metadata, ...payload.data },
        };
      }
      return { data: { user: state.user }, error: null };
    }),
    uploadAvatar,
    removeAvatar,
    storageFrom,
    unsubscribe: vi.fn(),
    emitAuthStateChange: (event: string, session: unknown) => {
      stateChangeCallback?.(event, session);
    },
  };
});

vi.mock("../features/auth/supabaseClient", () => ({
  appleAuthEnabled: false,
  browserAuthConfiguration: () => ({
    supabaseUrl: "https://accounts.example.test",
    publishableKey: "public-browser-key",
  }),
  cloudAuthConfigured: true,
  googleAuthEnabled: false,
  supabaseClient: {
    auth: {
      getSession: authMock.getSession,
      onAuthStateChange: authMock.onAuthStateChange,
      signInWithPassword: authMock.signInWithPassword,
      signInWithOtp: authMock.signInWithOtp,
      resetPasswordForEmail: authMock.resetPasswordForEmail,
      verifyOtp: authMock.verifyOtp,
      signOut: authMock.signOut,
      updateUser: authMock.updateUser,
    },
    storage: {
      from: authMock.storageFrom,
    },
  },
}));

function AccountProbe() {
  const auth = useAuth();
  const [avatarError, setAvatarError] = useState("");
  const [registrationError, setRegistrationError] = useState("");
  const [recoveryError, setRecoveryError] = useState("");
  return (
    <>
      <output aria-label="username">{auth.account?.displayName ?? ""}</output>
      <output aria-label="email">{auth.account?.email ?? ""}</output>
      <output aria-label="avatar">{auth.account?.avatarUrl ?? ""}</output>
      <output aria-label="avatar-error">{avatarError}</output>
      <output aria-label="registration-error">{registrationError}</output>
      <output aria-label="recovery-error">{recoveryError}</output>
      <output aria-label="password-recovery">{String(auth.passwordRecovery)}</output>
      <button
        type="button"
        onClick={() => void auth.updateDisplayName("Flight Pilot")}
      >
        Rename
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.updateAvatar("data:image/jpeg;base64,ZmFrZS1hdmF0YXI=")
            .catch((error: unknown) => {
              setAvatarError(error instanceof Error ? error.message : String(error));
            })
        }
      >
        Change avatar
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.signInWithPassword("pilot@example.com", "correct-horse")
        }
      >
        Password sign in
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.sendRegistrationCode("new@example.com", "captcha-register")
        }
      >
        Send registration code
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.verifyRegistrationCode(
            "new@example.com",
           "123456",
           "correct-horse",
          ).catch((error: unknown) => {
            setRegistrationError(error instanceof Error ? error.message : String(error));
          })
        }
      >
        Finish registration
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.sendRecoveryCode(
            " existing@example.com ",
            "captcha-recovery",
          )
        }
      >
        Send recovery code
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.verifyRecoveryCode(
            " existing@example.com ",
            " 654321 ",
          )
        }
      >
        Sign in with recovery code
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.verifyRecoveryCode(
            " existing@example.com ",
            " 654321 ",
            "new-recovery-password",
          ).catch((error: unknown) => {
            setRecoveryError(error instanceof Error ? error.message : String(error));
          })
        }
      >
        Reset with recovery code
      </button>
      <button
        type="button"
        onClick={() =>
          void auth.requestPasswordReset("pilot@example.com", "captcha-reset")
        }
      >
        Request password reset
      </button>
      <button
        type="button"
        onClick={() => void auth.updatePassword("new-correct-horse")}
      >
        Update password
      </button>
      <button
        type="button"
        onClick={() => void auth.signOut().catch(() => undefined)}
      >
        Sign out
      </button>
    </>
  );
}

function adoptDesktopAccount(): void {
  window.dispatchEvent(new CustomEvent(ADOPT_DESKTOP_AUTH_EVENT, {
    detail: {
      user: authMock.state.user,
      accessToken: "session-token",
    },
  }));
}

function LoadingHistoryProbe({ history }: { history: boolean[] }) {
  const auth = useAuth();
  history.push(auth.loading);
  return <output aria-label="auth-loading">{String(auth.loading)}</output>;
}

describe("AuthContext account profile", () => {
  afterEach(() => {
    authMock.state.user = {
      id: "user-1",
      email: "pilot.name@example.com",
      user_metadata: {},
    };
    authMock.updateUser.mockClear();
    authMock.uploadAvatar.mockClear();
    authMock.removeAvatar.mockClear();
    authMock.storageFrom.mockClear();
    authMock.getSession.mockClear();
    authMock.onAuthStateChange.mockClear();
    authMock.signInWithPassword.mockClear();
    authMock.signInWithOtp.mockClear();
    authMock.resetPasswordForEmail.mockClear();
    authMock.verifyOtp.mockClear();
    authMock.signOut.mockReset();
    authMock.signOut.mockResolvedValue({ data: {}, error: null });
    authMock.unsubscribe.mockClear();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete window.__TAURI__;
    window.history.replaceState(null, "", "/");
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("uses a local preview identity only in desktop visual-QA mode", async () => {
    vi.stubEnv("VITE_DESKTOP_VISUAL_QA", "true");
    window.__TAURI__ = { core: { invoke: vi.fn() } };

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    expect(await screen.findByLabelText("username"))
      .toHaveTextContent("DroneDream Pilot");
    expect(screen.getByLabelText("email")).toHaveTextContent("pilot@example.com");
    expect(authMock.getSession).not.toHaveBeenCalled();
  });

  it("defaults to the email prefix and lets the user save a custom username", async () => {
    vi.spyOn(Date, "now").mockReturnValue(1_777_777_777_777);
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    expect(await screen.findByLabelText("username"))
      .toHaveTextContent("pilot.name");
    expect(screen.getByLabelText("email"))
      .toHaveTextContent("pilot.name@example.com");

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => {
      expect(screen.getByLabelText("username"))
        .toHaveTextContent("Flight Pilot");
    });
    expect(authMock.updateUser).toHaveBeenCalledWith({
      data: { display_name: "Flight Pilot" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Change avatar" }));
    const remoteAvatar =
      "https://accounts.example.test/storage/v1/object/public/profile-avatars/user-1/avatar.jpg?v=1777777777777";
    await waitFor(() => {
      expect(screen.getByLabelText("avatar"))
        .toHaveTextContent(remoteAvatar);
    });
    expect(authMock.storageFrom).toHaveBeenCalledWith("profile-avatars");
    expect(authMock.uploadAvatar).toHaveBeenCalledWith(
      "user-1/avatar.jpg",
      expect.any(Blob),
      {
        cacheControl: "3600",
        contentType: "image/jpeg",
        upsert: true,
      },
    );
    expect(authMock.updateUser).toHaveBeenCalledWith({
      data: { avatar_url: remoteAvatar },
    });
    expect(
      window.localStorage.getItem("drone-dream:account-avatar:user-1"),
    ).toBe(remoteAvatar);
  });

  it("keeps docs-preview avatar changes local and never contacts cloud storage", async () => {
    window.history.replaceState(null, "", "/assistant?docsPreview=1");
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    expect(await screen.findByLabelText("username"))
      .toHaveTextContent("DroneDream Pilot");
    fireEvent.click(screen.getByRole("button", { name: "Change avatar" }));

    const avatar = "data:image/jpeg;base64,ZmFrZS1hdmF0YXI=";
    await waitFor(() => {
      expect(screen.getByLabelText("avatar")).toHaveTextContent(avatar);
    });
    expect(authMock.storageFrom).not.toHaveBeenCalled();
    expect(authMock.updateUser).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("drone-dream:account-avatar:docs-preview"))
      .toBe(avatar);
  });

  it("uses passwords for sign-in and sets the password only after email-code verification", async () => {
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await screen.findByLabelText("username");
    fireEvent.click(screen.getByRole("button", { name: "Password sign in" }));
    await waitFor(() => {
      expect(authMock.signInWithPassword).toHaveBeenCalledWith({
        email: "pilot@example.com",
        password: "correct-horse",
      });
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Send registration code" }),
    );
    await waitFor(() => {
      expect(authMock.signInWithOtp).toHaveBeenCalledWith({
        email: "new@example.com",
        options: {
          shouldCreateUser: true,
          captchaToken: "captcha-register",
        },
      });
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Finish registration" }),
    );
    await waitFor(() => {
      expect(authMock.verifyOtp).toHaveBeenCalledWith({
        email: "new@example.com",
        token: "123456",
        type: "email",
      });
      expect(authMock.updateUser).toHaveBeenCalledWith({
        password: "correct-horse",
      });
    });
  });

  it("rolls back the verified registration session when the password update fails", async () => {
    authMock.updateUser.mockResolvedValueOnce({
      data: { user: authMock.state.user },
      error: new Error("registration password update failed"),
    });
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await screen.findByLabelText("username");
    fireEvent.click(
      screen.getByRole("button", { name: "Finish registration" }),
    );

    await waitFor(() => {
      expect(authMock.signOut).toHaveBeenCalledWith({ scope: "local" });
      expect(screen.getByLabelText("registration-error"))
        .toHaveTextContent("registration password update failed");
    });
    expect(authMock.verifyOtp.mock.invocationCallOrder[0])
      .toBeLessThan(authMock.updateUser.mock.invocationCallOrder[0]);
    expect(authMock.updateUser.mock.invocationCallOrder[0])
      .toBeLessThan(authMock.signOut.mock.invocationCallOrder[0]);
  });

  it("uses a same-origin email link and enters password recovery only after Supabase verifies it", async () => {
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await screen.findByLabelText("username");
    fireEvent.click(screen.getByRole("button", { name: "Request password reset" }));
    await waitFor(() => {
      expect(authMock.resetPasswordForEmail).toHaveBeenCalledWith(
        "pilot@example.com",
        {
          redirectTo: new URL("/", window.location.origin).toString(),
          captchaToken: "captcha-reset",
        },
      );
    });
    expect(screen.getByLabelText("password-recovery")).toHaveTextContent("false");

    act(() => {
      authMock.emitAuthStateChange("PASSWORD_RECOVERY", {
        user: authMock.state.user,
        access_token: "recovery-token",
      });
    });
    expect(screen.getByLabelText("password-recovery")).toHaveTextContent("true");

    fireEvent.click(screen.getByRole("button", { name: "Update password" }));
    await waitFor(() => {
      expect(authMock.updateUser).toHaveBeenCalledWith({
        password: "new-correct-horse",
      });
      expect(screen.getByLabelText("password-recovery")).toHaveTextContent("false");
    });
  });

  it("sends a non-creating OTP and verifies it as a code-only login", async () => {
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await screen.findByLabelText("username");
    fireEvent.click(screen.getByRole("button", { name: "Send recovery code" }));
    await waitFor(() => {
      expect(authMock.signInWithOtp).toHaveBeenCalledWith({
        email: "existing@example.com",
        options: {
          shouldCreateUser: false,
          captchaToken: "captcha-recovery",
        },
      });
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Sign in with recovery code" }),
    );
    await waitFor(() => {
      expect(authMock.verifyOtp).toHaveBeenCalledWith({
        email: "existing@example.com",
        token: "654321",
        type: "email",
      });
    });
    expect(authMock.updateUser).not.toHaveBeenCalled();
  });

  it("updates the password only after the existing-user OTP is verified", async () => {
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await screen.findByLabelText("username");
    fireEvent.click(
      screen.getByRole("button", { name: "Reset with recovery code" }),
    );
    await waitFor(() => {
      expect(authMock.verifyOtp).toHaveBeenCalledWith({
        email: "existing@example.com",
        token: "654321",
        type: "email",
      });
      expect(authMock.updateUser).toHaveBeenCalledWith({
        password: "new-recovery-password",
      });
    });
    expect(authMock.verifyOtp.mock.invocationCallOrder[0])
      .toBeLessThan(authMock.updateUser.mock.invocationCallOrder[0]);
  });

  it("rolls back the verified recovery session when the password update fails", async () => {
    authMock.updateUser.mockResolvedValueOnce({
      data: { user: authMock.state.user },
      error: new Error("password update failed"),
    });
    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await screen.findByLabelText("username");
    fireEvent.click(
      screen.getByRole("button", { name: "Reset with recovery code" }),
    );

    await waitFor(() => {
      expect(authMock.signOut).toHaveBeenCalledWith({ scope: "local" });
      expect(screen.getByLabelText("recovery-error"))
        .toHaveTextContent("password update failed");
    });
    expect(authMock.verifyOtp.mock.invocationCallOrder[0])
      .toBeLessThan(authMock.updateUser.mock.invocationCallOrder[0]);
    expect(authMock.updateUser.mock.invocationCallOrder[0])
      .toBeLessThan(authMock.signOut.mock.invocationCallOrder[0]);
  });

  it.each(["/", "/#/desktop/setup"])(
    "keeps Supabase session state out of the desktop launcher at %s and adopts only the native access token",
    async (launcherUrl) => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async () => undefined),
      },
    };
    window.history.replaceState(null, "", launcherUrl);

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await Promise.resolve();
    expect(authMock.getSession).not.toHaveBeenCalled();
    expect(authMock.onAuthStateChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("username")).toHaveTextContent("");

    activateDesktopAuthSession();
    adoptDesktopAccount();

    await waitFor(() => {
      expect(authMock.getSession).not.toHaveBeenCalled();
      expect(authMock.onAuthStateChange).not.toHaveBeenCalled();
      expect(screen.getByLabelText("username")).toHaveTextContent("pilot.name");
    });
    },
  );

  it("keeps the required desktop account surface mounted during activation", () => {
    window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };
    const loadingHistory: boolean[] = [];

    render(
      <AuthProvider>
        <LoadingHistoryProbe history={loadingHistory} />
      </AuthProvider>,
    );
    act(() => activateDesktopAuthSession());

    expect(screen.getByLabelText("auth-loading")).toHaveTextContent("false");
    expect(loadingHistory).not.toContain(true);
  });

  it("updates a desktop username with the native-adopted access token", async () => {
    const request = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", request);
    window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );
    activateDesktopAuthSession();
    adoptDesktopAccount();
    await screen.findByText("pilot.name");

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    await waitFor(() => {
      expect(screen.getByLabelText("username")).toHaveTextContent("Flight Pilot");
    });
    expect(request).toHaveBeenCalledWith(
      "https://accounts.example.test/auth/v1/user",
      expect.objectContaining({
        method: "PUT",
        headers: {
          apikey: "public-browser-key",
          Authorization: "Bearer session-token",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ data: { display_name: "Flight Pilot" } }),
      }),
    );
    expect(authMock.updateUser).not.toHaveBeenCalled();
    expect(authMock.getSession).not.toHaveBeenCalled();
  });

  it("uploads a desktop avatar with the adopted token and persists its shared URL", async () => {
    vi.spyOn(Date, "now").mockReturnValue(1_888_888_888_888);
    const request = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", request);
    window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );
    activateDesktopAuthSession();
    adoptDesktopAccount();
    await screen.findByText("pilot.name");

    fireEvent.click(screen.getByRole("button", { name: "Change avatar" }));

    const remoteAvatar =
      "https://accounts.example.test/storage/v1/object/public/profile-avatars/user-1/avatar.jpg?v=1888888888888";
    await waitFor(() => {
      expect(screen.getByLabelText("avatar")).toHaveTextContent(remoteAvatar);
    });
    expect(request).toHaveBeenNthCalledWith(
      1,
      "https://accounts.example.test/storage/v1/object/profile-avatars/user-1/avatar.jpg",
      expect.objectContaining({
        method: "POST",
        headers: {
          apikey: "public-browser-key",
          Authorization: "Bearer session-token",
          "Content-Type": "image/jpeg",
          "x-upsert": "true",
        },
        body: expect.any(Blob),
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "https://accounts.example.test/auth/v1/user",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ data: { avatar_url: remoteAvatar } }),
      }),
    );
    expect(authMock.updateUser).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("drone-dream:account-avatar:user-1"))
      .toBe(remoteAvatar);
  });

  it("replaces a raw desktop fetch failure with a useful avatar error", async () => {
    const request = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    vi.stubGlobal("fetch", request);
    window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );
    activateDesktopAuthSession();
    adoptDesktopAccount();
    await screen.findByText("pilot.name");

    fireEvent.click(screen.getByRole("button", { name: "Change avatar" }));

    await waitFor(() => {
      expect(screen.getByLabelText("avatar-error")).toHaveTextContent(
        "The profile photo could not be uploaded. Check your connection and try again.",
      );
    });
    expect(screen.getByLabelText("avatar")).toHaveTextContent("");
    expect(window.localStorage.getItem("drone-dream:account-avatar:user-1"))
      .toBeNull();
  });

  it("adopts an authenticated account when optional avatar storage is unavailable", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new DOMException("storage disabled", "SecurityError");
      });

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    expect(await screen.findByLabelText("username"))
      .toHaveTextContent("pilot.name");
    expect(screen.getByLabelText("email"))
      .toHaveTextContent("pilot.name@example.com");
    expect(screen.getByLabelText("avatar")).toHaveTextContent("");
    getItem.mockRestore();
  });

  it("preserves drafts when sign-out fails and clears them only after success", async () => {
    const draftKey = "drone-dream:experiment-workspace-draft:v1:workspace-1";
    window.localStorage.setItem(draftKey, "local-draft");
    window.sessionStorage.setItem(draftKey, "session-draft");
    authMock.signOut.mockResolvedValueOnce({
      data: {},
      error: new Error("network unavailable"),
    });

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );

    await screen.findByLabelText("username");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(authMock.signOut).toHaveBeenCalledTimes(1));
    expect(authMock.signOut).toHaveBeenLastCalledWith({ scope: "local" });
    expect(window.localStorage.getItem(draftKey)).toBe("local-draft");
    expect(window.sessionStorage.getItem(draftKey)).toBe("session-draft");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => {
      expect(authMock.signOut).toHaveBeenCalledTimes(2);
      expect(authMock.signOut).toHaveBeenLastCalledWith({ scope: "local" });
      expect(window.localStorage.getItem(draftKey)).toBeNull();
      expect(window.sessionStorage.getItem(draftKey)).toBeNull();
    });
  });

  it("clears only the desktop edition vault before local sign-out", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "clear_browser_auth_vault") return true;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );
    activateDesktopAuthSession();
    adoptDesktopAccount();
    await screen.findByText("pilot.name");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith("clear_browser_auth_vault", undefined);
      expect(authMock.signOut).toHaveBeenCalledWith({ scope: "local" });
    });
    expect(invoke.mock.invocationCallOrder[0])
      .toBeLessThan(authMock.signOut.mock.invocationCallOrder[0]);
  });

  it("still closes the local WebView session when edition vault cleanup fails", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "clear_browser_auth_vault") {
        throw new Error("credential manager unavailable");
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    render(
      <AuthProvider>
        <AccountProbe />
      </AuthProvider>,
    );
    activateDesktopAuthSession();
    adoptDesktopAccount();
    await screen.findByText("pilot.name");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => {
      expect(authMock.signOut).toHaveBeenCalledWith({ scope: "local" });
      expect(screen.getByLabelText("username")).toHaveTextContent("");
    });
  });
});
