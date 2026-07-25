import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "../features/auth/AuthContext";

const authMock = vi.hoisted(() => {
  const state = {
    user: {
      id: "user-1",
      email: "pilot.name@example.com",
      user_metadata: {} as Record<string, unknown>,
    },
  };
  return {
    state,
    signInWithPassword: vi.fn(async () => ({ data: {}, error: null })),
    signInWithOtp: vi.fn(async () => ({ data: {}, error: null })),
    verifyOtp: vi.fn(async () => ({ data: {}, error: null })),
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
      getSession: vi.fn(async () => ({
        data: {
          session: {
            user: authMock.state.user,
            access_token: "session-token",
          },
        },
        error: null,
      })),
      onAuthStateChange: vi.fn(() => ({
        data: {
          subscription: { unsubscribe: authMock.unsubscribe },
        },
      })),
      signInWithPassword: authMock.signInWithPassword,
      signInWithOtp: authMock.signInWithOtp,
      verifyOtp: authMock.verifyOtp,
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
        onClick={() => void auth.sendRegistrationCode("new@example.com")}
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
    authMock.signInWithPassword.mockClear();
    authMock.signInWithOtp.mockClear();
    authMock.verifyOtp.mockClear();
    authMock.unsubscribe.mockClear();
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
        options: { shouldCreateUser: true },
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
});
