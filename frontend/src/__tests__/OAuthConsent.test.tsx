import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OAuthConsentPage } from "../site/OAuthConsentPage";
import {
  oauthAuthorizationId,
  oauthClientRegistrations,
  oauthConsentPath,
  safeOAuthRedirectUrl,
} from "../site/oauthConsent";

const oauthMocks = vi.hoisted(() => ({
  getAuthorizationDetails: vi.fn(),
  approveAuthorization: vi.fn(),
  denyAuthorization: vi.fn(),
}));

vi.mock("../features/auth/supabaseClient", () => ({
  supabaseClient: {
    auth: {
      oauth: oauthMocks,
    },
  },
}));

const authorizationId = "authorization_1234567890abcdef";
const state = "state_1234567890abcdef";
const code = "code-1234567890abcdef";
const account = {
  id: "user-1",
  email: "pilot@example.test",
  displayName: "Pilot",
  avatarUrl: null,
};
const sim = oauthClientRegistrations.find(({ editionId }) => editionId === "sim")!;
const details = {
  authorization_id: authorizationId,
  redirect_uri: sim.redirectUri,
  client: {
    id: sim.clientId,
    name: sim.displayName,
    uri: "https://getdronedream.com/",
    logo_uri: "https://getdronedream.com/drone-favicon.png",
  },
  user: {
    id: account.id,
    email: account.email,
  },
  scope: "openid email profile",
};

function renderConsent(overrides: Partial<ComponentProps<typeof OAuthConsentPage>> = {}) {
  const onRequireSignIn = vi.fn();
  const onRedirect = vi.fn();
  render(
    <OAuthConsentPage
      locale="en"
      account={account}
      authLoading={false}
      cloudActionsEnabled
      authorizationId={authorizationId}
      onRequireSignIn={onRequireSignIn}
      onRedirect={onRedirect}
      {...overrides}
    />,
  );
  return { onRequireSignIn, onRedirect };
}

