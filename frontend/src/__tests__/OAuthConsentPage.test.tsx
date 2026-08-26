import { StrictMode } from "react";
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

const agentAuthorizationDetails = {
  authorization_id: "authorization-1",
  redirect_uri: "http://127.0.0.1:49214/desktop-auth/autonomy/callback",
  scope: "openid email profile",
  client: {
    name: "DroneDream AGENT",
    uri: "https://getdronedream.com",
    logo_uri: "https://getdronedream.com/logo.svg",
  },
  user: { id: account.id, email: account.email },
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

  it("automatically approves a verified AGENT request exactly once and returns to the app", async () => {
    const onDesktopRedirect = vi.fn();
    oauthMock.getAuthorizationDetails.mockResolvedValue({
      data: agentAuthorizationDetails,
      error: null,
    });
    oauthMock.approveAuthorization.mockResolvedValue({
      data: {
        redirect_url: "http://127.0.0.1:49214/desktop-auth/autonomy/callback?code=code&state=state",
      },
      error: null,
    });

    render(
      <StrictMode>
        <OAuthConsentPage
          locale="en"
          account={account}
          authConfigured
          authLoading={false}
          onRequireSignIn={vi.fn()}
          onRequireRegistration={vi.fn()}
          onSwitchAccount={vi.fn()}
          onDesktopRedirect={onDesktopRedirect}
        />
      </StrictMode>,
    );

    expect(await screen.findByText("AGENT")).toBeVisible();
    expect(screen.getByText("DroneDream AGENT")).toBeVisible();
    expect(screen.getByText(account.email)).toBeVisible();
    expect(oauthMock.getAuthorizationDetails).toHaveBeenCalledWith("authorization-1");
    await waitFor(() => {
      expect(oauthMock.approveAuthorization).toHaveBeenCalledTimes(1);
      expect(oauthMock.approveAuthorization).toHaveBeenCalledWith(
        "authorization-1",
        { skipBrowserRedirect: true },
      );
      expect(onDesktopRedirect).toHaveBeenCalledWith(
        "http://127.0.0.1:49214/desktop-auth/autonomy/callback?code=code&state=state",
      );
    });
  });

  it("does not approve a new transaction with stale details or follow its stale completion", async () => {
    const approval = deferred<{
      data: { redirect_url: string };
      error: null;
    }>();
    const nextDetails = deferred<unknown>();
    const onDesktopRedirect = vi.fn();
    oauthMock.getAuthorizationDetails.mockImplementation((authorizationId: string) => {
      if (authorizationId === "authorization-1") {
        return Promise.resolve({ data: agentAuthorizationDetails, error: null });
      }
      return nextDetails.promise;
    });
    oauthMock.approveAuthorization.mockReturnValue(approval.promise);

    const page = render(
      <OAuthConsentPage
        locale="en"
        account={account}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
        onDesktopRedirect={onDesktopRedirect}
      />,
    );
    await waitFor(() => {
      expect(oauthMock.approveAuthorization).toHaveBeenCalledWith(
        "authorization-1",
        { skipBrowserRedirect: true },
      );
    });

    window.history.replaceState(
      null,
      "",
      "/oauth/consent?authorization_id=authorization-2",
    );
    page.rerender(
      <OAuthConsentPage
        locale="en"
        account={account}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
        onDesktopRedirect={onDesktopRedirect}
      />,
    );
    approval.resolve({
      data: {
        redirect_url: "http://127.0.0.1:49214/desktop-auth/autonomy/callback?code=old&state=old",
      },
      error: null,
    });

    await waitFor(() => {
      expect(oauthMock.getAuthorizationDetails).toHaveBeenCalledWith("authorization-2");
    });
    expect(oauthMock.approveAuthorization).toHaveBeenCalledTimes(1);
    expect(onDesktopRedirect).not.toHaveBeenCalled();
  });

  it("invalidates an approval completion when the signed-in account changes", async () => {
    const approval = deferred<{
      data: { redirect_url: string };
      error: null;
    }>();
    const switchedDetails = deferred<unknown>();
    const onDesktopRedirect = vi.fn();
    oauthMock.getAuthorizationDetails
      .mockResolvedValueOnce({ data: agentAuthorizationDetails, error: null })
      .mockReturnValueOnce(switchedDetails.promise);
    oauthMock.approveAuthorization.mockReturnValue(approval.promise);
    const switchedAccount = {
      ...account,
      id: "account-2",
      email: "other@example.com",
    };

    const page = render(
      <OAuthConsentPage
        locale="en"
        account={account}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
        onDesktopRedirect={onDesktopRedirect}
      />,
    );
    await waitFor(() => expect(oauthMock.approveAuthorization).toHaveBeenCalledTimes(1));

    page.rerender(
      <OAuthConsentPage
        locale="en"
        account={switchedAccount}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
        onDesktopRedirect={onDesktopRedirect}
      />,
    );
    approval.resolve({
      data: {
        redirect_url: "http://127.0.0.1:49214/desktop-auth/autonomy/callback?code=old&state=old",
      },
      error: null,
    });

    await waitFor(() => expect(oauthMock.getAuthorizationDetails).toHaveBeenCalledTimes(2));
    expect(oauthMock.approveAuthorization).toHaveBeenCalledTimes(1);
    expect(onDesktopRedirect).not.toHaveBeenCalled();
  });

  it("allows the original account to start a fresh approval after switching away and back", async () => {
    const firstApproval = deferred<{
      data: { redirect_url: string };
      error: null;
    }>();
    const secondApproval = deferred<{
      data: { redirect_url: string };
      error: null;
    }>();
    const switchedAccount = {
      ...account,
      id: "account-2",
      email: "other@example.com",
    };
    oauthMock.getAuthorizationDetails.mockResolvedValue({
      data: agentAuthorizationDetails,
      error: null,
    });
    oauthMock.approveAuthorization
      .mockReturnValueOnce(firstApproval.promise)
      .mockReturnValueOnce(secondApproval.promise);

    const page = render(
      <OAuthConsentPage
        locale="en"
        account={account}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
        onDesktopRedirect={vi.fn()}
      />,
    );
    await waitFor(() => expect(oauthMock.approveAuthorization).toHaveBeenCalledTimes(1));

    page.rerender(
      <OAuthConsentPage
        locale="en"
        account={switchedAccount}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
        onDesktopRedirect={vi.fn()}
      />,
    );
    await waitFor(() => expect(oauthMock.getAuthorizationDetails).toHaveBeenCalledTimes(2));

    page.rerender(
      <OAuthConsentPage
        locale="en"
        account={account}
        authConfigured
        authLoading={false}
        onRequireSignIn={vi.fn()}
        onRequireRegistration={vi.fn()}
        onSwitchAccount={vi.fn()}
        onDesktopRedirect={vi.fn()}
      />,
    );

    await waitFor(() => expect(oauthMock.approveAuthorization).toHaveBeenCalledTimes(2));
  });

  it("rejects authorization details bound to a different signed-in account", async () => {
    oauthMock.getAuthorizationDetails.mockResolvedValue({
      data: {
        ...agentAuthorizationDetails,
        user: { id: "different-account", email: "other@example.com" },
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
        onDesktopRedirect={vi.fn()}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be verified/i);
    expect(oauthMock.approveAuthorization).not.toHaveBeenCalled();
  });

  it("rejects an allowlisted callback belonging to another desktop edition", async () => {
    const onDesktopRedirect = vi.fn();
    oauthMock.getAuthorizationDetails.mockResolvedValue({
      data: agentAuthorizationDetails,
      error: null,
    });
    oauthMock.approveAuthorization.mockResolvedValue({
      data: {
        redirect_url: "http://127.0.0.1:49212/desktop-auth/lab/callback?code=code&state=state",
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
        onDesktopRedirect={onDesktopRedirect}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be verified/i);
    expect(onDesktopRedirect).not.toHaveBeenCalled();
  });

  it("rejects an already-consented redirect outside the desktop callback allowlist", async () => {
    const onDesktopRedirect = vi.fn();
    oauthMock.getAuthorizationDetails.mockResolvedValue({
      data: {
        redirect_url: "https://attacker.example/callback?code=code&state=state",
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
        onDesktopRedirect={onDesktopRedirect}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be verified/i);
    expect(onDesktopRedirect).not.toHaveBeenCalled();
    expect(oauthMock.approveAuthorization).not.toHaveBeenCalled();
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
    expect(onRequireSignIn).not.toHaveBeenCalled();
    expect(onRequireRegistration).not.toHaveBeenCalled();
    expect(oauthMock.getAuthorizationDetails).not.toHaveBeenCalled();
  });

  it("never approves a request whose desktop redirect is not on the exact allowlist", async () => {
    oauthMock.getAuthorizationDetails.mockResolvedValue({
      data: {
        authorization_id: "authorization-1",
        redirect_uri: "http://127.0.0.1:49214/desktop-auth/field/callback",
        scope: "openid email profile",
        client: { name: "Fake client", uri: "https://example.com", logo_uri: "" },
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
        onDesktopRedirect={vi.fn()}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be verified/i);
    expect(oauthMock.approveAuthorization).not.toHaveBeenCalled();
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
