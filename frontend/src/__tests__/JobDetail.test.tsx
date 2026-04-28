import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { JobDetail } from "../pages/JobDetail";
import { apiClient } from "../api/client";
import type { Artifact, Job, JobReport, TrialSummary } from "../types/api";

const PHASE8_DEFAULTS = {
  simulator_backend_requested: "mock" as const,
  optimizer_strategy: "gpt" as const,
  max_iterations: 20,
  trials_per_candidate: 3,
  acceptance_criteria: {
    target_rmse: 0.5,
    target_max_error: null,
    min_pass_rate: 0.8,
  },
  current_generation: 0,
  optimization_outcome: null,
  openai_model: null,
};

function makeJob(overrides: Partial<Job>): Job {
  const base: Job = {
    id: "job_test_1",
    track_type: "circle",
    reference_track: null,
    start_point: { x: 0, y: 0 },
    altitude_m: 3,
    wind: { north: 0, east: 0, south: 0, west: 0 },
    sensor_noise_level: "medium",
    objective_profile: "robust",
    status: "COMPLETED",
    progress: {
      completed_trials: 13,
      total_trials: 13,
      current_phase: "completed",
    },
    baseline_candidate_id: "cand_baseline",
    best_candidate_id: "cand_best",
    source_job_id: null,
    latest_error: null,
    created_at: "2026-04-22T09:00:00Z",
    updated_at: "2026-04-22T09:05:00Z",
    queued_at: "2026-04-22T09:00:10Z",
    started_at: "2026-04-22T09:00:20Z",
    completed_at: "2026-04-22T09:05:00Z",
    cancelled_at: null,
    failed_at: null,
    recent_events: [],
    ...PHASE8_DEFAULTS,
    ...overrides,
  };
  return base;
}

function makeReport(): JobReport {
  return {
    job_id: "job_test_1",
    best_candidate_id: "cand_best",
    summary_text: "best-so-far summary text",
    baseline_metrics: {
      rmse: 1.2,
      max_error: 2.0,
      overshoot_count: 3,
      completion_time: 9.0,
      score: 4.2,
    },
    optimized_metrics: {
      rmse: 0.9,
      max_error: 1.5,
      overshoot_count: 2,
      completion_time: 8.0,
      score: 3.0,
    },
    comparison: [
      {
        metric: "rmse",
        label: "RMSE",
        baseline: 1.2,
        optimized: 0.9,
        lower_is_better: true,
        unit: "m",
      },
    ],
    best_parameters: {
      kp_xy: 1.1,
      kd_xy: 0.21,
      ki_xy: 0.05,
      vel_limit: 5.0,
      accel_limit: 4.0,
      disturbance_rejection: 0.5,
    },
    report_status: "READY",
    created_at: "2026-04-22T09:05:00Z",
    updated_at: "2026-04-22T09:05:00Z",
  };
}

