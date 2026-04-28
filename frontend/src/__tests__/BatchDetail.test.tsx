import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { BatchDetail } from "../pages/BatchDetail";
import { apiClient } from "../api/client";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/batches/bat_1"]}>
        <Routes>
          <Route path="/batches/:batchId" element={<BatchDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BatchDetail", () => {
  it("renders child jobs table", async () => {
    vi.spyOn(apiClient, "getBatch").mockResolvedValue({
      id: "bat_1",
      name: "exp",
      description: null,
      status: "RUNNING",
      progress: {
        total_jobs: 2,
        completed_jobs: 1,
        failed_jobs: 0,
        cancelled_jobs: 0,
        running_jobs: 1,
        queued_jobs: 0,
        created_jobs: 0,
        terminal_jobs: 1,
      },
      created_at: "2026-01-01",
      updated_at: "2026-01-01",
      completed_at: null,
      cancelled_at: null,
    } as never);
    vi.spyOn(apiClient, "listBatchJobs").mockResolvedValue([
      { id: "job_1", status: "COMPLETED", track_type: "circle", objective_profile: "robust" },
      { id: "job_2", status: "RUNNING", track_type: "u_turn", objective_profile: "fast" },
    ] as never);

    renderPage();
    expect(await screen.findByText("job_1")).toBeInTheDocument();
    expect(screen.getByText("job_2")).toBeInTheDocument();
  });
});
