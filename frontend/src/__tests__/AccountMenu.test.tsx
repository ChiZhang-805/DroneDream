import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConsoleMemoryConsentRecord,
  ConsolePreferenceRecord,
} from "../features/settings/consolePreferences";

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

const preferenceMock = vi.hoisted(() => ({
  preferences: null as ConsolePreferenceRecord | null,
  consent: null as ConsoleMemoryConsentRecord | null,
  loadPreferences: vi.fn(async () => preferenceMock.preferences),
  loadMemoryConsent: vi.fn(async () => preferenceMock.consent),
  savePreferences: vi.fn(async (...args: [unknown, unknown]) => {
    void args;
  }),
  saveMemoryConsent: vi.fn(async (...args: [unknown, ConsoleMemoryConsentRecord]) => {
    preferenceMock.consent = args[1];
  }),
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

vi.mock("../features/settings/consolePreferences", async (importOriginal) => {
  const original = await importOriginal<typeof import("../features/settings/consolePreferences")>();
  return {
    ...original,
    loadConsolePreferences: preferenceMock.loadPreferences,
    loadConsoleMemoryConsent: preferenceMock.loadMemoryConsent,
    saveConsolePreferences: preferenceMock.savePreferences,
    saveConsoleMemoryConsent: preferenceMock.saveMemoryConsent,
  };
});

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";

function WorkspaceProbe() {
  const [count, setCount] = useState(0);
  return (
    <button type="button" onClick={() => setCount((current) => current + 1)}>
      Workspace count {count}
    </button>
  );
}

function renderApp() {
  const router = createMemoryRouter([
    {
      path: "/",
      element: <AppShell />,
      children: [{ index: true, element: <WorkspaceProbe /> }],
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
    preferenceMock.loadPreferences.mockClear();
    preferenceMock.loadMemoryConsent.mockClear();
    preferenceMock.savePreferences.mockClear();
    preferenceMock.saveMemoryConsent.mockClear();
    preferenceMock.preferences = null;
    preferenceMock.consent = null;
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("shows the authoritative remaining allowance and opens the Models & allowance workspace", async () => {
    const { router } = renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Workspace count 0" }));
    fireEvent.click(screen.getByRole("button", { name: "Account" }));

    const menu = screen.getByRole("menu", { name: "Account" });
    expect(await within(menu).findByText("12,000,000")).toBeVisible();
    expect(within(menu).getByText("Pro")).toBeVisible();
    expect(within(menu).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "12000000");

    fireEvent.click(within(menu).getByRole("menuitem", { name: /Remaining allowance/ }));
    const settings = screen.getByRole("region", { name: "Settings" });
    expect(within(settings).getByRole("tab", { name: "Models & allowance" })).toHaveAttribute("aria-selected", "true");
    const sevenDays = await within(settings).findByText("7 days");
    expect(sevenDays.closest("button")).toHaveAttribute("aria-selected", "true");
    fireEvent.click(within(settings).getByRole("tab", { name: "1 year" }));
    expect(within(settings).getByTestId("settings-allowance-chart")).toHaveClass("settings-allowance-heatmap");
    fireEvent.click(within(settings).getByRole("button", { name: "Back to app" }));
    expect(screen.queryByRole("region", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Workspace count 1" })).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Account" })).toHaveFocus());
    router.dispose();
  });

  it("keeps the header gear concise and routes All settings into the workspace", async () => {
    const { router } = renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const quickSettings = screen.getByRole("dialog", { name: "Quick settings" });
    expect(within(quickSettings).getByText("Language")).toBeVisible();
    expect(within(quickSettings).getByText("Appearance")).toBeVisible();
    expect(within(quickSettings).getByText("Account memory")).toBeVisible();
    expect(within(quickSettings).getByText("This edition's memory")).toBeVisible();
    expect(within(quickSettings).getByText("Default platform model")).toBeVisible();
    expect(within(quickSettings).queryByText("Chat preferences")).not.toBeInTheDocument();
    expect(within(quickSettings).queryByText("Default vehicle")).not.toBeInTheDocument();

    const accountMemory = within(quickSettings).getByRole("checkbox", { name: "Account memory" });
    await waitFor(() => expect(accountMemory).toBeEnabled());
    preferenceMock.savePreferences.mockClear();
    preferenceMock.saveMemoryConsent.mockClear();
    fireEvent.click(accountMemory);
    fireEvent.click(within(quickSettings).getByRole("button", { name: "All settings" }));
    const workspace = await screen.findByRole("region", { name: "Settings" });
    expect(within(workspace).getByRole("tab", { name: "General" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("dialog", { name: "Quick settings" })).not.toBeInTheDocument();
    await waitFor(() => expect(
      preferenceMock.saveMemoryConsent.mock.calls.some(([, consent]) => consent.memory_enabled),
    ).toBe(true));
    fireEvent.click(within(workspace).getByRole("tab", { name: "Memory" }));
    await waitFor(() => expect(
      within(workspace).getByRole("checkbox", { name: "Cross-session memory for this account" }),
    ).toBeChecked());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Settings" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Settings" })).toHaveFocus());
    router.dispose();
  });

  it("opens the full workspace even when a pending preference save is offline", async () => {
    const { router } = renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const quickSettings = screen.getByRole("dialog", { name: "Quick settings" });
    const accountMemory = within(quickSettings).getByRole("checkbox", { name: "Account memory" });
    await waitFor(() => expect(accountMemory).toBeEnabled());
    preferenceMock.savePreferences.mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(accountMemory);

    fireEvent.click(within(quickSettings).getByRole("button", { name: "All settings" }));

    const workspace = await screen.findByRole("region", { name: "Settings" });
    expect(within(workspace).getByRole("tab", { name: "General" }))
      .toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(preferenceMock.savePreferences).toHaveBeenCalled());
    router.dispose();
  });

  it("hands an unsaved memory draft to the full workspace after the navigation timeout", async () => {
    preferenceMock.consent = {
      memory_enabled: false,
      read_namespaces: [],
      write_namespaces: [],
      memory_scopes: {
        chat_preferences: true,
        experiment_defaults: true,
        device_vehicle: true,
        metrics_constraints: true,
        safety_approvals: true,
        workflow_tools: true,
        reports_delivery: true,
        collaboration_organization: true,
        files_artifacts: true,
      },
    };
    let releaseDelayedSave: (() => void) | undefined;
    const delayedSave = new Promise<void>((resolve) => {
      releaseDelayedSave = resolve;
    });
    preferenceMock.saveMemoryConsent.mockImplementationOnce(async (...args) => {
      await delayedSave;
      preferenceMock.consent = args[1];
    });

    const { router } = renderApp();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Settings" }));
      const quickSettings = screen.getByRole("dialog", { name: "Quick settings" });
      const accountMemory = within(quickSettings).getByRole("checkbox", { name: "Account memory" });
      const editionMemory = within(quickSettings).getByRole("checkbox", { name: "This edition's memory" });
      await waitFor(() => expect(accountMemory).toBeEnabled());

      fireEvent.click(accountMemory);
      expect(editionMemory).toBeEnabled();
      fireEvent.click(editionMemory);
      fireEvent.click(within(quickSettings).getByRole("button", { name: "All settings" }));

      const workspace = await screen.findByRole("region", { name: "Settings" });
      expect(preferenceMock.consent.memory_enabled).toBe(false);
      fireEvent.click(within(workspace).getByRole("tab", { name: "Memory" }));
      expect(within(workspace).getByRole("checkbox", {
        name: "Cross-session memory for this account",
      })).toBeChecked();
      expect(within(workspace).getByRole("checkbox", {
        name: "Allow this edition to use account memory",
      })).toBeChecked();
    } finally {
      releaseDelayedSave?.();
      router.dispose();
    }
  });

  it("lets remote memory settings win when All settings is opened before quick settings hydrate", async () => {
    const enabledScopes = {
      chat_preferences: true,
      experiment_defaults: true,
      device_vehicle: true,
      metrics_constraints: true,
      safety_approvals: true,
      workflow_tools: true,
      reports_delivery: true,
      collaboration_organization: true,
      files_artifacts: true,
    } as const;
    preferenceMock.preferences = {
      interface_locale: "en",
      appearance_mode: "system",
      custom_accent: "#e52a57",
      notifications: {},
      memory_enabled: true,
      memory_scopes: enabledScopes,
      defaults: {},
    };
    preferenceMock.consent = {
      memory_enabled: true,
      read_namespaces: [],
      write_namespaces: [],
      memory_scopes: enabledScopes,
    };
    let releaseQuickLoad: (() => void) | undefined;
    const quickLoad = new Promise<void>((resolve) => {
      releaseQuickLoad = resolve;
    });
    preferenceMock.loadPreferences.mockImplementationOnce(async () => {
      await quickLoad;
      return preferenceMock.preferences;
    });
    preferenceMock.loadMemoryConsent.mockImplementationOnce(async () => {
      await quickLoad;
      return preferenceMock.consent;
    });

    const { router } = renderApp();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Settings" }));
      const quickSettings = screen.getByRole("dialog", { name: "Quick settings" });
      expect(within(quickSettings).getByRole("checkbox", { name: "Account memory" }))
        .toBeDisabled();

      fireEvent.click(within(quickSettings).getByRole("button", { name: "All settings" }));

      const workspace = await screen.findByRole("region", { name: "Settings" });
      fireEvent.click(within(workspace).getByRole("tab", { name: "Memory" }));
      await waitFor(() => expect(within(workspace).getByRole("checkbox", {
        name: "Cross-session memory for this account",
      })).toBeChecked());
      expect(within(workspace).getByRole("checkbox", {
        name: "Allow this edition to use account memory",
      })).toBeChecked();
    } finally {
      releaseQuickLoad?.();
      router.dispose();
    }
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
