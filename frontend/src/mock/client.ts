// Mock API client for Phase 1. This is the *only* layer in the frontend that
// produces job/trial/report data. UI code imports from here instead of calling
// real HTTP endpoints so that Phase 2 can replace the implementation with a
// real `/api/v1` client (fetch/axios) without touching pages or components.
//
// The shapes returned here mirror docs/04_API_SPEC.md §7–9 exactly.

import type {
  ApiEnvelope,
  Job,
  JobCreateRequest,
  JobReport,
  JobStatus,
  PaginatedJobs,
  Trial,
  TrialSummary,
} from "../types/api";
import {
  MOCK_JOBS,
  MOCK_REPORTS,
  MOCK_TRIALS,
  toTrialSummary,
} from "./fixtures";

export class MockApiError extends Error {
  readonly code: string;
  readonly details: unknown;

  constructor(code: string, message: string, details: unknown = null) {
    super(message);
    this.name = "MockApiError";
    this.code = code;
    this.details = details;
  }
}

// Working, in-memory copy so create/cancel/rerun calls during a session feel
// real. Each page load resets back to MOCK_JOBS — Phase 2 replaces this.
const jobStore: Job[] = MOCK_JOBS.map((j) => ({ ...j }));
const trialStore: Record<string, Trial[]> = Object.fromEntries(
  Object.entries(MOCK_TRIALS).map(([k, v]) => [k, v.map((t) => ({ ...t }))]),
);
const reportStore: Record<string, JobReport> = Object.fromEntries(
  Object.entries(MOCK_REPORTS).map(([k, v]) => [k, { ...v }]),
);

// Simulated network latency. Isolated here so components stay clean.
const NETWORK_DELAY_MS = 250;

function delay(ms = NETWORK_DELAY_MS): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function envelopeSuccess<T>(data: T): ApiEnvelope<T> {
  return { success: true, data, error: null };
}

function envelopeError<T>(
  code: string,
  message: string,
  details: unknown = null,
): ApiEnvelope<T> {
  return { success: false, data: null, error: { code, message, details } };
}

async function unwrap<T>(envelope: ApiEnvelope<T>): Promise<T> {
  await delay();
  if (!envelope.success) {
    throw new MockApiError(
      envelope.error.code,
      envelope.error.message,
      envelope.error.details,
    );
  }
  return envelope.data;
}

function nowIso(): string {
  return new Date().toISOString();
}

function nextJobId(): string {
  // Stable-ish, monotonic mock id.
  return `job_mock_${Date.now().toString(36)}`;
}

function validateCreate(req: JobCreateRequest): string | null {
  if (req.altitude_m < 1.0 || req.altitude_m > 20.0) {
    return "altitude_m must be between 1.0 and 20.0";
  }
  for (const v of [
    req.wind.north,
    req.wind.east,
    req.wind.south,
    req.wind.west,
  ]) {
    if (v < -10 || v > 10) {
      return "wind components must be between -10 and 10";
    }
  }
  return null;
}

export const mockApi = {
  // POST /api/v1/jobs
  async createJob(req: JobCreateRequest): Promise<Job> {
    const validationError = validateCreate(req);
    if (validationError) {
      return unwrap<Job>(
        envelopeError("INVALID_INPUT", validationError),
      );
    }
    const id = nextJobId();
    const created: Job = {
      id,
      track_type: req.track_type,
      start_point: { ...req.start_point },
      altitude_m: req.altitude_m,
      wind: { ...req.wind },
      sensor_noise_level: req.sensor_noise_level,
      objective_profile: req.objective_profile,
      status: "QUEUED",
      progress: {
        completed_trials: 0,
        total_trials: 12,
        current_phase: "queued",
      },
      baseline_candidate_id: null,
      best_candidate_id: null,
      source_job_id: null,
      latest_error: null,
      created_at: nowIso(),
      updated_at: nowIso(),
      queued_at: nowIso(),
      started_at: null,
      completed_at: null,
      cancelled_at: null,
      failed_at: null,
      recent_events: [],
      simulator_backend_requested: req.simulator_backend ?? "mock",
      optimizer_strategy: req.optimizer_strategy ?? "heuristic",
      max_iterations: req.max_iterations ?? 5,
      trials_per_candidate: req.trials_per_candidate ?? 3,
      acceptance_criteria: req.acceptance_criteria ?? {
        target_rmse: 0.5,
        target_max_error: null,
        min_pass_rate: 0.8,
      },
      current_generation: 0,
      optimization_outcome: null,
      openai_model: req.openai?.model ?? null,
    };
    jobStore.unshift(created);
    return unwrap(envelopeSuccess(created));
  },

  // GET /api/v1/jobs
  async listJobs(params?: {
    page?: number;
    page_size?: number;
    status?: JobStatus;
  }): Promise<PaginatedJobs> {
    const page = params?.page ?? 1;
    const pageSize = params?.page_size ?? 20;
    const filtered = params?.status
      ? jobStore.filter((j) => j.status === params.status)
      : jobStore.slice();
    const start = (page - 1) * pageSize;
    const items = filtered.slice(start, start + pageSize);
    return unwrap(
      envelopeSuccess({
        items,
        page,
        page_size: pageSize,
        total: filtered.length,
      }),
    );
  },

  // GET /api/v1/jobs/{job_id}
  async getJob(jobId: string): Promise<Job> {
    const job = jobStore.find((j) => j.id === jobId);
    if (!job) {
      return unwrap<Job>(
        envelopeError("JOB_NOT_FOUND", `Job ${jobId} was not found.`),
      );
    }
    return unwrap(envelopeSuccess(job));
  },

  // GET /api/v1/jobs/{job_id}/trials
  async listJobTrials(jobId: string): Promise<TrialSummary[]> {
    const trials = trialStore[jobId];
    if (!trials) {
      return unwrap(envelopeSuccess<TrialSummary[]>([]));
    }
    return unwrap(envelopeSuccess(trials.map(toTrialSummary)));
  },

  // GET /api/v1/trials/{trial_id}
  async getTrial(trialId: string): Promise<Trial> {
    for (const trials of Object.values(trialStore)) {
      const t = trials.find((x) => x.id === trialId);
      if (t) {
        return unwrap(envelopeSuccess(t));
      }
    }
    return unwrap<Trial>(
      envelopeError("TRIAL_NOT_FOUND", `Trial ${trialId} was not found.`),
    );
  },

  // GET /api/v1/jobs/{job_id}/report
  async getJobReport(jobId: string): Promise<JobReport> {
    const report = reportStore[jobId];
    if (!report) {
      return unwrap<JobReport>(
        envelopeError(
          "REPORT_NOT_READY",
          `Report for job ${jobId} is not ready yet.`,
        ),
      );
    }
    return unwrap(envelopeSuccess(report));
  },

  // POST /api/v1/jobs/{job_id}/cancel
  async cancelJob(jobId: string): Promise<Job> {
    const job = jobStore.find((j) => j.id === jobId);
    if (!job) {
      return unwrap<Job>(
        envelopeError("JOB_NOT_FOUND", `Job ${jobId} was not found.`),
      );
    }
    if (
      job.status === "COMPLETED" ||
      job.status === "FAILED" ||
      job.status === "CANCELLED"
    ) {
      return unwrap<Job>(
        envelopeError(
          "JOB_ALREADY_COMPLETED",
          `Job ${jobId} is already in terminal state ${job.status}.`,
        ),
      );
    }
    job.status = "CANCELLED";
    job.cancelled_at = nowIso();
    job.updated_at = nowIso();
    return unwrap(envelopeSuccess(job));
  },
};

export type MockApi = typeof mockApi;
