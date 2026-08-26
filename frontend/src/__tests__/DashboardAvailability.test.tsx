import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const authState = vi.hoisted(() => ({
  configured: false,
  loading: false,
  account: null as { id: string } | null,
}));

vi.mock("../features/auth/AuthContext", () => ({
  useAuthOrLocal: () => authState,
}));

import { ApiClientError, apiClient } from "../api/client";
import { I18nProvider } from "../i18n/I18nProvider";
import { Dashboard } from "../pages/Dashboard";

describe("Dashboard availability", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    authState.configured = false;
    authState.loading = false;
    authState.account = null;
    window.localStorage.clear();
  });

  it("keeps the dashboard usable when the local backend is temporarily offline", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    vi.spyOn(apiClient, "listJobs").mockRejectedValue(
      new ApiClientError("NETWORK_ERROR", "Failed to fetch", null, 0),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <Dashboard />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nProvider>,
    );

    expect(await screen.findByText("Runtime disconnected"))
      .toBeVisible();
    expect(screen.getByText("Status summary")).toBeVisible();
    expect(screen.getByText("Recent jobs")).toBeVisible();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
    queryClient.clear();
  });

  it("waits for desktop account adoption before issuing protected dashboard requests", async () => {
    authState.configured = true;
    authState.account = null;
    const listJobs = vi.spyOn(apiClient, "listJobs").mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const dashboard = () => (
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <Dashboard />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nProvider>
    );
    const rendered = render(dashboard());

    await Promise.resolve();
    expect(listJobs).not.toHaveBeenCalled();

    authState.account = { id: "desktop-account" };
    rendered.rerender(dashboard());
    await waitFor(() => expect(listJobs).toHaveBeenCalled());
    queryClient.clear();
  });
});
