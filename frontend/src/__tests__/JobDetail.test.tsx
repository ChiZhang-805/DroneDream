import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { JobDetail } from "../pages/JobDetail";
import { apiClient } from "../api/client";
import * as cloudModelAccess from "../features/settings/cloudModelAccess";
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
    control_version: 1,
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
    winner_evidence_id: "sha256:winner-evidence",
    winner_freeze_receipt_id: "wfr_test",
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
  vi.spyOn(apiClient, "listJobCandidates").mockResolvedValue({
    items: [],
    pareto_candidate_ids: [],
    recommendations: {},
    objective_directions: {},
  });
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
    expect(screen.getByRole("progressbar", { name: "Progress" })).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    await waitFor(() =>
      expect(apiClient.getJobReport).toHaveBeenCalledWith(job.id),
    );
  });

  it("labels a no-usable-candidate report as diagnostic instead of a recommendation", async () => {
    const job = makeJob({
      status: "COMPLETED",
      optimization_outcome: "no_usable_candidate",
      best_candidate_id: null,
    });
    const report = makeReport();
    report.best_candidate_id = "cand_baseline";
    report.best_parameters = { MPC_XY_P: 0.95 };
    report.winner_evidence_id = null;
    report.winner_freeze_receipt_id = null;
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(report);

    renderWithJob(job.id);

    expect(await screen.findByText("Diagnostic parameters")).toBeVisible();
    expect(screen.getByText("No validated winner")).toBeVisible();
    expect(screen.getByText(/not a validated recommendation/i)).toBeVisible();
    expect(screen.getByText(/no candidate passed the acceptance and evidence gates/i)).toBeVisible();
    expect(screen.queryByText("best-so-far summary text")).toBeNull();
    expect(screen.queryByText("Baseline winner")).toBeNull();
  });

  it("keeps a selected mock result readable without a real-simulator freeze receipt", async () => {
    const job = makeJob({ simulator_backend_requested: "mock" });
    const report = makeReport();
    report.winner_evidence_id = null;
    report.winner_freeze_receipt_id = null;
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(report);

    renderWithJob(job.id);

    expect(await screen.findByText("Best parameters")).toBeVisible();
    expect(screen.getByText("Optimizer winner")).toBeVisible();
    expect(screen.getByText("best-so-far summary text")).toBeVisible();
    expect(screen.queryByText("No validated winner")).toBeNull();
  });

  it("surfaces worst-case max error and incomplete holdout evidence", async () => {
    const job = makeJob({ status: "COMPLETED" });
    const report = makeReport();
    report.baseline_metrics.max_error_worst = 3.5;
    report.optimized_metrics.max_error_mean = 1.5;
    report.optimized_metrics.max_error_worst = 4.2;
    report.optimized_metrics.holdout = {
      validation_status: "incomplete",
      feasible: false,
      objective_feasible: true,
      trial_count: 4,
      completed_trial_count: 3,
      failed_trial_count: 1,
      passing_trial_count: 2,
      completion_rate: 0.75,
      failure_rate: 0.25,
      pass_rate: 0.5,
    };
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(report);

    renderWithJob(job.id);

    expect(await screen.findByText("4.20 m")).toBeInTheDocument();
    expect(screen.getByText(/Holdout validation: incomplete/i)).toBeInTheDocument();
    expect(screen.getByText(/3\/4 trials completed/)).toBeInTheDocument();
    expect(screen.getByText(/failure rate 25.0%/)).toBeInTheDocument();
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
        failure_code: null,
        failure_reason: null,
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
        failure_code: null,
        failure_reason: null,
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

  it("opens a completed passing trial for the best candidate before a failed one", async () => {
    const job = makeJob({ status: "COMPLETED" });
    const common = {
      candidate_id: "cand_best",
      seed: 1,
      scenario_type: "nominal" as const,
      candidate_label: "best",
      candidate_source_type: "optimizer" as const,
      candidate_is_baseline: false,
      candidate_is_best: true,
      candidate_generation_index: 1,
      failure_code: null,
      failure_reason: null,
    };
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([
      {
        ...common,
        id: "trial_failed_first",
        status: "FAILED",
        score: null,
        pass_flag: null,
      },
      {
        ...common,
        id: "trial_completed_pass",
        status: "COMPLETED",
        score: 0.2,
        pass_flag: true,
      },
    ]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findByRole("link", {
      name: "Open best trial replay",
    })).toHaveAttribute("href", "/trials/trial_completed_pass");
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
        failure_code: null,
        failure_reason: null,
      },
    ];
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue(trials);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findByText(/CMA-ES Gen 2/)).toBeInTheDocument();
  });

  it("renders the portfolio with a localized name and accuracy-first description", async () => {
    const job = makeJob({
      status: "COMPLETED",
      optimizer_strategy: "optimizer_portfolio",
    });
    const trials: TrialSummary[] = [
      {
        id: "tri_portfolio_1",
        candidate_id: "cand_portfolio_1",
        seed: 31,
        scenario_type: "nominal",
        status: "COMPLETED",
        score: 0.6,
        pass_flag: true,
        candidate_label: "optimizer_portfolio_gen_2",
        candidate_source_type: "optimizer",
        candidate_optimizer_strategy: "turbo",
        candidate_is_baseline: false,
        candidate_is_best: false,
        candidate_generation_index: 2,
        failure_code: null,
        failure_reason: null,
      },
    ];
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue(trials);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(
      await screen.findByText(/TuRBO-inspired trust-region BO · Gen 2/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Splits budget across six engines and favors verified gains/),
    ).toBeInTheDocument();
    expect(screen.queryByText("optimizer_portfolio")).toBeNull();
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
        failure_code: null,
        failure_reason: null,
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
        failure_code: null,
        failure_reason: null,
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
        failure_code: "SIMULATION_FAILED",
        failure_reason: "Simulator refused the trial.",
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

  it("creates a bounded continuation child only after explicit confirmation and a fresh managed grant", async () => {
    const budget = {
      additional_generation_cap: 4,
      additional_trial_cap: 80,
      additional_provider_turn_cap: 16,
      additional_time_budget_seconds: 3600,
    };
    const job = makeJob({
      status: "COMPLETED",
      optimizer_strategy: "llm_harness",
      llm_access_mode: "platform",
      llm_provider: "dronedream",
      completion_policy: "first_qualified_stop",
      job_kind: "primary",
      first_qualified_candidate_id: "cand_best",
      first_qualified_at: "2026-04-22T09:04:30Z",
      continue_exploration_requested: false,
      exploration_budget: budget,
      provider_turns_attempted: 5,
      provider_turns_succeeded: 5,
      provider_turn_cap: 32,
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());
    vi.spyOn(cloudModelAccess, "issueManagedModelGrant").mockResolvedValue({
      access_mode: "platform",
      grant: `ddg_${"B".repeat(48)}`,
      scope: "job",
      expires_at: "2026-07-29T12:00:00Z",
      max_calls: 16,
      gateway_base_url: "https://gateway.example.test",
      managed_model: "DroneDream Managed",
      usage: {
        plan: {
          id: "free", name: "Free", monthly_price_cny_fen: 0,
          included_ai_credits: 20, capability_set: "core-v1",
        },
        period: {
          starts_at: "2026-07-01T00:00:00Z",
          ends_at: "2026-08-01T00:00:00Z",
        },
        usage: {
          reserved_ai_credits: 0, consumed_ai_credits: 0,
          remaining_ai_credits: 20, request_count: 0,
          input_tokens: 0, output_tokens: 0, total_tokens: 0,
          estimated_request_count: 0, credit_policy_version: 1,
        },
        recent_requests: [],
      },
    });
    const continueSpy = vi.spyOn(apiClient, "continueExploration").mockResolvedValue({
      ...job,
      id: "job_child",
      job_kind: "continue_exploration",
      continuation_parent_job_id: job.id,
    });

    renderWithJob(job.id);
    fireEvent.click(await screen.findByRole("button", { name: /Continue exploring/i }));
    const dialog = screen.getByRole("dialog", { name: /Confirm a separate exploration job/i });
    expect(within(dialog).getByLabelText(/Extra generations/i)).toBeDisabled();
    const confirm = within(dialog).getByRole("button", { name: /Confirm and start exploration/i });
    expect(confirm).toBeDisabled();
    fireEvent.click(within(dialog).getByLabelText(/I understand the additional limits/i));
    fireEvent.click(confirm);

    await waitFor(() => expect(continueSpy).toHaveBeenCalledWith(
      job.id,
      job.control_version,
      {
        budget,
        llm: {
          access_mode: "platform",
          provider: "dronedream",
          api_key: null,
          platform_grant: `ddg_${"B".repeat(48)}`,
          model: null,
          base_url: null,
        },
      },
    ));
    expect(cloudModelAccess.issueManagedModelGrant).toHaveBeenCalledWith("job", job.id);
  });

  it("keeps the parent first-qualified result reachable from an exploration child", async () => {
    const job = makeJob({
      id: "job_child",
      job_kind: "continue_exploration",
      continuation_parent_job_id: "job_parent",
      completion_policy: "exploration_budget_stop",
      optimization_outcome: "exploration_no_improvement",
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    expect(await screen.findAllByText("Best validated after exploration")).not.toHaveLength(0);
    expect(screen.getByRole("link", { name: /Open first-qualified result/i })).toHaveAttribute(
      "href", "/jobs/job_parent",
    );
    expect(
      screen.getAllByText(/parent first-qualified result remains authoritative/i)[0],
    ).toBeVisible();
  });

  it("rerun for a BYOK job preserves its provider, model, and endpoint", async () => {
    const job = makeJob({
      status: "COMPLETED",
      optimizer_strategy: "gpt",
      llm_access_mode: "byok",
      llm_provider: "deepseek",
      llm_base_url: "https://api.deepseek.com/v1",
      openai_model: "deepseek-chat",
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());
    const rerunSpy = vi
      .spyOn(apiClient, "rerunJob")
      .mockResolvedValue({ ...job, id: "job_rerun_1" });
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("fresh-key");

    renderWithJob(job.id);

    fireEvent.click(await screen.findByRole("button", { name: /Rerun/i }));
    await waitFor(() =>
      expect(rerunSpy).toHaveBeenCalledWith(job.id, {
        llm: {
          access_mode: "byok",
          provider: "deepseek",
          api_key: "fresh-key",
          platform_grant: null,
          model: "deepseek-chat",
          base_url: "https://api.deepseek.com/v1",
        },
      }),
    );
    expect(promptSpy).toHaveBeenCalledWith(
      expect.stringContaining("deepseek"),
    );
  });

  it("rerun for managed access requests a fresh scoped grant without prompting", async () => {
    const job = makeJob({
      status: "COMPLETED",
      optimizer_strategy: "llm_harness",
      llm_access_mode: "platform",
      llm_provider: "dronedream",
      llm_base_url: "https://gateway.example.test",
      openai_model: "DroneDream Managed",
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());
    const rerunSpy = vi
      .spyOn(apiClient, "rerunJob")
      .mockResolvedValue({ ...job, id: "job_rerun_managed" });
    const promptSpy = vi.spyOn(window, "prompt");
    vi.spyOn(cloudModelAccess, "issueManagedModelGrant").mockResolvedValue({
      access_mode: "platform",
      grant: `ddg_${"A".repeat(48)}`,
      scope: "job",
      expires_at: "2026-07-29T12:00:00Z",
      max_calls: 1,
      gateway_base_url: "https://gateway.example.test",
      managed_model: "DroneDream Managed",
      usage: {
        plan: {
          id: "free",
          name: "Free",
          monthly_price_cny_fen: 0,
          included_ai_credits: 10,
          capability_set: "core-v1",
        },
        period: {
          starts_at: "2026-07-01T00:00:00Z",
          ends_at: "2026-08-01T00:00:00Z",
        },
        usage: {
          reserved_ai_credits: 0,
          consumed_ai_credits: 0,
          remaining_ai_credits: 10,
          request_count: 0,
          input_tokens: 0,
          output_tokens: 0,
          total_tokens: 0,
          estimated_request_count: 0,
          credit_policy_version: 1,
        },
        recent_requests: [],
      },
    });

    renderWithJob(job.id);

    fireEvent.click(await screen.findByRole("button", { name: /Rerun/i }));
    await waitFor(() =>
      expect(rerunSpy).toHaveBeenCalledWith(job.id, {
        llm: {
          access_mode: "platform",
          provider: "dronedream",
          api_key: null,
          platform_grant: `ddg_${"A".repeat(48)}`,
          model: null,
          base_url: null,
        },
      }),
    );
    expect(promptSpy).not.toHaveBeenCalled();
  });

  it("coalesces duplicate rerun requests while the first request is pending", async () => {
    const job = makeJob({
      status: "COMPLETED",
      optimizer_strategy: "heuristic",
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());
    let resolveRerun: ((value: Job) => void) | null = null;
    const rerunSpy = vi.spyOn(apiClient, "rerunJob").mockImplementation(
      () => new Promise((resolve) => {
        resolveRerun = resolve;
      }),
    );

    renderWithJob(job.id);
    const rerun = await screen.findByRole("button", { name: /Rerun/i });
    act(() => {
      rerun.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      rerun.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => expect(rerunSpy).toHaveBeenCalledTimes(1));
    await act(async () => {
      resolveRerun?.({ ...job, id: "job_rerun_once" });
    });
  });

  it("coalesces duplicate cancel requests while the first request is pending", async () => {
    const job = makeJob({
      status: "RUNNING",
      completed_at: null,
    });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    let resolveCancel: ((value: Job) => void) | null = null;
    const cancelSpy = vi.spyOn(apiClient, "cancelJob").mockImplementation(
      () => new Promise((resolve) => {
        resolveCancel = resolve;
      }),
    );

    renderWithJob(job.id);
    const cancel = await screen.findByRole("button", { name: /^Cancel$/i });
    act(() => {
      cancel.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      cancel.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => expect(cancelSpy).toHaveBeenCalledTimes(1));
    await act(async () => {
      resolveCancel?.({ ...job, status: "CANCELLED" });
    });
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
    fireEvent.click(button);
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

  it("performs one final trials and candidates refresh for a terminal job", async () => {
    const job = makeJob({ status: "COMPLETED" });
    vi.spyOn(apiClient, "getJob").mockResolvedValue(job);
    const trialsSpy = vi.spyOn(apiClient, "listJobTrials").mockResolvedValue([]);
    const candidatesSpy = vi.spyOn(apiClient, "listJobCandidates").mockResolvedValue({
      items: [],
      pareto_candidate_ids: [],
      recommendations: {},
      objective_directions: {},
    });
    vi.spyOn(apiClient, "listJobArtifacts").mockResolvedValue([]);
    vi.spyOn(apiClient, "getJobReport").mockResolvedValue(makeReport());

    renderWithJob(job.id);

    await waitFor(() => expect(trialsSpy).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(candidatesSpy).toHaveBeenCalledTimes(2));
  });
});
