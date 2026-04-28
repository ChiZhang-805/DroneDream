import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { JobCompare } from "../pages/JobCompare";
import { apiClient } from "../api/client";

describe("JobCompare page", () => {
  it("renders comparison table and CSV button", async () => {
    vi.spyOn(apiClient, "compareJobs").mockResolvedValue({
      items: [
        {
          job_id: "job_1",
          status: "COMPLETED",
          track_type: "circle",
          simulator_backend: "mock",
          optimizer_strategy: "heuristic",
          optimization_outcome: "success",
          baseline_metrics: { rmse: 1.2, max_error: 2.1 },
          optimized_metrics: { rmse: 0.9, max_error: 1.8 },
          best_candidate_id: "cand_1",
          best_parameters: {},
          trial_count: 10,
          completed_trial_count: 10,
          failed_trial_count: 0,
          created_at: "2026-01-01",
          completed_at: "2026-01-01",
        },
        {
          job_id: "job_2",
          status: "RUNNING",
          track_type: "circle",
          simulator_backend: "real_cli",
          optimizer_strategy: "gpt",
          optimization_outcome: null,
          baseline_metrics: null,
          optimized_metrics: null,
          best_candidate_id: null,
          best_parameters: {},
          trial_count: 2,
          completed_trial_count: 1,
          failed_trial_count: 0,
          created_at: "2026-01-01",
          completed_at: null,
        },
      ],
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/compare?job_ids=job_1,job_2"]}>
          <Routes><Route path="/compare" element={<JobCompare />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("job_1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download CSV/i })).toBeInTheDocument();
  });
});
