import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  signOut: vi.fn(async () => undefined),
  account: {
    id: "account-menu-user",
    email: "pilot@example.test",
    displayName: "Pilot",
    avatarUrl: "https://example.test/avatar.jpg",
  },
}));

const usageMock = vi.hoisted(() => ({
  get: vi.fn(async () => ({
    plan: {
      id: "pro",
      name: "Pro",
      monthly_price_cny_fen: 19_900,
      included_ai_credits: 15_000_000,
      capability_set: "pro-v1",
    },
    period: {
      starts_at: "2026-08-01T08:12:00Z",
      ends_at: "2026-08-31T08:12:00Z",
    },
    usage: {
      reserved_ai_credits: 0,
      consumed_ai_credits: 3_000_000,
      remaining_ai_credits: 12_000_000,
      request_count: 12,
      input_tokens: 900,
      output_tokens: 300,
      total_tokens: 1_200,
      estimated_request_count: 0,
      credit_policy_version: 1,
    },
    recent_requests: [],
    daily_usage: Array.from({ length: 365 }, (_, index) => ({
      date: new Date(Date.UTC(2025, 7, 23 + index)).toISOString().slice(0, 10),
      consumed_ai_credits: index % 7 === 0 ? 120 : 24,
      request_count: index % 4,
      input_tokens: index * 10,
      output_tokens: index * 4,
      total_tokens: index * 14,
    })),
  })),
}));

vi.mock("../features/auth/AuthContext", async (importOriginal) => {
  const original = await importOriginal<typeof import("../features/auth/AuthContext")>();
  const unavailable = async () => undefined;
  return {
    ...original,
    AuthProvider: ({ children }: { children: ReactNode }) => children,
    useAuth: () => ({
      configured: true,
      loading: false,
      account: authMock.account,
      googleEnabled: false,
      appleEnabled: false,
      signInWithPassword: unavailable,
      sendRegistrationCode: unavailable,
      verifyRegistrationCode: unavailable,
      signInWithProvider: unavailable,
      updateDisplayName: unavailable,
      updateAvatar: unavailable,
      signOut: authMock.signOut,
    }),
  };
});

vi.mock("../features/settings/cloudModelAccess", async (importOriginal) => {
  const original = await importOriginal<typeof import("../features/settings/cloudModelAccess")>();
  return {
    ...original,
    getManagedModelUsage: usageMock.get,
    getManagedModelCatalog: vi.fn(async () => ({
      schema_version: "dronedream.managed-model-catalog.v1",
      models: original.DEFAULT_MANAGED_MODEL_CATALOG,
    })),
  };
});

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";

function renderApp() {
  const router = createMemoryRouter([
    {
      path: "/",
      element: <AppShell />,
      children: [{ index: true, element: <div>Workspace</div> }],
    },
  ]);
  const page = render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { ...page, router };
}

describe("sidebar account menu", () => {
  beforeEach(() => {
    window.localStorage.setItem("drone-dream:locale", "en");
    usageMock.get.mockClear();
    authMock.signOut.mockClear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("shows the authoritative remaining allowance and opens the Model settings tab", async () => {
    const { router } = renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Account" }));

    const menu = screen.getByRole("menu", { name: "Account" });
    expect(await within(menu).findByText("12,000,000")).toBeVisible();
    expect(within(menu).getByText("Pro")).toBeVisible();
    expect(within(menu).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "12000000");

    fireEvent.click(within(menu).getByRole("menuitem", { name: /Remaining allowance/ }));
    const settings = screen.getByRole("dialog", { name: "Settings" });
    expect(within(settings).getByRole("tab", { name: "Model" })).toHaveAttribute("aria-selected", "true");
    const sevenDays = await within(settings).findByText("7 days");
    expect(sevenDays.closest("button")).toHaveAttribute("aria-selected", "true");
    fireEvent.click(within(settings).getByRole("tab", { name: "1 year" }));
    expect(within(settings).getByTestId("settings-allowance-chart")).toHaveClass("settings-allowance-heatmap");
    router.dispose();
  });

  it("opens profile editing from the avatar row and signs out from the menu", async () => {
    const { router } = renderApp();
    const account = screen.getByRole("button", { name: "Account" });
    fireEvent.click(account);
    fireEvent.click(screen.getByRole("menuitem", { name: /Pilot/ }));
    const dialog = screen.getByRole("dialog", { name: "DroneDream account" });
    expect(dialog).toBeVisible();
    expect(within(dialog).getAllByRole("button", { name: "Choose from computer" }))
      .toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Close account" }));
    await waitFor(() => expect(account).toHaveFocus());
    fireEvent.click(account);
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(authMock.signOut).toHaveBeenCalledTimes(1));
    router.dispose();
  });
});
