import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiClient } from "../api/client";
import { I18nProvider } from "../i18n/I18nProvider";
import { Dashboard } from "../pages/Dashboard";

describe("Dashboard availability", () => {
  afterEach(() => {
    vi.restoreAllMocks();
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

    expect(await screen.findByText("Runtime data is not available yet"))
      .toBeVisible();
    expect(screen.getByText("Status summary")).toBeVisible();
    expect(screen.getByText("Recent jobs")).toBeVisible();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
    queryClient.clear();
  });
});
