// HTTP client for the DroneDream /api/v1 backend. It owns envelope parsing,
// desktop-runtime liveness checks, and the typed call surface used by pages.

import { isDesktopRuntime } from "../desktop/bridge";
import { getDesktopReadinessSession } from "../desktop/readiness";
import { getAuthAccessToken } from "../features/auth/authTokenStore";
import { publicDemoConsole } from "../features/demo/publicDemo";
import type {
  ApiEnvelope,
  Artifact,
  BackendCapabilitiesResponse,
  BatchCreateRequest,
  BatchJob,
  Job,
  JobCompareResponse,
  JobCreateRequest,
  DeleteJobResponse,
  ExperimentAssistantTurnRequest,
  ExperimentAssistantTurnResponse,
  JobUpdateRequest,
  JobRerunRequest,
  JobReport,
  PaginatedBatchJobs,
  JobStatus,
  PaginatedJobs,
  ParameterCatalogApiResponse,
  OptimizationHistory,
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
  const accessToken = getAuthAccessToken() ?? DEMO_AUTH_TOKEN;
  if (!accessToken) {
    return {};
  }
  return { Authorization: `Bearer ${accessToken}` };
}

export function artifactDownloadUrl(artifactId: string): string {
  return `${API_BASE_URL}/api/v1/artifacts/${encodeURIComponent(artifactId)}/download`;
}

