import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { getAuthAccessToken, setAuthAccessToken } from "../features/auth/authTokenStore";

import {
  AuthProvider,
  providerRedirectUrl,
  useAuth,
} from "../features/auth/AuthContext";
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
    activeDesktopSession: false,
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
  hasActiveDesktopAuthSession: () => authMock.activeDesktopSession,
  githubAuthEnabled: false,
  googleAuthEnabled: false,
  slackAuthEnabled: false,
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
  const [profileError, setProfileError] = useState("");
  const [passwordError, setPasswordError] = useState("");
  return (
    <>
      <output aria-label="username">{auth.account?.displayName ?? ""}</output>
      <output aria-label="email">{auth.account?.email ?? ""}</output>
      <output aria-label="avatar">{auth.account?.avatarUrl ?? ""}</output>
      <output aria-label="avatar-fallback">{auth.account?.avatarFallbackUrl ?? ""}</output>
      <output aria-label="avatar-error">{avatarError}</output>
      <output aria-label="registration-error">{registrationError}</output>
      <output aria-label="recovery-error">{recoveryError}</output>
      <output aria-label="profile-error">{profileError}</output>
      <output aria-label="password-error">{passwordError}</output>
      <output aria-label="password-recovery">{String(auth.passwordRecovery)}</output>
      <button
        type="button"
        onClick={() => void auth.updateDisplayName("Flight Pilot").catch((error: Error) => {
          setProfileError(error.message);
        })}
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
            .catch((error: Error) => setPasswordError(error.message))
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
  it("keeps a desktop authorization request through a provider redirect", () => {
    expect(providerRedirectUrl(
      "https://getdronedream.com/oauth/consent?authorization_id=desktop-request-1&ignored=value#secret",
    )).toBe(
      "https://getdronedream.com/oauth/consent?authorization_id=desktop-request-1",
    );
    expect(providerRedirectUrl(
      "https://getdronedream.com/community/?view=all#topics",
    )).toBe("https://getdronedream.com/community/");
  });

  it("does not overwrite a newer auth event with a late hydration snapshot", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof authMock.getSession>>) => void;
    const oldUser = { ...authMock.state.user };
    authMock.getSession.mockReturnValueOnce(new Promise((accept) => { resolve = accept; }));
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    act(() => authMock.emitAuthStateChange("SIGNED_IN", {
      user: { ...oldUser, id: "user-2", email: "new@example.com" }, access_token: "new-token",
    }));
    await act(async () => resolve({
      data: { session: { user: oldUser, access_token: "old-token" } }, error: null,
    }));
    expect(screen.getByLabelText("email")).toHaveTextContent("new@example.com");
  });

  it("settles loading when hydration rejects instead of returning an error object", async () => {
    authMock.getSession.mockRejectedValueOnce(new Error("offline"));
    render(<AuthProvider><LoadingHistoryProbe history={[]} /></AuthProvider>);
    await waitFor(() => expect(screen.getByLabelText("auth-loading")).toHaveTextContent("false"));
  });

  it("does not rename the new desktop account with a late old-account response", async () => {
    let resolve!: (value: typeof authMock.state.user) => void;
    window.__TAURI__ = { core: { invoke: vi.fn((command: string) => command === "update_account_profile"
      ? new Promise((accept) => { resolve = accept; }) : Promise.resolve(undefined)) } };
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    act(() => { activateDesktopAuthSession(); adoptDesktopAccount(); });
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    act(() => window.dispatchEvent(new CustomEvent(ADOPT_DESKTOP_AUTH_EVENT, {
      detail: {
        user: { ...authMock.state.user, id: "user-2", email: "new@example.com" },
        accessToken: "new-token",
      },
    })));
    await act(async () => resolve({ ...authMock.state.user, user_metadata: { display_name: "Flight Pilot" } }));
    expect(screen.getByLabelText("username")).toHaveTextContent("new");
    expect(screen.getByLabelText("profile-error")).toHaveTextContent("account changed");
  });

  it("does not write old avatar metadata into a newly signed-in web account", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof authMock.uploadAvatar>>) => void;
    authMock.uploadAvatar.mockReturnValueOnce(new Promise((accept) => { resolve = accept; }));
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    await waitFor(() => expect(screen.getByLabelText("email")).toHaveTextContent("pilot.name"));
    fireEvent.click(screen.getByRole("button", { name: "Change avatar" }));
    act(() => authMock.emitAuthStateChange("SIGNED_IN", {
      user: { ...authMock.state.user, id: "user-2", email: "new@example.com" },
      access_token: "new-token",
    }));
    await act(async () => resolve({ data: { path: "user-1/avatar.jpg" }, error: null }));
    expect(authMock.updateUser).not.toHaveBeenCalled();
    expect(screen.getByLabelText("email")).toHaveTextContent("new@example.com");
    expect(screen.getByLabelText("avatar-error")).toHaveTextContent("account changed");
  });

  afterEach(() => {
    authMock.activeDesktopSession = false;
    setAuthAccessToken(null);
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
      data: { dronedream_avatar_url: remoteAvatar },
    });
    expect(
      window.localStorage.getItem("drone-dream:account-avatar:user-1"),
    ).toBe(remoteAvatar);
  });

  it("keeps the provider photo available when a saved custom avatar is stale", async () => {
    authMock.state.user = {
      ...authMock.state.user,
      user_metadata: {
        dronedream_avatar_url: "https://accounts.example.test/storage/v1/object/public/profile-avatars/user-1/avatar.jpg",
        picture: "https://identity.example.test/pilot.jpg",
      },
    };

    render(<AuthProvider><AccountProbe /></AuthProvider>);

    expect(await screen.findByLabelText("avatar")).toHaveTextContent(
      "https://accounts.example.test/storage/v1/object/public/profile-avatars/user-1/avatar.jpg",
    );
    expect(screen.getByLabelText("avatar-fallback")).toHaveTextContent(
      "https://identity.example.test/pilot.jpg",
    );
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

    act(() => { activateDesktopAuthSession(); adoptDesktopAccount(); });

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

  it("adopts the returned password session in desktop and tracks its refresh and sign-out", async () => {
    const invoke = vi.fn(async () => undefined);
    window.__TAURI__ = { core: { invoke } };
    const session = { user: authMock.state.user, access_token: "direct-password-token" };
    authMock.signInWithPassword.mockResolvedValueOnce({ data: { session }, error: null });
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    expect(authMock.getSession).not.toHaveBeenCalled();
    expect(screen.getByLabelText("username")).toBeEmptyDOMElement();

    fireEvent.click(screen.getByRole("button", { name: "Password sign in" }));
    await waitFor(() => expect(screen.getByLabelText("username")).toHaveTextContent("pilot.name"));
    expect(getAuthAccessToken()).toBe("direct-password-token");
    expect(authMock.getSession).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalledWith("begin_browser_auth", expect.anything());

    act(() => authMock.emitAuthStateChange("TOKEN_REFRESHED", {
      user: { ...authMock.state.user, user_metadata: { display_name: "Refreshed Pilot" } },
      access_token: "refreshed-password-token",
    }));
    expect(getAuthAccessToken()).toBe("refreshed-password-token");
    expect(screen.getByLabelText("username")).toHaveTextContent("Refreshed Pilot");
    act(() => authMock.emitAuthStateChange("SIGNED_OUT", null));
    expect(getAuthAccessToken()).toBeNull();
    expect(screen.getByLabelText("username")).toBeEmptyDOMElement();
  });

  it("does not publish a desktop identity when password sign-in returns no session", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };
    authMock.signInWithPassword.mockResolvedValueOnce({ data: { session: null }, error: null });
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Password sign in" }));
    await waitFor(() => expect(screen.getByLabelText("password-error"))
      .toHaveTextContent("The account service returned no session."));
    expect(screen.getByLabelText("username")).toBeEmptyDOMElement();
    expect(getAuthAccessToken()).toBeNull();
    expect(authMock.onAuthStateChange).not.toHaveBeenCalled();
  });

  it.each(["Finish registration", "Reset with recovery code"])(
    "publishes the desktop code session only after the password write succeeds: %s",
    async (button) => {
      window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };
      const session = { user: authMock.state.user, access_token: "verified-code-token" };
      authMock.verifyOtp.mockResolvedValueOnce({ data: { session }, error: null });
      let finishPassword!: (result: { data: { user: typeof authMock.state.user }; error: null }) => void;
      authMock.updateUser.mockImplementationOnce(() => new Promise((resolve) => { finishPassword = resolve; }));
      render(<AuthProvider><AccountProbe /></AuthProvider>);
      fireEvent.click(screen.getByRole("button", { name: button }));
      await waitFor(() => expect(authMock.updateUser).toHaveBeenCalled());
      expect(screen.getByLabelText("username")).toBeEmptyDOMElement();
      expect(getAuthAccessToken()).toBeNull();
      await act(async () => finishPassword({ data: { user: authMock.state.user }, error: null }));
      expect(screen.getByLabelText("username")).toHaveTextContent("pilot.name");
      expect(getAuthAccessToken()).toBe("verified-code-token");
    },
  );

  it.each([
    ["Finish registration", "registration-error"],
    ["Reset with recovery code", "recovery-error"],
  ])("keeps desktop signed out when the verified-code password write fails: %s", async (button, errorLabel) => {
    window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };
    authMock.verifyOtp.mockResolvedValueOnce({
      data: { session: { user: authMock.state.user, access_token: "uncommitted-code-token" } }, error: null,
    });
    authMock.updateUser.mockResolvedValueOnce({ data: { user: authMock.state.user }, error: new Error("password write failed") });
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    fireEvent.click(screen.getByRole("button", { name: button }));
    await waitFor(() => expect(screen.getByLabelText(errorLabel)).toHaveTextContent("password write failed"));
    expect(authMock.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(screen.getByLabelText("username")).toBeEmptyDOMElement();
    expect(getAuthAccessToken()).toBeNull();
  });

  it("hydrates an already active process session after the desktop document reloads", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };
    authMock.activeDesktopSession = true;
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    await waitFor(() => expect(screen.getByLabelText("username")).toHaveTextContent("pilot.name"));
    expect(authMock.getSession).toHaveBeenCalledTimes(1);
    expect(authMock.onAuthStateChange).toHaveBeenCalledTimes(1);
    expect(getAuthAccessToken()).toBe("session-token");
  });

  it.each(["resolve", "reject"])(
    "keeps a newer native account when restored SDK hydration is late and then %ss",
    async (outcome) => {
      window.__TAURI__ = { core: { invoke: vi.fn(async () => undefined) } };
      authMock.activeDesktopSession = true;
      let complete!: (value: Awaited<ReturnType<typeof authMock.getSession>>) => void;
      let fail!: (reason: Error) => void;
      authMock.getSession.mockImplementationOnce(() => new Promise((resolve, reject) => {
        complete = resolve;
        fail = reject;
      }));
      render(<AuthProvider><AccountProbe /></AuthProvider>);
      act(() => window.dispatchEvent(new CustomEvent(ADOPT_DESKTOP_AUTH_EVENT, {
        detail: {
          user: { id: "native-user", email: "native@example.com", user_metadata: {} },
          accessToken: "native-account-token",
        },
      })));
      expect(screen.getByLabelText("email")).toHaveTextContent("native@example.com");
      await act(async () => {
        if (outcome === "resolve") complete({
          data: { session: { user: authMock.state.user, access_token: "stale-sdk-token" } }, error: null,
        });
        else fail(new Error("late hydration failed"));
      });
      act(() => authMock.emitAuthStateChange("TOKEN_REFRESHED", {
        user: authMock.state.user, access_token: "stale-refresh-token",
      }));
      act(() => authMock.emitAuthStateChange("SIGNED_OUT", null));
      expect(screen.getByLabelText("email")).toHaveTextContent("native@example.com");
      expect(getAuthAccessToken()).toBe("native-account-token");
    },
  );

  it("saves a desktop username through native HTTPS and adopts the returned cloud profile", async () => {
    const invoke = vi.fn(async (command: string) => command === "update_account_profile"
      ? { ...authMock.state.user, user_metadata: { display_name: "Flight Pilot" } } : undefined);
    window.__TAURI__ = { core: { invoke } };
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    act(() => { activateDesktopAuthSession(); adoptDesktopAccount(); });
    await screen.findByText("pilot.name");
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(screen.getByLabelText("username")).toHaveTextContent("Flight Pilot"));
    expect(invoke).toHaveBeenCalledWith("update_account_profile", { request: {
      accessToken: "session-token", publishableKey: "public-browser-key", userId: "user-1",
      change: { kind: "name", value: "Flight Pilot" },
    } });
    expect(authMock.updateUser).not.toHaveBeenCalled();
  });

  it("persists the confirmed desktop avatar URL returned by the account service", async () => {
    vi.spyOn(Date, "now").mockReturnValue(1_888_888_888_888);
    const remoteAvatar = "https://accounts.example.test/storage/v1/object/public/profile-avatars/user-1/avatar.jpg?v=1888888888888";
    const invoke = vi.fn(async (command: string) => command === "update_account_profile"
      ? { ...authMock.state.user, user_metadata: { dronedream_avatar_url: remoteAvatar } } : undefined);
    window.__TAURI__ = { core: { invoke } };
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    act(() => { activateDesktopAuthSession(); adoptDesktopAccount(); });
    await screen.findByText("pilot.name");
    fireEvent.click(screen.getByRole("button", { name: "Change avatar" }));
    await waitFor(() => expect(screen.getByLabelText("avatar")).toHaveTextContent(remoteAvatar));
    expect(invoke).toHaveBeenCalledWith("update_account_profile", { request: {
      accessToken: "session-token", publishableKey: "public-browser-key", userId: "user-1",
      change: { kind: "avatar", value: "data:image/jpeg;base64,ZmFrZS1hdmF0YXI=" },
    } });
    expect(window.localStorage.getItem("drone-dream:account-avatar:user-1")).toBe(remoteAvatar);
    expect(authMock.updateUser).not.toHaveBeenCalled();
  });

  it("keeps the existing desktop profile when the native save fails", async () => {
    const message = "Could not reach the account service. Try saving again.";
    window.__TAURI__ = { core: { invoke: vi.fn(async (command: string) => {
      if (command === "update_account_profile") throw new Error(message);
      return undefined;
    }) } };
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    act(() => { activateDesktopAuthSession(); adoptDesktopAccount(); });
    await screen.findByText("pilot.name");
    fireEvent.click(screen.getByRole("button", { name: "Change avatar" }));
    await waitFor(() => expect(screen.getByLabelText("avatar-error")).toHaveTextContent(message));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(screen.getByLabelText("profile-error")).toHaveTextContent(message));
    expect(screen.getByLabelText("username")).toHaveTextContent("pilot.name");
  });

  it("does not restore a deleted cloud avatar from stale local cache", async () => {
    window.localStorage.setItem("drone-dream:account-avatar:user-1", "https://accounts.example.test/storage/v1/object/public/profile-avatars/user-1/avatar.jpg");
    authMock.state.user.user_metadata = { dronedream_avatar_url: null };
    render(<AuthProvider><AccountProbe /></AuthProvider>);
    await screen.findByText("pilot.name");
    expect(screen.getByLabelText("avatar")).toBeEmptyDOMElement();
    expect(window.localStorage.getItem("drone-dream:account-avatar:user-1")).toBeNull();
  });

  it("reconstructs the shared avatar URL when optional WebView storage is unavailable", async () => {
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
    expect(screen.getByLabelText("avatar")).toHaveTextContent(
      "https://accounts.example.test/storage/v1/object/public/profile-avatars/user-1/avatar.jpg",
    );
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
    act(() => { activateDesktopAuthSession(); adoptDesktopAccount(); });
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
    act(() => { activateDesktopAuthSession(); adoptDesktopAccount(); });
    await screen.findByText("pilot.name");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => {
      expect(authMock.signOut).toHaveBeenCalledWith({ scope: "local" });
      expect(screen.getByLabelText("username")).toHaveTextContent("");
    });
  });
});