function renderWithJob(jobId: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/jobs/${jobId}`]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("JobDetail — Phase 8 best-so-far rendering", () => {
  it("shows custom track count and preview when track_type=custom", async () => {
    const job = makeJob({
      track_type: "custom",
      reference_track: [
        { x: 0, y: 0, z: 3 },
        { x: 5, y: 0, z: 3 },
        { x: 5, y: 5, z: 3 },
      ],
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findByText(/3 points/i)).toBeInTheDocument();
    expect(screen.getByText(/\[\{"x":0,"y":0,"z":3\}/)).toBeInTheDocument();
  });

  it("renders best-so-far metrics and a budget-exhausted banner for COMPLETED+READY report", async () => {
    const job = makeJob({
      status: "COMPLETED",
      latest_error: null,
      optimization_outcome: "max_iterations_reached",
      optimizer_strategy: "gpt",
      openai_model: "gpt-4.1",
      best_candidate_id: "cand_best",
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(
      await screen.findByText(
        /Search budget exhausted — showing best-so-far parameters/i,
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(apiClient.getJobReport).toHaveBeenCalledWith(job.id),
    );
  });

  it("labels llm_optimizer rows as 'GPT Gen N' and heuristic as 'Heuristic #N'", async () => {
    const job = makeJob({ status: "COMPLETED", optimizer_strategy: "gpt" });
    const trials: TrialSummary[] = [
      {
        id: "tri_llm_1",
        candidate_id: "cand_llm_1",
        seed: 11,
        scenario_type: "nominal",
        status: "COMPLETED",
        score: 0.9,
        pass_flag: true,
        candidate_label: "llm_v1",
        candidate_source_type: "llm_optimizer",
        candidate_is_baseline: false,
        candidate_is_best: true,
        candidate_generation_index: 2,
      },
      {
        id: "tri_heur_1",
        candidate_id: "cand_heur_1",
        seed: 12,
        scenario_type: "nominal",
        status: "COMPLETED",
        score: 1.1,
        pass_flag: true,
        candidate_label: "heur_v1",
        candidate_source_type: "optimizer",
        candidate_is_baseline: false,
        candidate_is_best: false,
        candidate_generation_index: 1,
      },
    ];
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue(trials);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findByText(/GPT Gen 2/)).toBeInTheDocument();
    expect(screen.getByText(/Heuristic #1/)).toBeInTheDocument();
    // Best badge still appears for the llm_optimizer row.
    expect(screen.getByText("Best")).toBeInTheDocument();
    // The llm_optimizer row is NOT mislabeled as Baseline.
    expect(screen.queryByText(/Baseline$/)).toBeNull();
  });

  it("labels cma_es optimizer rows as 'CMA-ES Gen N'", async () => {
    const job = makeJob({ status: "COMPLETED", optimizer_strategy: "cma_es" });
    const trials: TrialSummary[] = [
      {
        id: "tri_cma_1",
        candidate_id: "cand_cma_1",
        seed: 21,
        scenario_type: "nominal",
        status: "COMPLETED",
        score: 0.7,
        pass_flag: true,
        candidate_label: "cma_es_gen_2",
        candidate_source_type: "optimizer",
        candidate_is_baseline: false,
        candidate_is_best: false,
        candidate_generation_index: 2,
      },
    ];
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue(trials);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findByText(/CMA-ES Gen 2/)).toBeInTheDocument();
  });

  it("renders a PASS/FAIL badge per completed trial based on pass_flag", async () => {
    const job = makeJob({ status: "COMPLETED" });
    const trials: TrialSummary[] = [
      {
        id: "tri_pass",
        candidate_id: "cand_base",
        seed: 1,
        scenario_type: "nominal",
        status: "COMPLETED",
        score: 0.4,
        pass_flag: true,
        candidate_label: "baseline",
        candidate_source_type: "baseline",
        candidate_is_baseline: true,
        candidate_is_best: false,
        candidate_generation_index: 0,
      },
      {
        id: "tri_fail",
        candidate_id: "cand_opt",
        seed: 2,
        scenario_type: "wind_perturbed",
        status: "COMPLETED",
        score: 0.7,
        // Phase 8 polish: trial executed successfully (status=COMPLETED) but
        // did not satisfy per-trial acceptance (pass_flag=false). The PASS
        // column must surface this without opening Trial Detail.
        pass_flag: false,
        candidate_label: "opt_v1",
        candidate_source_type: "optimizer",
        candidate_is_baseline: false,
        candidate_is_best: true,
        candidate_generation_index: 1,
      },
      {
        id: "tri_nometric",
        candidate_id: "cand_opt",
        seed: 3,
        scenario_type: "nominal",
        status: "FAILED",
        score: null,
        pass_flag: null,
        candidate_label: "opt_v1",
        candidate_source_type: "optimizer",
        candidate_is_baseline: false,
        candidate_is_best: false,
        candidate_generation_index: 1,
      },
    ];
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue(trials);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findByText("PASS")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    // Trials with no metric render a dash in the Pass column.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows the classic failure banner when FAILED job has no report", async () => {
    const job = makeJob({
      status: "FAILED",
      latest_error: {
        code: "ALL_TRIALS_FAILED",
        message: "All trials failed.",
      },
      optimization_outcome: null,
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockRejectedValue(
      new Error("JOB_FAILED"),
    );

    renderWithJob(job.id);

    expect(await screen.findByText("Job failed")).toBeInTheDocument();
    expect(screen.getByText(/ALL_TRIALS_FAILED/)).toBeInTheDocument();
    expect(
      screen.queryByText(/Best-so-far: Baseline vs Optimized/i),
    ).not.toBeInTheDocument();
  });

  it("rerun for gpt asks for a fresh OpenAI key and stays gpt-based", async () => {
    const job = makeJob({ status: "COMPLETED", optimizer_strategy: "gpt" });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());
    const rerunSpy = vi
      .spyOn(apiClient, "rerunJob")
      .mockResolvedValue({ ...job, id: "job_rerun_1" });
    vi.spyOn(window, "prompt").mockReturnValue("sk-rerun");

    renderWithJob(job.id);

    fireEvent.click(await screen.findByRole("button", { name: /Rerun/i }));
    await waitFor(() =>
      expect(rerunSpy).toHaveBeenCalledWith(job.id, {
        openai: { api_key: "sk-rerun", model: null },
      }),
    );
  });

  it("renders artifact cards for long paths with grouped sections", async () => {
    const job = makeJob({ status: "COMPLETED" });
    const artifacts: Artifact[] = [
      {
        id: "art_long",
        owner_type: "job",
        owner_id: job.id,
        artifact_type: "report_json",
        display_name: "Job report",
        storage_path:
          "/workspace/dd_artifacts/jobs/job_xxx/job_artifacts/really/very/long/path/report.json",
        mime_type: "application/json",
        file_size_bytes: 200,
        created_at: "2026-04-22T09:05:00Z",
      },
    ];
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue(artifacts);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findByText(/Job artifacts \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("report.json")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy path/i })).toBeInTheDocument();
    expect(screen.getByTestId("artifact-grid")).toBeInTheDocument();
  });

  it("shows top Download PDF report button when pdf artifact exists", async () => {
    const job = makeJob({ status: "COMPLETED" });
    const artifacts: Artifact[] = [
      {
        id: "art_pdf",
        owner_type: "job",
        owner_id: job.id,
        artifact_type: "pdf_report",
        display_name: `${job.id} report.pdf`,
        storage_path: `/workspace/dd_artifacts/jobs/${job.id}/reports/${job.id} report.pdf`,
        mime_type: "application/pdf",
        file_size_bytes: 1024,
        created_at: "2026-04-22T09:05:00Z",
      },
    ];
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue(artifacts);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    const downloadSpy = vi.spyOn(apiClient, "downloadArtifact").mockResolvedValue();
    const button = await screen.findByRole("button", { name: /download pdf report/i });
    button.click();
    expect(downloadSpy).toHaveBeenCalledWith("art_pdf", `${job.id} report.pdf`);
  });

  it("does not show top Download PDF report button when no pdf artifact", async () => {
    const job = makeJob({ status: "COMPLETED" });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);
    await screen.findByText(/Baseline vs Optimized comparison/i);
    expect(screen.queryByRole("button", { name: /download pdf report/i })).toBeNull();
  });
});