describe("OAuth consent contract", () => {
  beforeEach(() => {
    oauthMocks.getAuthorizationDetails.mockReset();
    oauthMocks.approveAuthorization.mockReset();
    oauthMocks.denyAuthorization.mockReset();
    oauthMocks.getAuthorizationDetails.mockResolvedValue({ data: details, error: null });
  });

  it("binds four unique public clients to four exact loopback callbacks", () => {
    expect(oauthClientRegistrations).toHaveLength(4);
    expect(new Set(oauthClientRegistrations.map(({ clientId }) => clientId)).size).toBe(4);
    expect(oauthClientRegistrations.map(({ redirectUri }) => redirectUri)).toEqual([
      "http://127.0.0.1:49210/desktop-auth/universal/callback",
      "http://127.0.0.1:49211/desktop-auth/sim/callback",
      "http://127.0.0.1:49212/desktop-auth/lab/callback",
      "http://127.0.0.1:49213/desktop-auth/field/callback",
    ]);
  });

  it("accepts exactly one bounded authorization identifier", () => {
    expect(oauthConsentPath(authorizationId))
      .toBe(`/oauth/consent/?authorization_id=${authorizationId}`);
    expect(oauthAuthorizationId(new URLSearchParams({ authorization_id: authorizationId })))
      .toBe(authorizationId);
    expect(oauthAuthorizationId(new URLSearchParams(
      `authorization_id=${authorizationId}&authorization_id=second_1234567890`,
    ))).toBeNull();
    expect(oauthAuthorizationId(new URLSearchParams(
      "authorization_id=https%3A%2F%2Fattacker.example%2F",
    ))).toBeNull();
  });

  it("redirects an unauthenticated user without losing the authorization identifier", () => {
    const { onRequireSignIn } = renderConsent({ account: null });

    expect(onRequireSignIn).toHaveBeenCalledWith(authorizationId);
    expect(oauthMocks.getAuthorizationDetails).not.toHaveBeenCalled();
  });

  it("loads the registered client and requested account access", async () => {
    renderConsent();

    expect(await screen.findAllByText("DroneDream \u00b7 SIM")).toHaveLength(2);
    expect(screen.getByText("Identity, email address, and profile")).toBeVisible();
    expect(oauthMocks.getAuthorizationDetails).toHaveBeenCalledWith(authorizationId);
  });

  it("renders the consent action in Simplified Chinese", async () => {
    renderConsent({ locale: "zh-CN" });

    expect(await screen.findByRole("heading", { name: "授权此应用" })).toBeVisible();
    expect(screen.getByRole("button", { name: "授权并返回应用" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "拒绝" })).toBeEnabled();
  });

  it("returns an already-consented registered redirect without another decision", async () => {
    const redirectUrl = `${sim.redirectUri}?code=${code}&state=${state}`;
    oauthMocks.getAuthorizationDetails.mockResolvedValue({
      data: { redirect_url: redirectUrl },
      error: null,
    });
    const { onRedirect } = renderConsent();

    await waitFor(() => expect(onRedirect).toHaveBeenCalledWith(redirectUrl));
    expect(oauthMocks.approveAuthorization).not.toHaveBeenCalled();
    expect(oauthMocks.denyAuthorization).not.toHaveBeenCalled();
  });

  it.each([
    [
      "Authorize and return to app",
      "approveAuthorization",
      `${sim.redirectUri}?code=${code}&state=${state}`,
    ],
    [
      "Deny",
      "denyAuthorization",
      `${sim.redirectUri}?error=access_denied&state=${state}`,
    ],
  ] as const)("returns the provider redirect after %s", async (
    buttonName,
    method,
    redirectUrl,
  ) => {
    oauthMocks[method].mockResolvedValue({
      data: { redirect_url: redirectUrl },
      error: null,
    });
    const { onRedirect } = renderConsent();

    fireEvent.click(await screen.findByRole("button", { name: buttonName }));

    await waitFor(() => {
      expect(oauthMocks[method]).toHaveBeenCalledWith(
        authorizationId,
        { skipBrowserRedirect: true },
      );
      expect(onRedirect).toHaveBeenCalledWith(redirectUrl);
    });
  });

  it.each([
    {
      label: "unknown client",
      override: { client: { ...details.client, id: "attacker-client" } },
    },
    {
      label: "cross-edition callback",
      override: { redirect_uri: oauthClientRegistrations[2].redirectUri },
    },
    {
      label: "over-broad scope",
      override: { scope: "openid email profile admin" },
    },
  ])("fails closed before consent for $label", async ({ override }) => {
    oauthMocks.getAuthorizationDetails.mockResolvedValue({
      data: {
        ...details,
        ...override,
      },
      error: null,
    });
    renderConsent();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This authorization request is invalid",
    );
    expect(screen.queryByRole("button", { name: "Authorize and return to app" }))
      .toBeNull();
    expect(oauthMocks.approveAuthorization).not.toHaveBeenCalled();
  });

  it("rejects external, cross-edition, and over-broad redirect URLs", () => {
    expect(safeOAuthRedirectUrl(
      `${sim.redirectUri}?code=${code}&state=${state}`,
      sim,
    )).toBe(`${sim.redirectUri}?code=${code}&state=${state}`);
    expect(safeOAuthRedirectUrl(
      `https://attacker.example/callback?code=${code}&state=${state}`,
      sim,
    )).toBeNull();
    expect(safeOAuthRedirectUrl(
      `${oauthClientRegistrations[2].redirectUri}?code=${code}&state=${state}`,
      sim,
    )).toBeNull();
    expect(safeOAuthRedirectUrl(
      `${sim.redirectUri}?code=${code}&state=${state}&accessToken=secret`,
      sim,
    )).toBeNull();
    expect(safeOAuthRedirectUrl(
      `${sim.redirectUri}?code=${code}&code=second&state=${state}`,
      sim,
    )).toBeNull();
    expect(safeOAuthRedirectUrl(
      `${sim.redirectUri}?code=${code}&state=${state}&error_description=nope`,
      sim,
    )).toBeNull();
    expect(safeOAuthRedirectUrl(
      `${sim.redirectUri}?error=access_denied&state=${state}&error_code=nope`,
      sim,
    )).toBeNull();
  });
});
