import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "../features/auth/AuthContext";
import { activateDesktopAuthSession } from "../features/auth/desktopAuthActivation";

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
  const onAuthStateChange = vi.fn(() => ({
    data: {
      subscription: { unsubscribe: vi.fn() },
    },
  }));
  return {
    state,
    getSession,
    onAuthStateChange,
    signInWithPassword: vi.fn(async () => ({ data: {}, error: null })),
    signInWithOtp: vi.fn(async () => ({ data: {}, error: null })),
    verifyOtp: vi.fn(async () => ({ data: {}, error: null })),
    signOut: vi.fn(async (): Promise<{
      data: Record<string, never>;
      error: Error | null;
    }> => ({ data: {}, error: null })),
    updateUser: vi.fn(async (
      payload: { data?: Record<string, unknown>; password?: string },
    ) => {
      if (payload.data) {
        state.user = {
          ...state.user,
          user_metadata: { ...state.user.user_metadata, ...payload.data },
        };
      }
      return { data: { user: state.user }, error: null };
    }),
    unsubscribe: vi.fn(),
  };
});

vi.mock("../features/auth/supabaseClient", () => ({
  appleAuthEnabled: false,
  cloudAuthConfigured: true,
  googleAuthEnabled: false,
  supabaseClient: {
    auth: {
      getSession: authMock.getSession,
      onAuthStateChange: authMock.onAuthStateChange,
      signInWithPassword: authMock.signInWithPassword,
      signInWithOtp: authMock.signInWithOtp,
      verifyOtp: authMock.verifyOtp,
      signOut: authMock.signOut,
      updateUser: authMock.updateUser,
    },
  },
}));

function AccountProbe() {
  const auth = useAuth();
  return (
    <>
      <output aria-label="username">{auth.account?.displayName ?? ""}</output>
      <output aria-label="email">{auth.account?.email ?? ""}</output>
      <output aria-label="avatar">{auth.account?.avatarUrl ?? ""}</output>
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
          )
        }
      >
        Finish registration
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

describe("AuthContext account profile", () => {
  afterEach(() => {
    authMock.state.user = {
      id: "user-1",
      email: "pilot.name@example.com",
      user_metadata: {},
    };
    authMock.updateUser.mockClear();
    authMock.getSession.mockClear();
    authMock.onAuthStateChange.mockClear();
    authMock.signInWithPassword.mockClear();
    authMock.signInWithOtp.mockClear();
    authMock.verifyOtp.mockClear();
    authMock.signOut.mockReset();
    authMock.signOut.mockResolvedValue({ data: {}, error: null });
    authMock.unsubscribe.mockClear();
    delete window.__TAURI__;
    window.history.replaceState(null, "", "/");
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("defaults to the email prefix and lets the user save a custom username", async () => {
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
    await waitFor(() => {
      expect(screen.getByLabelText("avatar"))
        .toHaveTextContent("data:image/jpeg;base64,ZmFrZS1hdmF0YXI=");
    });
    expect(
      window.localStorage.getItem("drone-dream:account-avatar:user-1"),
    ).toBe("data:image/jpeg;base64,ZmFrZS1hdmF0YXI=");
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

  it.each(["/", "/#/desktop/setup"])(
    "does not hydrate the desktop launcher at %s until the 100 percent sign-in action activates it",
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

    await waitFor(() => {
      expect(authMock.getSession).toHaveBeenCalledTimes(1);
      expect(authMock.onAuthStateChange).toHaveBeenCalledTimes(1);
      expect(screen.getByLabelText("username")).toHaveTextContent("pilot.name");
    });
    },
  );

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
    await screen.findByText("pilot.name");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => {
      expect(authMock.signOut).toHaveBeenCalledWith({ scope: "local" });
      expect(screen.getByLabelText("username")).toHaveTextContent("");
    });
  });
});
