import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DroneDreamAccount } from "../features/auth/AuthContext";
import { I18nProvider } from "../i18n/I18nProvider";
import { SiteApp } from "../site/SiteApp";
import { oauthConsentPath } from "../site/oauthConsent";
import { websiteAuthUrl } from "../site/websiteAuth";

const authState = vi.hoisted(() => ({
  signInWithPassword: vi.fn(),
  current: {
    configured: true,
    loading: false,
    account: null,
  } as {
    configured: boolean;
    loading: boolean;
    account: DroneDreamAccount | null;
  },
}));

vi.mock("../features/auth/AuthContext", () => ({
  useAuthOrLocal: () => ({
    ...authState.current,
    googleEnabled: false,
    appleEnabled: false,
    signInWithPassword: authState.signInWithPassword,
    sendRegistrationCode: vi.fn(),
    verifyRegistrationCode: vi.fn(),
    signInWithProvider: vi.fn(),
    updateDisplayName: vi.fn(),
    updateAvatar: vi.fn(),
    signOut: vi.fn(),
  }),
}));

function renderSite() {
  return render(
    <I18nProvider>
      <SiteApp />
    </I18nProvider>,
  );
}

describe("website account navigation", () => {
  const desktopInvoke = vi.fn();

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline test")));
    vi.stubGlobal("scrollTo", vi.fn());
    Object.defineProperty(window, "__TAURI__", {
      configurable: true,
      value: { core: { invoke: desktopInvoke } },
    });
    authState.signInWithPassword.mockReset();
    authState.signInWithPassword.mockResolvedValue(undefined);
    authState.current = {
      configured: true,
      loading: false,
      account: null,
    };
    desktopInvoke.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete window.__TAURI__;
  });

  it("builds only allowlisted same-site return targets", () => {
    expect(websiteAuthUrl("sign-in", "/community/"))
      .toBe("/account/?source=website&mode=sign-in&returnTo=%2Fcommunity%2F");
    expect(websiteAuthUrl("register", "https://attacker.example/"))
      .toBe("/account/?source=website&mode=register&returnTo=%2F");
    expect(websiteAuthUrl("sign-in", "//attacker.example/"))
      .toBe("/account/?source=website&mode=sign-in&returnTo=%2F");
  });

  it("keeps a website-origin sign-in browser-only and returns to the homepage", async () => {
    renderSite();

    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    const form = await waitFor(() => {
      const current = document.querySelector(".site-auth-form");
      expect(current).not.toBeNull();
      return current;
    });
    expect(form).not.toBeNull();

    expect(window.location.pathname).toBe("/account/");
    expect(new URLSearchParams(window.location.search).get("source")).toBe("website");
    expect(new URLSearchParams(window.location.search).get("returnTo")).toBe("/");
    expect(screen.getByText(
      /Universal, SIM, LAB, and FIELD each require an explicit Sign in click/i,
    )).toBeVisible();
    expect(screen.getByText(/another app's session never signs an app in automatically/i))
      .toBeVisible();
    expect(document.querySelector('[data-auth-source="website"]')).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "pilot@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "safe-password" },
    });
    fireEvent.click(
      within(form as HTMLElement).getByRole("button", { name: "Sign in" }),
    );

    await waitFor(() => {
      expect(authState.signInWithPassword)
        .toHaveBeenCalledWith("pilot@example.test", "safe-password");
      expect(window.location.pathname).toBe("/");
    });
    expect(desktopInvoke).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: /Tune with evidence/i })).toBeVisible();
  });

  it("does not let a desktop-looking query turn a website page into a desktop callback", () => {
    window.history.replaceState(
      null,
      "",
      "/account/?source=desktop&mode=sign-in&returnTo=%2F",
    );

    renderSite();

    expect(document.querySelector('[data-auth-source="website"]')).toBeVisible();
    expect(screen.getByText(/each require an explicit Sign in click/i)).toBeVisible();
    expect(desktopInvoke).not.toHaveBeenCalled();
  });

  it("preserves an OAuth authorization identifier through website sign-in", async () => {
    const authorizationId = "authorization_1234567890abcdef";
    window.history.replaceState(null, "", oauthConsentPath(authorizationId));

    renderSite();

    await waitFor(() => expect(window.location.pathname).toBe("/account/"));
    const returnTo = new URLSearchParams(window.location.search).get("returnTo");
    expect(returnTo).toBe(oauthConsentPath(authorizationId));
    authState.signInWithPassword.mockImplementationOnce(async () => {
      authState.current = {
        configured: true,
        loading: false,
        account: {
          id: "user-1",
          email: "pilot@example.test",
          displayName: "Pilot",
          avatarUrl: null,
        },
      };
    });

    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "pilot@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "safe-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(window.location.pathname).toBe("/oauth/consent/");
      expect(new URLSearchParams(window.location.search).get("authorization_id"))
        .toBe(authorizationId);
    });
    expect(desktopInvoke).not.toHaveBeenCalled();
  });

  it("explains independent desktop authorization on the Chinese registration page", () => {
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    window.history.replaceState(
      null,
      "",
      "/account/?source=website&mode=register&returnTo=%2F",
    );

    renderSite();

    expect(screen.getByRole("heading", { name: "创建账号" })).toBeVisible();
    expect(screen.getByText(/都需要在各自应用内点击登录/)).toBeVisible();
    expect(screen.getByText(/都不会让任何桌面应用自动登录/)).toBeVisible();
    expect(document.querySelector('[data-auth-source="website"]')).toBeVisible();
  });
});