async function triggerBrowserDownload(
  content: Blob,
  filename: string,
): Promise<void> {
  const objectUrl = URL.createObjectURL(content);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  requireRuntimeLiveness = false,
): Promise<T> {
  if (isDesktopRuntime() && requireRuntimeLiveness) {
    const readiness = getDesktopReadinessSession()?.snapshot;
    if (!readiness?.ready) {
      throw new ApiClientError(
        "DESKTOP_RUNTIME_NOT_READY",
        "The local DroneDream runtime has not been approved for this session. Open Settings and click Check environment before starting an experiment.",
      );
    }
  }

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

  // The HTTP status remains authoritative. A proxy, stale service worker, or
  // malformed backend must not turn a 4xx/5xx response into a successful
  // mutation merely by returning a body with `success: true`.
  if (response.ok && envelope && envelope.success === true) {
    return envelope.data;
  }
  const error = envelope?.error;
  throw new ApiClientError(
    error?.code ?? (response.ok ? "INTERNAL_ERROR" : "HTTP_ERROR"),
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
  async compileExperimentAssistantTurn(
    req: ExperimentAssistantTurnRequest,
  ): Promise<ExperimentAssistantTurnResponse> {
    return request<ExperimentAssistantTurnResponse>("/experiment-assistant/turn", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  async getCapabilities(): Promise<BackendCapabilitiesResponse> {
    return request<BackendCapabilitiesResponse>("/capabilities");
  },

  async getParameterCatalog(px4Version: string): Promise<ParameterCatalogApiResponse> {
    const qs = buildQuery({ px4_version: px4Version });
    return request<ParameterCatalogApiResponse>(`/parameter-catalog${qs}`);
  },

  async createJob(req: JobCreateRequest): Promise<Job> {
    return request<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify(req),
    }, true);
  },

  async listJobs(params?: {
    page?: number;
    page_size?: number;
    status?: JobStatus;
  }): Promise<PaginatedJobs> {
    if (publicDemoConsole) {
      return {
        items: [],
        page: params?.page ?? 1,
        page_size: params?.page_size ?? 20,
        total: 0,
      };
    }
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

  async updateJob(jobId: string, req: JobUpdateRequest): Promise<Job> {
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    });
  },
  async deleteJob(jobId: string): Promise<DeleteJobResponse> {
    return request<DeleteJobResponse>(`/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    });
  },

  async listJobTrials(jobId: string): Promise<TrialSummary[]> {
    // Keep the historical "all trials" client contract while the API reads
    // bounded pages. A job is capped at 10,000 trials by JobCreateRequest, so
    // this is at most twenty deterministic requests instead of one unbounded
    // database load.
    const pageSize = 500;
    const maxPages = 20;
    const items: TrialSummary[] = [];
    const seen = new Set<string>();
    for (let page = 1; page <= maxPages; page += 1) {
      const qs = buildQuery({ page, page_size: pageSize });
      const pageItems = await request<TrialSummary[]>(
        `/jobs/${encodeURIComponent(jobId)}/trials${qs}`,
      );
      let added = 0;
      for (const item of pageItems) {
        if (!seen.has(item.id)) {
          seen.add(item.id);
          items.push(item);
          added += 1;
        }
      }
      if (pageItems.length < pageSize) return items;
      if (added === 0) {
        throw new ApiClientError(
          "INVALID_PAGINATION",
          "The trial endpoint returned a repeated page.",
        );
      }
    }
    return items;
  },

  async listJobCandidates(jobId: string): Promise<OptimizationHistory> {
    return request<OptimizationHistory>(
      `/jobs/${encodeURIComponent(jobId)}/candidates`,
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

  async downloadArtifact(artifactId: string, filename?: string): Promise<void> {
    const url = artifactDownloadUrl(artifactId);
    let response: Response;
    try {
      response = await fetch(url, {
        headers: {
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
        `Failed to download artifact (HTTP ${response.status})`,
        null,
        response.status,
      );
    }

    await triggerBrowserDownload(
      await response.blob(),
      filename ?? `artifact-${artifactId}`,
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
    }, true);
  },

  async compareJobs(jobIds: string[]): Promise<JobCompareResponse> {
    return request<JobCompareResponse>("/jobs/compare", {
      method: "POST",
      body: JSON.stringify({ job_ids: jobIds }),
    });
  },

  compareJobsCsvUrl(jobIds: string[]): string {
    const joined = encodeURIComponent(jobIds.join(","));
    return `${API_BASE_URL}/api/v1/jobs/compare.csv?job_ids=${joined}`;
  },

  async downloadCompareJobsCsv(jobIds: string[]): Promise<void> {
    let response: Response;
    try {
      response = await fetch(this.compareJobsCsvUrl(jobIds), {
        headers: { ...authHeaders() },
      });
    } catch (networkError) {
      throw new ApiClientError(
        "NETWORK_ERROR",
        networkError instanceof Error
          ? networkError.message
          : "Failed to download comparison CSV.",
        null,
        0,
      );
    }
    if (!response.ok) {
      throw new ApiClientError(
        "COMPARE_CSV_DOWNLOAD_FAILED",
        `Failed to download compare CSV (HTTP ${response.status})`,
        null,
        response.status,
      );
    }
    await triggerBrowserDownload(
      await response.blob(),
      `job-compare-${jobIds.join("_")}.csv`,
    );
  },

  async createBatch(req: BatchCreateRequest): Promise<BatchJob> {
    return request<BatchJob>("/batches", {
      method: "POST",
      body: JSON.stringify(req),
    }, true);
  },

  async listBatches(params?: {
    page?: number;
    page_size?: number;
  }): Promise<PaginatedBatchJobs> {
    const qs = buildQuery({
      page: params?.page,
      page_size: params?.page_size,
    });
    return request<PaginatedBatchJobs>(`/batches${qs}`);
  },

  async getBatch(batchId: string): Promise<BatchJob> {
    return request<BatchJob>(`/batches/${encodeURIComponent(batchId)}`);
  },

  async listBatchJobs(batchId: string): Promise<Job[]> {
    return request<Job[]>(`/batches/${encodeURIComponent(batchId)}/jobs`);
  },

  async cancelBatch(batchId: string): Promise<BatchJob> {
    return request<BatchJob>(`/batches/${encodeURIComponent(batchId)}/cancel`, {
      method: "POST",
    });
  },
};

export type ApiClient = typeof apiClient;
