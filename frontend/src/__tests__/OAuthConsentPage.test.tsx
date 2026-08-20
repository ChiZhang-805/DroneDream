import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const oauthMock = vi.hoisted(() => ({
  getAuthorizationDetails: vi.fn(),
  approveAuthorization: vi.fn(),
  denyAuthorization: vi.fn(),
}));

vi.mock("../features/auth/supabaseClient", () => ({
  supabaseClient: { auth: { oauth: oauthMock } },
}));

import {
  OAuthConsentPage,
} from "../site/OAuthConsentPage";
import {
  isAllowedDesktopCallback,
  isAllowedDesktopRedirectUri,
} from "../site/oauthConsentPolicy";

const account = {
  id: "account-1",
  email: "pilot@example.com",
  displayName: "Pilot",
  avatarUrl: null,
};

describe("desktop OAuth consent page", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/oauth/consent?authorization_id=authorization-1");
    oauthMock.getAuthorizationDetails.mockReset();
    oauthMock.approveAuthorization.mockReset();
    oauthMock.denyAuthorization.mockReset();
  });

  it("accepts only the five exact loopback callbacks", () => {
    const callbacks = [
      "http://127.0.0.1:49210/desktop-auth/universal/callback",
      "http://127.0.0.1:49211/desktop-auth/sim/callback",
      "http://127.0.0.1:49212/desktop-auth/lab/callback",
      "http://127.0.0.1:49213/desktop-auth/field/callback",
      "http://127.0.0.1:49214/desktop-auth/autonomy/callback",
    ];
    callbacks.forEach((callback) => {
      expect(isAllowedDesktopRedirectUri(callback)).toBe(true);
      expect(isAllowedDesktopCallback(`${callback}?code=code&state=state`)).toBe(true);
    });
    expect(isAllowedDesktopRedirectUri("https://example.com/callback")).toBe(false);
    expect(isAllowedDesktopCallback(
      "http://127.0.0.1:49210/desktop-auth/field/callback?code=code",
    )).toBe(false);
  });

  it("shows the verified desktop edition after an authenticated request", async () => {
    oauthMock.getAuthorizationDetails.mockResolvedValue({
      data: {
        authorization_id: "authorization-1",
        redirect_uri: "http://127.0.0.1:49212/desktop-auth/lab/callback",
        scope: "openid email profile",
        client: {
          name: "DroneDream LAB",
          uri: "https://getdronedream.com",
          logo_uri: "https://getdronedream.com/logo.svg",
        },
        user: { id: account.id, email: account.email },
      },
      error: null,
    });

    render(
      <OAuthConsentPage
        locale="en"
        account={account}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
      />,
    );

    expect(await screen.findByText("LAB")).toBeVisible();
    expect(screen.getByText("DroneDream LAB")).toBeVisible();
    expect(screen.getByText(account.email)).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve and return to the app" })).toBeEnabled();
    expect(oauthMock.getAuthorizationDetails).toHaveBeenCalledWith("authorization-1");
  });

  it("keeps distinct sign-in and account registration actions on the browser page", async () => {
    const onRequireSignIn = vi.fn();
    const onRequireRegistration = vi.fn();
    render(
      <OAuthConsentPage
        locale="en"
        account={null}
        authConfigured
        authLoading={false}
        onRequireSignIn={onRequireSignIn}
        onRequireRegistration={onRequireRegistration}
        onSwitchAccount={vi.fn()}
      />,
    );

    expect(screen.getByText(/verify your email and password/i)).toBeVisible();
    screen.getByRole("button", { name: "Sign in and continue" }).click();
    await waitFor(() => expect(onRequireSignIn).toHaveBeenCalledTimes(1));
    screen.getByRole("button", { name: /create an account/i }).click();
    await waitFor(() => expect(onRequireRegistration).toHaveBeenCalledTimes(1));
    expect(oauthMock.getAuthorizationDetails).not.toHaveBeenCalled();
  });

  it("rejects a missing authorization transaction before calling Supabase", () => {
    window.history.replaceState(null, "", "/oauth/consent");
    render(
      <OAuthConsentPage
        locale="en"
        account={account}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/missing or invalid/i);
    expect(oauthMock.getAuthorizationDetails).not.toHaveBeenCalled();
  });
});
