// Real HTTP client for the DroneDream /api/v1 backend. Pages and components
// use this module instead of the Phase 1 mock client. The call surface matches
// the mock client deliberately so swapping was a one-line import change.

import type {
  ApiEnvelope,
  Artifact,
  Job,
  JobCreateRequest,
  JobRerunRequest,
  JobReport,
  JobStatus,
  PaginatedJobs,
  Trial,
  TrialSummary,
} from "../types/api";

export class ApiClientError extends Error {
  readonly code: string;
  readonly details: unknown;
  readonly httpStatus: number;

  constructor(
    code: string,
    message: string,
    details: unknown = null,
    httpStatus = 0,
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.details = details;
    this.httpStatus = httpStatus;
  }
}

// Vite injects import.meta.env at build time. Falls back to the dev server
// host so `npm run dev` + `uvicorn` works with no config.
const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://127.0.0.1:8000";
const DEMO_AUTH_TOKEN: string | undefined =
  import.meta.env.VITE_DEMO_AUTH_TOKEN as string | undefined;

function authHeaders(): Record<string, string> {
  if (!DEMO_AUTH_TOKEN) {
    return {};
  }
  return { Authorization: `Bearer ${DEMO_AUTH_TOKEN}` };
}

export function artifactDownloadUrl(artifactId: string): string {
  return `${API_BASE_URL}/api/v1/artifacts/${encodeURIComponent(artifactId)}/download`;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...authHeaders(),
        ...(init?.headers ?? {}),
      },
    });
  } catch (networkError) {
    throw new ApiClientError(
      "NETWORK_ERROR",
      networkError instanceof Error
        ? networkError.message
        : "Failed to reach the API.",
      null,
      0,
    );
  }

  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiClientError(
      "INTERNAL_ERROR",
      `Unexpected non-JSON response (HTTP ${response.status})`,
      null,
      response.status,
    );
  }

  if (envelope && envelope.success === true) {
    return envelope.data;
  }
  const error = envelope?.error;
  throw new ApiClientError(
    error?.code ?? "INTERNAL_ERROR",
    error?.message ?? `Request failed with HTTP ${response.status}`,
    error?.details ?? null,
    response.status,
  );
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const apiClient = {
  async createJob(req: JobCreateRequest): Promise<Job> {
    return request<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async listJobs(params?: {
    page?: number;
    page_size?: number;
    status?: JobStatus;
  }): Promise<PaginatedJobs> {
    const qs = buildQuery({
      page: params?.page,
      page_size: params?.page_size,
      status: params?.status,
    });
    return request<PaginatedJobs>(`/jobs${qs}`);
  },

  async getJob(jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}`);
  },

  async listJobTrials(jobId: string): Promise<TrialSummary[]> {
    return request<TrialSummary[]>(
      `/jobs/${encodeURIComponent(jobId)}/trials`,
    );
  },

  async getTrial(trialId: string): Promise<Trial> {
    return request<Trial>(`/trials/${encodeURIComponent(trialId)}`);
  },

  async getJobReport(jobId: string): Promise<JobReport> {
    return request<JobReport>(
      `/jobs/${encodeURIComponent(jobId)}/report`,
    );
  },

  async listJobArtifacts(jobId: string): Promise<Artifact[]> {
    return request<Artifact[]>(
      `/jobs/${encodeURIComponent(jobId)}/artifacts`,
    );
  },

  async fetchArtifactJson<T>(artifactId: string): Promise<T> {
    const url = artifactDownloadUrl(artifactId);
    let response: Response;
    try {
      response = await fetch(url, {
        headers: {
          Accept: "application/json",
          ...authHeaders(),
        },
      });
    } catch (networkError) {
      throw new ApiClientError(
        "NETWORK_ERROR",
        networkError instanceof Error
          ? networkError.message
          : "Failed to download artifact.",
        null,
        0,
      );
    }

    if (!response.ok) {
      throw new ApiClientError(
        "ARTIFACT_DOWNLOAD_FAILED",
        `Failed to download artifact JSON (HTTP ${response.status})`,
        null,
        response.status,
      );
    }

    const payloadText = await response.text();
    try {
      return JSON.parse(payloadText) as T;
    } catch {
      throw new ApiClientError(
        "ARTIFACT_NOT_JSON",
        "Artifact is not valid JSON.",
        null,
        response.status,
      );
    }
  },

  async cancelJob(jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    });
  },

  async rerunJob(jobId: string, req?: JobRerunRequest): Promise<Job> {
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}/rerun`, {
      method: "POST",
      body: JSON.stringify(req ?? {}),
    });
  },
};

export type ApiClient = typeof apiClient;
