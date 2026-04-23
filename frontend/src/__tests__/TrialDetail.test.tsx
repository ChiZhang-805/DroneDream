import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TrialDetail } from "../pages/TrialDetail";
import { apiClient } from "../api/client";
import type { Artifact, Trial } from "../types/api";

function makeTrial(overrides: Partial<Trial> = {}): Trial {
  return {
    id: "trial_rc_1",
    job_id: "job_rc_1",
    candidate_id: "cand_rc_1",
    seed: 7,
    scenario_type: "nominal",
    status: "COMPLETED",
    score: 0.42,
    pass_flag: true,
    candidate_label: "opt_v1",
    candidate_source_type: "optimizer",
    candidate_is_baseline: false,
    candidate_is_best: true,
    candidate_generation_index: 1,
    attempt_count: 1,
    worker_id: "worker-1",
    simulator_backend: "real_cli",
    failure_code: null,
    failure_reason: null,
    log_excerpt: null,
    metrics: {
      rmse: 0.3,
      max_error: 0.9,
      overshoot_count: 1,
      completion_time: 32.5,
      crash_flag: false,
      timeout_flag: false,
      score: 0.42,
      final_error: 0.1,
      pass_flag: true,
      instability_flag: false,
    },
    queued_at: "2026-04-22T09:00:00Z",
    started_at: "2026-04-22T09:00:05Z",
    finished_at: "2026-04-22T09:00:40Z",
    ...overrides,
  };
}

function renderTrial(trialId: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/trials/${trialId}`]}>
        <Routes>
          <Route path="/trials/:trialId" element={<TrialDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("TrialDetail artifacts — Phase 8 polish", () => {
  it("shows real_cli trial-level artifacts filtered by owner_type+owner_id", async () => {
    const trial = makeTrial();
    const artifacts: Artifact[] = [
      {
        id: "art_trial_traj",
        owner_type: "trial",
        owner_id: trial.id,
        artifact_type: "trajectory_plot",
        display_name: "Trajectory plot",
        storage_path:
          "/home/ubuntu/repos/DroneDream/.artifacts/trial_rc_1/trajectory.png",
        mime_type: "image/png",
        file_size_bytes: 1234,
        created_at: "2026-04-22T09:00:40Z",
      },
      {
        id: "art_trial_telem",
        owner_type: "trial",
        owner_id: trial.id,
        artifact_type: "telemetry_json",
        display_name: "Telemetry",
        storage_path:
          "/home/ubuntu/repos/DroneDream/.artifacts/trial_rc_1/telemetry.json",
        mime_type: "application/json",
        file_size_bytes: 5678,
        created_at: "2026-04-22T09:00:40Z",
      },
      {
        id: "art_other_trial",
        owner_type: "trial",
        owner_id: "trial_other_2",
        artifact_type: "trajectory_plot",
        display_name: "Other trial's trajectory plot",
        storage_path:
          "/home/ubuntu/repos/DroneDream/.artifacts/trial_other_2/trajectory.png",
        mime_type: "image/png",
        file_size_bytes: 2222,
        created_at: "2026-04-22T09:01:00Z",
      },
      {
        id: "art_job_report",
        owner_type: "job",
        owner_id: trial.job_id,
        artifact_type: "pdf_report",
        display_name: "Job report",
        storage_path: "mock://reports/job_rc_1.pdf",
        mime_type: "application/pdf",
        file_size_bytes: 10_000,
        created_at: "2026-04-22T09:01:10Z",
      },
    ];

    vi.spyOn(apiClient, "getTrial").mockResolvedValue(trial);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue(artifacts);

    renderTrial(trial.id);

    await waitFor(() =>
      expect(screen.getByText("Trajectory plot")).toBeInTheDocument(),
    );
    // Trial-level artifacts for this trial are shown.
    expect(screen.getByText("Telemetry")).toBeInTheDocument();
    // Trial artifacts for other trials are NOT shown here.
    expect(
      screen.queryByText("Other trial's trajectory plot"),
    ).not.toBeInTheDocument();
    // Job-level artifacts are still surfaced under a separate heading.
    expect(screen.getByText("Job report")).toBeInTheDocument();
    // Section headings reflect the new split.
    expect(screen.getByText(/Trial artifacts \(2\)/)).toBeInTheDocument();
    expect(screen.getByText(/Job artifacts \(1\)/)).toBeInTheDocument();
    // Stale "mock-only" wording must be gone for real_cli trials.
    expect(screen.queryByText(/mock-only/i)).not.toBeInTheDocument();
  });

  it("keeps the mock-simulator note on trials with no real_cli artifacts", async () => {
    const trial = makeTrial({ simulator_backend: "mock" });
    const artifacts: Artifact[] = [
      {
        id: "art_job_only",
        owner_type: "job",
        owner_id: trial.job_id,
        artifact_type: "pdf_report",
        display_name: "Job report",
        storage_path: "mock://reports/job_rc_1.pdf",
        mime_type: "application/pdf",
        file_size_bytes: 10_000,
        created_at: "2026-04-22T09:01:10Z",
      },
    ];

    vi.spyOn(apiClient, "getTrial").mockResolvedValue(trial);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue(artifacts);

    renderTrial(trial.id);

    await waitFor(() =>
      expect(
        screen.getByText(
          /The mock simulator does not produce per-trial artifact files/i,
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Job report")).toBeInTheDocument();
  });
});
